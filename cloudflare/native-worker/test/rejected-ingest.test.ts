import { describe, expect, it } from "vitest";
import { withWorker } from "./golden/harness";
import { fixedNow } from "./golden/paths";

const rejectedPayload = {
  schema_version: 1,
  source_id: "mac-rejected",
};

const rejectedResponse = {
  status: "error",
  error_type: "http_schema_invalid",
  message: "Missing required field: host",
};

async function seedKnownSource(db: D1Database): Promise<void> {
  await db.prepare(`
    INSERT INTO source_identities (
      source_id, host, machine, os_user, platform, first_seen_at, last_seen_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?)
  `).bind(
    "mac-rejected", "mac-rejected.local", "mac-rejected", "alice", "darwin",
    "2026-06-01T00:00:00.000Z", "2026-06-01T00:00:00.000Z",
  ).run();
}

describe.sequential("authenticated rejected ingest visibility", () => {
  it("upserts an authenticated schema rejection without changing its HTTP response", async () => {
    await withWorker({ now: fixedNow }, async ({ fetchRaw, db }) => {
      await seedKnownSource(db);
      for (let attempt = 0; attempt < 2; attempt += 1) {
        const response = await fetchRaw({
          method: "POST",
          path: "/ingest",
          auth: true,
          body: rejectedPayload,
        });
        expect(response.status).toBe(400);
        expect(JSON.parse(response.body.toString("utf8"))).toEqual(rejectedResponse);
      }

      const rows = await db.prepare(`
        SELECT source_id_claimed, error_type, path, day, first_seen_at, last_seen_at, count
        FROM rejected_ingest_attempts
      `).all<Record<string, string | number>>();
      expect(rows.results).toEqual([{
        source_id_claimed: "mac-rejected",
        error_type: "http_schema_invalid",
        path: "/ingest",
        day: "2026-06-03",
        first_seen_at: "2026-06-03T04:00:00.000Z",
        last_seen_at: "2026-06-03T04:00:00.000Z",
        count: 2,
      }]);
    });
  });

  it("lists recent rejected sources and error types in health versions", async () => {
    await withWorker({ now: fixedNow }, async ({ fetchRaw, db }) => {
      await seedKnownSource(db);
      await fetchRaw({ method: "POST", path: "/ingest", auth: true, body: rejectedPayload });
      await db.batch([
        db.prepare(`
          INSERT INTO rejected_ingest_attempts
            (source_id_claimed, error_type, path, day, first_seen_at, last_seen_at, count)
          VALUES (?, ?, ?, ?, ?, ?, ?)
        `).bind("outside-window", "http_schema_invalid", "/ingest", "2026-05-27", "2026-05-27T03:59:59.999Z", "2026-05-27T03:59:59.999Z", 1),
        db.prepare(`
          INSERT INTO rejected_ingest_attempts
            (source_id_claimed, error_type, path, day, first_seen_at, last_seen_at, count)
          VALUES (?, ?, ?, ?, ?, ?, ?)
        `).bind("on-boundary", "limit_schema_invalid", "/ingest-limits", "2026-05-27", "2026-05-27T04:00:00.000Z", "2026-05-27T04:00:00.000Z", 3),
      ]);

      const response = await fetchRaw({ method: "GET", path: "/api/health", auth: true });
      const health = JSON.parse(response.body.toString("utf8")) as Record<string, any>;

      expect(response.status).toBe(200);
      expect(health.versions.rejected_recent).toEqual([{
        source_id_claimed: "mac-rejected",
        error_type: "http_schema_invalid",
        path: "/ingest",
        last_seen_at: "2026-06-03T04:00:00.000Z",
        count: 1,
      }, {
        source_id_claimed: "on-boundary",
        error_type: "limit_schema_invalid",
        path: "/ingest-limits",
        last_seen_at: "2026-05-27T04:00:00.000Z",
        count: 3,
      }]);
    });
  });

  it("never persists or exposes an unrecognized source claim", async () => {
    await withWorker({ now: fixedNow }, async ({ fetchRaw, db }) => {
      for (const sourceId of [
        "/Users/alice/.codex/token",
        "secret-token-0123456789abcdef0123456789abcdef",
      ]) {
        const response = await fetchRaw({
          method: "POST",
          path: "/ingest",
          auth: true,
          body: { ...rejectedPayload, source_id: sourceId },
        });
        expect(response.status).toBe(400);
      }

      const rows = await db.prepare(`
        SELECT source_id_claimed, count FROM rejected_ingest_attempts
      `).all<{ source_id_claimed: string; count: number }>();
      const healthResponse = await fetchRaw({ method: "GET", path: "/api/health", auth: true });
      const health = JSON.parse(healthResponse.body.toString("utf8")) as Record<string, any>;

      expect(rows.results).toEqual([{ source_id_claimed: "unknown", count: 2 }]);
      expect(JSON.stringify(rows.results)).not.toContain("/Users/alice");
      expect(JSON.stringify(rows.results)).not.toContain("secret-token");
      expect(JSON.stringify(health.versions.rejected_recent)).not.toContain("secret-token");
      expect(health.versions.rejected_recent[0].source_id_claimed).toBe("unknown");
    });
  });

  it("uses the configured product timezone for the daily upsert key", async () => {
    await withWorker({
      now: "2026-06-03T00:30:00+08:00",
      bindings: { AIUSAGE_TIMEZONE: "Asia/Shanghai" },
    }, async ({ fetchRaw, db }) => {
      await seedKnownSource(db);
      await fetchRaw({ method: "POST", path: "/ingest", auth: true, body: rejectedPayload });
      const row = await db.prepare("SELECT day FROM rejected_ingest_attempts").first<{ day: string }>();
      expect(row?.day).toBe("2026-06-03");
    });
  });

  it("does not record an unauthenticated invalid payload", async () => {
    await withWorker({ now: fixedNow }, async ({ fetchRaw, db }) => {
      const response = await fetchRaw({
        method: "POST",
        path: "/ingest",
        auth: "wrong-token",
        body: rejectedPayload,
      });
      const count = await db.prepare("SELECT count(*) AS count FROM rejected_ingest_attempts")
        .first<{ count: number }>();

      expect(response.status).toBe(401);
      expect(JSON.parse(response.body.toString("utf8"))).toEqual({
        status: "error",
        error_type: "http_auth_failed",
        message: "Invalid or missing token",
      });
      expect(count?.count).toBe(0);
    });
  });

  it("prunes rejected attempts older than seven days", async () => {
    await withWorker({ now: fixedNow }, async ({ mf, db }) => {
      await db.batch([
        db.prepare(`
          INSERT INTO rejected_ingest_attempts
            (source_id_claimed, error_type, path, day, first_seen_at, last_seen_at, count)
          VALUES (?, ?, ?, ?, ?, ?, ?)
        `).bind("old-source", "http_schema_invalid", "/ingest", "2026-05-20", "2026-05-20T00:00:00.000Z", "2026-05-20T00:00:00.000Z", 1),
        db.prepare(`
          INSERT INTO rejected_ingest_attempts
            (source_id_claimed, error_type, path, day, first_seen_at, last_seen_at, count)
          VALUES (?, ?, ?, ?, ?, ?, ?)
        `).bind("recent-source", "limit_schema_invalid", "/ingest-limits", "2026-06-01", "2026-06-01T00:00:00.000Z", "2026-06-01T00:00:00.000Z", 1),
        db.prepare(`
          INSERT INTO rejected_ingest_attempts
            (source_id_claimed, error_type, path, day, first_seen_at, last_seen_at, count)
          VALUES (?, ?, ?, ?, ?, ?, ?)
        `).bind("boundary-source", "http_schema_invalid", "/ingest", "2026-05-27", "2026-05-27T04:00:00.000Z", "2026-05-27T04:00:00.000Z", 1),
      ]);

      const worker = await mf.getWorker();
      await worker.scheduled({
        scheduledTime: new Date(fixedNow).getTime(),
        cron: "17 3 * * *",
      });

      const rows = await db.prepare(`
        SELECT source_id_claimed, error_type, path
        FROM rejected_ingest_attempts
        ORDER BY source_id_claimed
      `).all<Record<string, string>>();
      expect(rows.results).toEqual([
        {
          source_id_claimed: "boundary-source",
          error_type: "http_schema_invalid",
          path: "/ingest",
        },
        {
          source_id_claimed: "recent-source",
          error_type: "limit_schema_invalid",
          path: "/ingest-limits",
        },
      ]);
    });
  });

  it("keeps the original rejection response when best-effort recording fails", async () => {
    await withWorker({ now: fixedNow }, async ({ fetchRaw, db }) => {
      await seedKnownSource(db);
      await db.prepare(`
        CREATE TRIGGER force_rejected_attempt_failure
        BEFORE INSERT ON rejected_ingest_attempts
        BEGIN
          SELECT RAISE(FAIL, 'forced recording failure');
        END
      `).run();
      try {
        const response = await fetchRaw({
          method: "POST",
          path: "/ingest",
          auth: true,
          body: rejectedPayload,
        });
        expect(response.status).toBe(400);
        expect(JSON.parse(response.body.toString("utf8"))).toEqual(rejectedResponse);
      } finally {
        await db.prepare("DROP TRIGGER force_rejected_attempt_failure").run();
      }
    });
  });
});

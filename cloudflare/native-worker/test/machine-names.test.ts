import { describe, expect, it } from "vitest";
import { withStableMachineName } from "../src/read-model/machine-names";
import { sourceIdentityStatement } from "../src/write-model/statements";
import { withWorker } from "./golden/harness";
import { collectModelPayloads } from "./golden/navigation-models";

const historical = {
  source_id: "paired-mac", machine_id: "192.0.2.8", machine_name: "192.0.2.8",
  os_user: "tester", total_tokens: 412,
};

describe("historical macOS machine names", () => {
  const identities = {
    "paired-mac": { platform: "darwin", machine: "MacBook-Air.local", os_user: "tester" },
  };

  it("assigns old IP names on the same source to its current stable name", () => {
    expect(withStableMachineName(historical, identities)).toEqual({
      ...historical, machine_id: "MacBook-Air.local", machine_name: "MacBook-Air.local",
    });
    const ipv6 = { ...historical, machine_id: "fe80::1%en0", machine_name: "fe80::1%en0" };
    expect(withStableMachineName(ipv6, identities).machine_name).toBe("MacBook-Air.local");
  });

  it("preserves different sources, users and named devices", () => {
    const genericMac = { ...historical, machine_id: "Mac", machine_name: "Mac" };
    for (const row of [
      { ...historical, source_id: "different-mac" },
      { ...historical, os_user: "different-user" },
      { ...historical, machine_name: "ExplicitName" },
      { ...historical, machine_id: "explicit-machine-id" },
      { ...genericMac, source_id: "different-mac" },
      { ...genericMac, os_user: "different-user" },
      { ...genericMac, machine_name: "ExplicitName" },
      { ...genericMac, machine_id: "custom-id", machine_name: "custom-id" },
    ]) {
      expect(withStableMachineName(row, identities)).toBe(row);
    }
  });

  it("retains source identity where no stable macOS name has arrived", () => {
    for (const identity of [
      { ...identities["paired-mac"], machine: "192.0.2.9" },
      { ...identities["paired-mac"], platform: "linux" },
    ]) {
      expect(withStableMachineName(historical, { "paired-mac": identity })).toBe(historical);
    }
  });
});

it.each([
  { oldName: "192.0.2.8", period: "week&offset=0" },
  { oldName: "Mac", period: "month&offset=0&statistics=client" },
])("shows one paired Mac while preserving another source named $oldName", async ({ oldName, period }) => {
  const days = ["2026-09-21", "2026-09-22", "2026-09-23"];
  const names = [oldName, "192.0.2.19", "MacBook-Air.local"];
  await withWorker({ now: "2026-09-23T12:05:00+08:00" }, async ({ fetchRaw }) => {
    for (const [index, day] of days.entries()) {
      const [mac, linux] = collectModelPayloads(day);
      for (const payload of [
        { ...mac, machine: names[index], host: names[index] },
        { ...linux, machine: names[0], host: names[0] },
      ]) {
        const response = await fetchRaw({ method: "POST", path: "/ingest", auth: true, body: payload });
        expect(response.status).toBe(200);
      }
    }
    const path = `/api/mobile/summary?period=${period}`;
    const response = await fetchRaw({ method: "GET", path, auth: true });
    expect(response.status).toBe(200);
    const summary = JSON.parse(response.body.toString());
    expect(summary.period.total_tokens).toBe(3000);
    expect(summary.breakdown.by_machine).toHaveLength(2);
    expect(summary.breakdown.by_machine).toEqual(expect.arrayContaining([
      expect.objectContaining({ id: names[2], tokens: 1950, source_ids: ["model-mac"] }),
      expect.objectContaining({ id: names[0], tokens: 1050, source_ids: ["model-linux"] }),
    ]));
    const filtered = await fetchRaw({ method: "GET", path: `${path}&machine=${names[2]}`, auth: true });
    expect(filtered.status).toBe(200);
    const mac = JSON.parse(filtered.body.toString());
    expect(mac.period.total_tokens).toBe(1950);
    expect(mac.breakdown.by_source[0].agents.flatMap((entry: { models: { tokens: number }[] }) => entry.models)
      .reduce((total: number, model: { tokens: number }) => total + model.tokens, 0)).toBe(1950);
  });
});

it("keeps the newest source identity when an earlier concurrent batch writes last", async () => {
  await withWorker({ now: "2026-09-23T12:05:00+08:00" }, async ({ db }) => {
    const [mac] = collectModelPayloads("2026-09-23");
    const before = { ...mac, host: "192.0.2.8", machine: "192.0.2.8" };
    const after = { ...mac, host: "MacBook-Air.local", machine: "MacBook-Air.local" };
    const delayed = sourceIdentityStatement(db, before, "2026-09-23T12:00:00+08:00");
    const newIdentity = sourceIdentityStatement(db, after, "2026-09-23T04:02:00Z");
    await db.batch([newIdentity]);
    await db.batch([delayed]);
    expect(await db.prepare("SELECT machine, last_seen_at FROM source_identities").first()).toEqual({
      machine: "MacBook-Air.local", last_seen_at: "2026-09-23T04:02:00Z",
    });
  });
});

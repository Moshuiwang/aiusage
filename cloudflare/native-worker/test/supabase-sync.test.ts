import { describe, expect, it, vi } from "vitest";
import { syncDailyRollupsToSupabase } from "../src/supabase-sync";

describe("Supabase daily rollup sync", () => {
  it("upserts the selected daily rollups and records a successful sync run", async () => {
    const db = {
      prepare: vi.fn().mockReturnValue({
        bind: vi.fn().mockReturnValue({
          all: vi.fn().mockResolvedValue({
            results: [{
              date: "2026-07-26",
              bucket_start: "2026-07-26T00:00:00+08:00",
              bucket_end: "2026-07-26T23:59:59+08:00",
              source_id: "macbook",
              machine_id: "macbook",
              os_user: "wang",
              ai_provider: "openai",
              ai_account_id: "work",
              agent: "codex",
              client: "codex",
              attribution_confidence: "observed",
              provenance: "usage_ledger",
              input_tokens: 10,
              output_tokens: 20,
              cache_creation_tokens: 0,
              cache_read_tokens: 0,
              reasoning_output_tokens: 3,
              total_tokens: 33,
              event_count: 1,
              session_count: 1,
              fact_count: 1,
            }],
          }),
        }),
      }),
    } as unknown as D1Database;
    const fetcher = vi.fn().mockResolvedValue(new Response("", { status: 201 }));

    const result = await syncDailyRollupsToSupabase({
      db,
      supabaseUrl: "https://example.supabase.co",
      secretKey: "test-secret",
      now: new Date("2026-07-27T00:00:00.000Z"),
      fetcher,
    });

    expect(result).toEqual({ rowsSynced: 1 });
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(fetcher.mock.calls[0]?.[0]).toBe("https://example.supabase.co/rest/v1/aiusage_daily_rollups?on_conflict=date%2Csource_id%2Cmachine_id%2Cos_user%2Cai_provider%2Cai_account_id%2Cagent%2Cclient%2Cattribution_confidence%2Cprovenance");
    expect(fetcher.mock.calls[0]?.[1]).toMatchObject({ method: "POST" });
    expect(JSON.parse(String(fetcher.mock.calls[0]?.[1]?.body))).toMatchObject([{ total_tokens: 33 }]);
    expect(fetcher.mock.calls[1]?.[0]).toBe("https://example.supabase.co/rest/v1/aiusage_sync_runs");
    expect(JSON.parse(String(fetcher.mock.calls[1]?.[1]?.body))).toMatchObject({ status: "ok", rows_synced: 1 });
  });

  it("does not record a successful run when Supabase rejects the rollup write", async () => {
    const db = {
      prepare: vi.fn().mockReturnValue({
        bind: vi.fn().mockReturnValue({ all: vi.fn().mockResolvedValue({ results: [] }) }),
      }),
    } as unknown as D1Database;
    const fetcher = vi.fn().mockResolvedValue(new Response("denied", { status: 401 }));

    await expect(syncDailyRollupsToSupabase({
      db,
      supabaseUrl: "https://example.supabase.co",
      secretKey: "test-secret",
      now: new Date("2026-07-27T00:00:00.000Z"),
      fetcher,
    })).rejects.toThrow("Supabase sync request failed: 401");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});

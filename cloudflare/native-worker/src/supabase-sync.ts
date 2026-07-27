const DAILY_ROLLUP_CONFLICT_COLUMNS = [
  "date",
  "source_id",
  "machine_id",
  "os_user",
  "ai_provider",
  "ai_account_id",
  "agent",
  "client",
  "attribution_confidence",
  "provenance",
].join(",");

const DAILY_ROLLUP_LOOKBACK_DAYS = 90;

type DailyRollup = Record<string, unknown>;

export type SupabaseSyncOptions = {
  db: D1Database;
  supabaseUrl: string;
  secretKey: string;
  now: Date;
  fetcher?: typeof fetch;
};

export async function syncDailyRollupsToSupabase({
  db,
  supabaseUrl,
  secretKey,
  now,
  fetcher = fetch,
}: SupabaseSyncOptions): Promise<{ rowsSynced: number }> {
  const cutoffDate = new Date(now.getTime() - DAILY_ROLLUP_LOOKBACK_DAYS * 24 * 60 * 60 * 1000)
    .toISOString()
    .slice(0, 10);
  const result = await db.prepare(`
    SELECT
      date, bucket_start, bucket_end, source_id, machine_id, os_user, ai_provider, ai_account_id,
      agent, client, attribution_confidence, provenance, input_tokens, output_tokens,
      cache_creation_tokens, cache_read_tokens, reasoning_output_tokens, total_tokens,
      event_count, session_count, fact_count
    FROM usage_daily_rollups
    WHERE date >= ?
    ORDER BY date, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client
  `).bind(cutoffDate).all<DailyRollup>();
  const rows = result.results ?? [];
  const baseUrl = supabaseUrl.replace(/\/$/, "");
  const headers = {
    apikey: secretKey,
    Authorization: `Bearer ${secretKey}`,
    "Content-Type": "application/json",
  };

  if (rows.length > 0) {
    await assertSuccess(await fetcher(
      `${baseUrl}/rest/v1/aiusage_daily_rollups?${new URLSearchParams({ on_conflict: DAILY_ROLLUP_CONFLICT_COLUMNS })}`,
      {
        method: "POST",
        headers: { ...headers, Prefer: "resolution=merge-duplicates,return=minimal" },
        body: JSON.stringify(rows.map((row) => ({ ...row, synced_at: now.toISOString() }))),
      },
    ));
  }

  await assertSuccess(await fetcher(`${baseUrl}/rest/v1/aiusage_sync_runs`, {
    method: "POST",
    headers: { ...headers, Prefer: "return=minimal" },
    body: JSON.stringify({
      started_at: now.toISOString(),
      completed_at: now.toISOString(),
      status: "ok",
      rows_synced: rows.length,
      source_cutoff_date: cutoffDate,
    }),
  }));
  return { rowsSynced: rows.length };
}

async function assertSuccess(response: Response): Promise<void> {
  if (!response.ok) throw new Error(`Supabase sync request failed: ${response.status}`);
}

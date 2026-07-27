-- Execute once in the SOFA Base SQL editor. These tables are a one-way,
-- non-user-facing replica of AI Usage D1 summaries.
CREATE TABLE IF NOT EXISTS public.aiusage_daily_rollups (
  date date NOT NULL,
  bucket_start text NOT NULL,
  bucket_end text NOT NULL,
  source_id text NOT NULL,
  machine_id text NOT NULL,
  os_user text NOT NULL,
  ai_provider text NOT NULL,
  ai_account_id text NOT NULL,
  agent text NOT NULL,
  client text NOT NULL,
  attribution_confidence text NOT NULL,
  provenance text NOT NULL,
  input_tokens bigint NOT NULL,
  output_tokens bigint NOT NULL,
  cache_creation_tokens bigint NOT NULL,
  cache_read_tokens bigint NOT NULL,
  reasoning_output_tokens bigint NOT NULL,
  total_tokens bigint NOT NULL,
  event_count integer NOT NULL,
  session_count integer NOT NULL,
  fact_count integer NOT NULL,
  synced_at timestamptz NOT NULL,
  PRIMARY KEY (
    date, source_id, machine_id, os_user, ai_provider, ai_account_id,
    agent, client, attribution_confidence, provenance
  )
);

CREATE TABLE IF NOT EXISTS public.aiusage_sync_runs (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  started_at timestamptz NOT NULL,
  completed_at timestamptz NOT NULL,
  status text NOT NULL CHECK (status IN ('ok')),
  rows_synced integer NOT NULL,
  source_cutoff_date date NOT NULL
);

ALTER TABLE public.aiusage_daily_rollups ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.aiusage_sync_runs ENABLE ROW LEVEL SECURITY;
GRANT ALL ON public.aiusage_daily_rollups TO service_role;
GRANT ALL ON public.aiusage_sync_runs TO service_role;
GRANT USAGE, SELECT ON SEQUENCE public.aiusage_sync_runs_id_seq TO service_role;

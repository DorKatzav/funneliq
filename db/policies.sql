-- Row Level Security for FunnelIQ. Run after schema.sql. Idempotent.
--
-- Effect:
--   * anon (no JWT)        -> funnel_records: 0 rows ; prediction_log: 0 rows
--   * authenticated user   -> funnel_records: all rows (read-only) ; prediction_log: only their own rows
--   * service_role         -> bypasses RLS (used ONLY by scripts/load_data.py, locally)

alter table public.funnel_records enable row level security;
alter table public.prediction_log enable row level security;

drop policy if exists "authenticated users can read funnel records" on public.funnel_records;
create policy "authenticated users can read funnel records"
  on public.funnel_records
  for select
  to authenticated
  using (true);

drop policy if exists "users insert their own predictions" on public.prediction_log;
create policy "users insert their own predictions"
  on public.prediction_log
  for insert
  to authenticated
  with check (user_id = auth.uid());

drop policy if exists "users read their own predictions" on public.prediction_log;
create policy "users read their own predictions"
  on public.prediction_log
  for select
  to authenticated
  using (user_id = auth.uid());

-- No insert/update/delete policies on funnel_records: the API cannot modify the dataset.

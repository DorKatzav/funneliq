-- FunnelIQ schema. Run in the Supabase SQL editor (then run policies.sql).
-- Idempotent: safe to re-run.

create table if not exists public.funnel_records (
  id integer primary key,                       -- row_id from the CSV (0..3499)
  ad_budget integer not null,
  num_leads integer not null,
  leads_answered integer not null,
  leads_not_answered integer not null,
  followup_1 integer not null,
  followup_2 integer not null,
  followup_3 integer not null,
  followup_4 integer not null,
  followup_5 integer not null,
  not_closed integer not null,
  closed integer not null,
  calls_to_closed integer not null,
  calls_to_not_closed integer not null,
  customer_acquisition_cost integer not null,
  ltv_months real,                              -- 4 rows missing in the source
  purchased smallint not null,
  upsell smallint not null,
  cumulative_profit real,                       -- 29 rows missing in the source
  referred boolean not null,
  budget_tier text generated always as (
    case
      when ad_budget <= 1500 then 'Low'
      when ad_budget <= 5000 then 'Mid'
      else 'High'
    end
  ) stored
);

comment on table public.funnel_records is 'One row per customer/campaign record from funnel_marketing_data.csv';

create index if not exists funnel_records_budget_tier_idx on public.funnel_records (budget_tier);

-- Every prediction a signed-in user requests is logged here (written through RLS with the user''s token).
create table if not exists public.prediction_log (
  id bigserial primary key,
  user_id uuid not null default auth.uid(),
  model text not null,
  input jsonb not null,
  output jsonb not null,
  created_at timestamptz not null default now()
);

create index if not exists prediction_log_user_created_idx on public.prediction_log (user_id, created_at desc);

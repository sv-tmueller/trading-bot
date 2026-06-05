-- MVP 2.0 schema (Supabase/Postgres). Ports storage/schema.sql (SQLite) with
-- Postgres-native types, plus bot_config for the runtime pause flag.

create table if not exists regime_state (
    date date primary key,
    spy_close double precision not null,
    spy_sma200 double precision not null,
    target_state text not null check (target_state in ('LONG','CASH')),
    current_state text not null check (current_state in ('LONG','CASH')),
    position_drawdown_pct double precision,
    kill_switch_active boolean not null default false,
    kill_switch_fired_at timestamptz,
    created_at timestamptz not null default now()
);

create table if not exists trades (
    id bigint generated always as identity primary key,
    symbol text not null,
    side text not null check (side in ('BUY','SELL')),
    qty integer not null,
    fill_price double precision not null,
    fill_time timestamptz not null,
    broker_order_id text not null,
    reason text not null check (reason in
        ('regime_flip_long','regime_flip_cash','kill_switch','panic_cli')),
    created_at timestamptz not null default now()
);

create table if not exists audit_log (
    id bigint generated always as identity primary key,
    script_name text not null,
    started_at timestamptz not null,
    finished_at timestamptz,
    outcome text,
    notes text
);

create table if not exists bot_config (
    key text primary key,
    value text not null,
    updated_at timestamptz not null default now()
);

insert into bot_config (key, value) values ('paused', 'false')
on conflict (key) do nothing;

-- Keep bot_config.updated_at honest on every UPDATE (DEFAULT only fires on
-- INSERT). The app layer also sets it explicitly, but the trigger removes the
-- footgun for any future writer — important for forensic timestamps.
create or replace function set_updated_at() returns trigger language plpgsql as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

create trigger bot_config_updated_at
    before update on bot_config
    for each row execute procedure set_updated_at();

-- Edge Functions connect with the service-role key (bypasses RLS). Enable RLS
-- and add no policies so anon/public access is denied by default.
alter table regime_state enable row level security;
alter table trades        enable row level security;
alter table audit_log     enable row level security;
alter table bot_config    enable row level security;

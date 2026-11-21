-- APPLIED 2026-11-16 to Supabase project rlwidfirrdwolaywjpca, with the owner's go-ahead, as the
-- migration `create_fantrax_api_schema`. Kept here as the record; the statements are idempotent.
-- Generic multi-league tables for the Fantrax API pipeline.
-- Every table is keyed by league_id so any league (any scoring format, with or
-- without contracts) fits. contract/salary are NULL for leagues without them.
--
-- Verified after applying: 7 tables, RLS on for all, `anon` and `authenticated` have no table
-- privileges and no schema usage, columns and primary keys match fantrax_api_load.py, all tables
-- empty (0 rows). NOT yet checked: the loader against these tables (only tested with a fake
-- cursor), because nothing has been loaded. The first live load is that test.
-- No read policies exist yet: the Decision Engine and Power BI cannot read these tables until the
-- read path is decided (policies, exposed schema, or views in `public`).
create schema if not exists fantrax_api;

create table if not exists fantrax_api.leagues (
  league_id text primary key, sport text, name text, season int, scoring_type text,
  scoring jsonb, roster_rules jsonb, start_date text, end_date text, fetched_at timestamptz default now());
create table if not exists fantrax_api.teams (
  league_id text references fantrax_api.leagues, team_id text, name text, division text,
  primary key (league_id, team_id));
create table if not exists fantrax_api.rosters (
  league_id text, team_id text, player_id text, period int, position text,
  status text, contract text, salary numeric, fetched_at timestamptz default now(),
  primary key (league_id, team_id, player_id));
create table if not exists fantrax_api.standings (
  league_id text, team_id text, rank int, record text, win_pct numeric,
  games_back numeric, total_points_for numeric, fetched_at timestamptz default now(),
  primary key (league_id, team_id));
create table if not exists fantrax_api.draft_picks (
  league_id text, year int, round int, original_team_id text, current_team_id text,
  primary key (league_id, year, round, original_team_id));
create table if not exists fantrax_api.draft_results (
  league_id text, division text, round int, pick int, team_id text, player_id text,
  picked_at timestamptz, primary key (league_id, division, pick));
create table if not exists fantrax_api.players (
  player_id text, sport text, name text, team text, position text,
  primary key (sport, player_id));

-- Secure by default: RLS on, no policies. The loader connects as the database owner and bypasses
-- RLS. Nothing else can read these tables until you add a policy on purpose, e.g. (decide first):
--   create policy "read all" on fantrax_api.rosters for select to anon using (true);
-- Note: PostgREST only serves schemas listed under API settings -> Exposed schemas.
alter table fantrax_api.leagues       enable row level security;
alter table fantrax_api.teams         enable row level security;
alter table fantrax_api.rosters       enable row level security;
alter table fantrax_api.standings     enable row level security;
alter table fantrax_api.draft_picks   enable row level security;
alter table fantrax_api.draft_results enable row level security;
alter table fantrax_api.players       enable row level security;

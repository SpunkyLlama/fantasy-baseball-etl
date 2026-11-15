-- DRAFT. Not applied. Generic multi-league tables for the Fantrax API pipeline.
-- Every table is keyed by league_id so any league (any scoring format, with or
-- without contracts) fits. contract/salary are NULL for leagues without them.
-- Review before applying; applying touches live Supabase and needs owner go-ahead.
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

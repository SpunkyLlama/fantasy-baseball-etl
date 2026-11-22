-- DRAFT, NOT APPLIED. Read path for the Fantrax API tables (fantrax_api.*), for the Decision Engine.
-- Applying this changes live Supabase: needs the owner's go-ahead first (CLAUDE.md, "Live data").
--
-- Design (owner decision 2026-11-22: same openness as today's public.* tables, i.e. readable with
-- the anon key; Power BI is separate, see below):
--   * The fantrax_api schema is NOT added to the API's Exposed schemas, so PostgREST cannot serve its
--     tables directly. The only way in over the API is the public.v_api_* views below.
--   * The views are security_invoker, so Postgres checks the caller's rights and the RLS policies on
--     the base tables. (Your 18 existing public.v_* views are not security_invoker: they run as the
--     owner and bypass RLS. These are stricter on purpose; Supabase's advisor flags the other kind.)
--   * Views created in `public` get ALL privileges for anon/authenticated by default (pg_default_acl),
--     so each view is revoked first and then granted SELECT only.
--   * Read only: there are no INSERT/UPDATE/DELETE policies or grants.
-- Idempotent: safe to re-run.

-- 1. Let anon/authenticated read the base tables, through RLS policies.
grant usage on schema fantrax_api to anon, authenticated;
grant select on fantrax_api.leagues, fantrax_api.teams, fantrax_api.rosters, fantrax_api.standings,
               fantrax_api.draft_picks, fantrax_api.draft_results, fantrax_api.players
  to anon, authenticated;

do $$
declare t text;
begin
  foreach t in array array['leagues','teams','rosters','standings','draft_picks','draft_results','players']
  loop
    execute format('drop policy if exists api_read_%1$s on fantrax_api.%1$s', t);
    execute format('create policy api_read_%1$s on fantrax_api.%1$s for select to anon, authenticated using (true)', t);
  end loop;
end $$;

-- 2. Views in public. Names come from teams / players. fantrax_api.players is empty until a
--    load with --players, so player_name is NULL until then (the left join keeps the rows).
create or replace view public.v_api_rosters with (security_invoker = true) as
select r.league_id, l.name as league_name, r.team_id, t.name as team_name, t.division,
       r.player_id, p.name as player_name, r.position, r.status, r.contract, r.salary, r.period
from fantrax_api.rosters r
join fantrax_api.leagues l on l.league_id = r.league_id
join fantrax_api.teams   t on t.league_id = r.league_id and t.team_id = r.team_id
left join fantrax_api.players p on p.player_id = r.player_id and p.sport = l.sport;

create or replace view public.v_api_standings with (security_invoker = true) as
select s.league_id, l.name as league_name, s.team_id, t.name as team_name, t.division,
       s.rank, s.record, s.win_pct, s.games_back, s.total_points_for
from fantrax_api.standings s
join fantrax_api.leagues l on l.league_id = s.league_id
join fantrax_api.teams   t on t.league_id = s.league_id and t.team_id = s.team_id;

create or replace view public.v_api_draft_results with (security_invoker = true) as
select d.league_id, l.name as league_name, d.division, d.round, d.pick, d.team_id,
       t.name as team_name, d.player_id, p.name as player_name, d.picked_at
from fantrax_api.draft_results d
join fantrax_api.leagues l on l.league_id = d.league_id
left join fantrax_api.teams t on t.league_id = d.league_id and t.team_id = d.team_id
left join fantrax_api.players p on p.player_id = d.player_id and p.sport = l.sport;

create or replace view public.v_api_draft_picks with (security_invoker = true) as
select k.league_id, l.name as league_name, k.year, k.round,
       k.original_team_id, o.name as original_team_name,
       k.current_team_id,  c.name as current_team_name
from fantrax_api.draft_picks k
join fantrax_api.leagues l on l.league_id = k.league_id
left join fantrax_api.teams o on o.league_id = k.league_id and o.team_id = k.original_team_id
left join fantrax_api.teams c on c.league_id = k.league_id and c.team_id = k.current_team_id;

-- 3. SELECT only for anon/authenticated (new views start with every privilege).
do $$
declare v text;
begin
  foreach v in array array['v_api_rosters','v_api_standings','v_api_draft_results','v_api_draft_picks']
  loop
    execute format('revoke all on public.%I from anon, authenticated', v);
    execute format('grant select on public.%I to anon, authenticated', v);
  end loop;
end $$;

-- Power BI is NOT covered here. It connects over ODBC (DSN PostgreSQL35W) straight to Postgres, not
-- through the API, so it needs no policy or view. If that DSN logs in as `postgres` (not checked) it
-- can already see fantrax_api.* because the owner bypasses RLS. A dedicated read-only role is the
-- tidier option later: create role ... login; grant usage on schema fantrax_api; grant select on all
-- tables in schema fantrax_api; and point the DSN at it.

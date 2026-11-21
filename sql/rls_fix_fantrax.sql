-- APPLIED 2026-11-16 to Supabase project rlwidfirrdwolaywjpca, with the owner's go-ahead, as the
-- migration `enable_rls_fantrax_18_tables` (steps 1 and 2 below). Kept here as the record.
-- Drafted 2026-11-15 from read-only inspection of the live database.
--
-- HOW IT WAS APPLIED: steps 1 and 2 were run through the migration tool, NOT inside the
-- begin/commit wrapper below, and the step 3 verification was run separately. Verified after applying:
--   * all 18 tables: RLS on (0 off); `anon` has no SELECT and no write privilege on any of them
--   * as `anon`: a direct read of fantrax.savant_metrics fails with "permission denied" (intended)
--   * as `anon`: the public views (v_league_rosters, v_hitter_stats, v_pitcher_stats,
--     v_league_financials, v_team_gap_priority, v_contract_decision_summary, v_cap_health,
--     v_player_projections, v_pick_valuations) and public.contract_decisions / public.teams still return rows
-- NOT checked: index.html in a browser, a Power BI refresh, or the next etl.yml / Savant run.
-- To undo, use the ROLLBACK block at the bottom of this file.
--
-- WHAT THE ADVISORY FLAGGED: 18 tables in schema `fantrax` have Row Level Security off.
-- WHAT WAS ACTUALLY EXPOSED BEFORE THIS FIX (checked with has_table_privilege):
--   * 10 tables: `anon` has NO privileges at all -> already unreachable through the API.
--       Fantrax_HOD_Drafts, Fantrax_Players_{Hitters,Pitchers}_{Topps,Rawlings},
--       Fantrax_Standings, Fantrax_Standings_Hit, Fantrax_Standings_Pit,
--       Fantrax_Transaction_History, player_snapshots
--   * 8 tables: `anon` can SELECT (read only, no writes) -> readable by anyone with the anon key
--       via the REST API (Accept-Profile: fantrax):
--       cap_hit_overrides, contract_decisions, draft_picks, savant_metrics,
--       fv_position_multipliers, fv_to_fpts_hitter, fv_to_fpts_pitcher, level_reach_discount
--   * No anon INSERT/UPDATE/DELETE on any of the 18, so "modify every row" in the advisory is overstated.
--
-- WHY THIS IS SAFE FOR EXISTING READERS (all verified, none of them is `anon`/`authenticated`):
--   * Every public.v_* / fantrax.v_* view is owned by `postgres` with no security_invoker, so views
--     read these tables as the owner. Table owners bypass RLS (none of the tables is FORCEd).
--   * The loaders (etl.yml, load_supabase_actions.py) connect as `postgres` (owner, BYPASSRLS).
--   * SECURITY DEFINER functions (take_daily_snapshot, sync_*_to_fantrax, upsert_*) run as owner.
--   * The only other login role is `authenticator` (PostgREST itself). Power BI / any direct
--     Postgres connection must be `postgres`; if yours uses another role, tell me BEFORE applying.
--   * index.html never reads these 18 tables directly: it reads views, plus public.* tables and
--     fantrax.{owner_profiles,trading_reputation,team_map,trade_feedback}, all of which already have RLS.
--   * The Savant ETL writes public.savant_metrics with the service key (BYPASSRLS), untouched.
--
-- WHAT THIS CHANGES: with RLS on and no policy, `anon` / `authenticated` see zero rows from these
-- tables even if a grant is added later. Step 2 also revokes the 8 direct anon SELECT grants.
-- Reversible: see ROLLBACK at the bottom.

begin;

-- 1. Enable RLS on all 18 (idempotent). No policies on purpose: nothing legitimate reads them as anon.
alter table fantrax."Fantrax_HOD_Drafts"                  enable row level security;
alter table fantrax."Fantrax_Players_Hitters_Rawlings"    enable row level security;
alter table fantrax."Fantrax_Players_Hitters_Topps"       enable row level security;
alter table fantrax."Fantrax_Players_Pitchers_Rawlings"   enable row level security;
alter table fantrax."Fantrax_Players_Pitchers_Topps"      enable row level security;
alter table fantrax."Fantrax_Standings"                   enable row level security;
alter table fantrax."Fantrax_Standings_Hit"               enable row level security;
alter table fantrax."Fantrax_Standings_Pit"               enable row level security;
alter table fantrax."Fantrax_Transaction_History"         enable row level security;
alter table fantrax.cap_hit_overrides                     enable row level security;
alter table fantrax.contract_decisions                    enable row level security;
alter table fantrax.draft_picks                           enable row level security;
alter table fantrax.fv_position_multipliers               enable row level security;
alter table fantrax.fv_to_fpts_hitter                     enable row level security;
alter table fantrax.fv_to_fpts_pitcher                    enable row level security;
alter table fantrax.level_reach_discount                  enable row level security;
alter table fantrax.player_snapshots                      enable row level security;
alter table fantrax.savant_metrics                        enable row level security;

-- 2. Belt and braces: take away the 8 direct anon read grants (RLS alone already hides the rows).
--    Skip this step if you WANT anon to read these tables; then add, per table, e.g.:
--      create policy anon_read on fantrax.savant_metrics for select to anon using (true);
revoke select on fantrax.cap_hit_overrides, fantrax.contract_decisions, fantrax.draft_picks,
                 fantrax.savant_metrics, fantrax.fv_position_multipliers,
                 fantrax.fv_to_fpts_hitter, fantrax.fv_to_fpts_pitcher, fantrax.level_reach_discount
  from anon;

-- 3. VERIFY inside the transaction. Expect: 0 rows from the first query, and 0 from the second.
select c.relname as still_without_rls
from pg_class c join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'fantrax' and c.relkind = 'r' and not c.relrowsecurity;

select c.relname as anon_can_still_read
from pg_class c join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'fantrax' and c.relkind = 'r'
  and c.relname in ('cap_hit_overrides','contract_decisions','draft_picks','savant_metrics',
                    'fv_position_multipliers','fv_to_fpts_hitter','fv_to_fpts_pitcher','level_reach_discount')
  and has_table_privilege('anon', c.oid, 'select');

-- Views must still work (they run as owner). Expect a number, not an error:
select count(*) as v_league_rosters_rows from public.v_league_rosters;
select count(*) as v_hitter_stats_rows   from public.v_hitter_stats;

-- (Not used: already applied, see the header.) Originally: review the output above, then run one of:
--   commit;
--   rollback;

-- ROLLBACK AFTER COMMIT (restores the old state):
--   alter table fantrax.<table> disable row level security;   -- for each table
--   grant select on fantrax.cap_hit_overrides, fantrax.contract_decisions, fantrax.draft_picks,
--                   fantrax.savant_metrics, fantrax.fv_position_multipliers,
--                   fantrax.fv_to_fpts_hitter, fantrax.fv_to_fpts_pitcher, fantrax.level_reach_discount
--     to anon;

-- ─────────────────────────────────────────────────────────────────────────────────────────────
-- SEPARATE, BIGGER ISSUE (NOT part of this fix; needs a decision + a site change): these policies
-- let ANYONE holding the anon key WRITE, because `anon_*` policies with `true` are OR'd with the
-- newer `owner_*` ones. The site signs in as the owner (S.token) for writes, so the anon writes
-- may now be unnecessary, but I have not tested that.
--   public.teams                   anon_write_teams            UPDATE  true
--   public.team_cap_settings       anon_insert/update_cap_settings   true
--   public.contract_decisions      anon_insert_cd / anon_update_cd   true
--   fantrax.owner_profiles         anon_all_owner_profiles     ALL     true   (anon has write grants)
--   fantrax.trade_feedback         anon_insert_trade_feedback  INSERT  true   (probably intended)
-- Dropping them would break signed-out writes in index.html. Test with the site signed in first.

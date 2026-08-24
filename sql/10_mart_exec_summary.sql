-- =============================================================================
-- 10_mart_exec_summary.sql
-- Purpose : The handful of numbers that go at the top of the page.
-- Grain   : one row.
-- Notes   : Figures derived from a stated assumption are kept separate from
--           figures measured directly, and named so the difference is visible.
--           Anything prefixed est_ rests on an assumed boarding rate; anything
--           else is computed from the published data alone.
-- =============================================================================

DROP TABLE IF EXISTS mart_exec_summary;

CREATE TABLE mart_exec_summary AS
WITH scope AS (
    SELECT
        COUNT(*)                                            AS incidents,
        SUM(is_service_affecting)                           AS service_affecting,
        COUNT(DISTINCT route_number)                        AS routes,
        COUNT(DISTINCT delay_date)                          AS days,
        MIN(delay_date)                                     AS first_date,
        MAX(delay_date)                                     AS last_date,
        SUM(min_delay)                                      AS delay_minutes,
        SUM(min_gap)                                        AS gap_minutes,
        SUM(rider_impact_index)                             AS rider_impact_index,
        SUM(est_excess_rider_minutes)                       AS est_excess_rider_minutes,
        AVG(CASE WHEN is_service_affecting = 1 THEN min_gap END)   AS avg_gap_min,
        AVG(CASE WHEN is_service_affecting = 1 THEN min_delay END) AS avg_delay_min,
        AVG(CASE WHEN is_service_affecting = 1
                 THEN excess_wait_per_rider_min END)        AS avg_excess_wait_min,
        SUM(CASE WHEN severity = 'severe_gap' THEN 1 ELSE 0 END)   AS severe_gaps
    FROM fct_delay_incident
    WHERE is_analysable = 1
),
concentration AS (
    -- Share of all rider impact carried by the worst ten routes.
    SELECT
        (SELECT SUM(rider_impact_index) FROM (
            SELECT rider_impact_index FROM mart_route_scorecard
            ORDER BY rider_impact_index DESC LIMIT 10)) AS top10_impact,
        (SELECT COUNT(*) FROM mart_route_scorecard)     AS n_routes
),
tractable AS (
    SELECT
        SUM(CASE WHEN tractability = 'addressable'
                 THEN rider_impact_index ELSE 0 END)        AS addressable_impact,
        SUM(CASE WHEN tractability = 'largely_irreducible'
                 THEN rider_impact_index ELSE 0 END)        AS irreducible_impact,
        SUM(rider_impact_index)                             AS all_impact
    FROM mart_cause_category
),
worst_cause AS (
    SELECT cause_category, pct_of_rider_impact, accountable_for
    FROM mart_cause_category ORDER BY rider_impact_index DESC LIMIT 1
),
worst_route AS (
    SELECT route_label, rider_impact_index, pct_of_total_impact, rank_by_incident_count
    FROM mart_route_scorecard ORDER BY rider_impact_index DESC LIMIT 1
),
winter AS (
    SELECT
        AVG(CASE WHEN is_winter = 1 THEN impact_per_day END)  AS winter_impact_per_day,
        AVG(CASE WHEN is_winter = 0 THEN impact_per_day END)  AS other_impact_per_day
    FROM mart_monthly
),
ranking_disagreement AS (
    -- How differently does the network look when ranked by rider impact rather
    -- than by incident count? Measured as the number of routes that move more
    -- than five places between the two rankings.
    SELECT
        SUM(CASE WHEN ABS(rank_shift) > 5 THEN 1 ELSE 0 END) AS routes_moving_5plus,
        MAX(ABS(rank_shift))                                 AS largest_rank_shift
    FROM mart_route_scorecard
)

SELECT
    -- ---- scope ---------------------------------------------------------------
    (SELECT data_mode FROM meta_build)                      AS data_mode,
    s.incidents,
    s.service_affecting,
    ROUND(s.service_affecting * 100.0 / s.incidents, 1)     AS pct_service_affecting,
    s.routes,
    s.days,
    s.first_date,
    s.last_date,

    -- ---- measured directly ---------------------------------------------------
    s.delay_minutes,
    s.gap_minutes,
    ROUND(s.avg_delay_min, 1)                               AS avg_delay_min,
    ROUND(s.avg_gap_min, 1)                                 AS avg_gap_min,
    ROUND(s.avg_excess_wait_min, 2)                         AS avg_excess_wait_min,
    s.severe_gaps,
    ROUND(s.rider_impact_index, 0)                          AS rider_impact_index,

    -- ---- rests on the assumed boarding rate ----------------------------------
    ROUND(s.est_excess_rider_minutes / 60.0, 0)             AS est_excess_rider_hours,
    ROUND(s.est_excess_rider_minutes / 60.0 / NULLIF(s.days, 0) * 365.0, 0)
                                                            AS est_excess_rider_hours_annualised,

    -- ---- concentration -------------------------------------------------------
    ROUND(c.top10_impact * 100.0 / NULLIF(s.rider_impact_index, 0), 1)
                                                            AS top10_route_share_pct,
    c.n_routes,

    -- ---- tractability --------------------------------------------------------
    ROUND(t.addressable_impact * 100.0 / NULLIF(t.all_impact, 0), 1)
                                                            AS addressable_impact_pct,
    ROUND(t.irreducible_impact * 100.0 / NULLIF(t.all_impact, 0), 1)
                                                            AS irreducible_impact_pct,

    -- ---- headlines -----------------------------------------------------------
    (SELECT cause_category FROM worst_cause)                AS top_cause_category,
    (SELECT pct_of_rider_impact FROM worst_cause)           AS top_cause_impact_pct,
    (SELECT accountable_for FROM worst_cause)               AS top_cause_owner,
    (SELECT route_label FROM worst_route)                   AS worst_route,
    (SELECT pct_of_total_impact FROM worst_route)           AS worst_route_impact_pct,
    (SELECT rank_by_incident_count FROM worst_route)        AS worst_route_count_rank,

    ROUND(w.winter_impact_per_day, 0)                       AS winter_impact_per_day,
    ROUND(w.other_impact_per_day, 0)                        AS other_impact_per_day,
    ROUND(
        (w.winter_impact_per_day - w.other_impact_per_day) * 100.0
        / NULLIF(w.other_impact_per_day, 0)
    , 1)                                                    AS winter_uplift_pct,

    rd.routes_moving_5plus,
    rd.largest_rank_shift
FROM scope s
CROSS JOIN concentration c
CROSS JOIN tractable t
CROSS JOIN winter w
CROSS JOIN ranking_disagreement rd;

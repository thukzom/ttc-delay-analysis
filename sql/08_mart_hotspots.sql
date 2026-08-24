-- =============================================================================
-- 08_mart_hotspots.sql
-- Purpose : Where on the network delays concentrate, and how concentrated the
--           whole problem is.
-- Grain   : mart_location_hotspots = one row per location;
--           mart_route_pareto      = one row per route, cumulative.
-- Notes   : Location is free text entered by staff and is the messiest field in
--           the dataset - the same corner appears several ways. Values are
--           normalised lightly here and the residual messiness is reported in
--           mart_data_quality rather than papered over.
-- =============================================================================

DROP TABLE IF EXISTS mart_location_hotspots;

CREATE TABLE mart_location_hotspots AS
WITH cleaned AS (
    SELECT
        -- Light normalisation only: collapse whitespace and strip the trailing
        -- "STATION" qualifier so "WARDEN STATION" and "WARDEN" group together.
        TRIM(
            REPLACE(REPLACE(REPLACE(UPPER(location), '  ', ' '), ' STN', ''),
                    ' STATION', '')
        )                                                   AS location_key,
        location                                            AS location_raw,
        route_number,
        min_gap,
        rider_impact_index,
        est_excess_rider_minutes,
        is_service_affecting,
        cause_category,
        severity
    FROM fct_delay_incident
    WHERE is_analysable = 1 AND TRIM(location) <> ''
),
agg AS (
    SELECT
        location_key,
        COUNT(*)                                            AS incidents,
        SUM(is_service_affecting)                           AS service_affecting,
        COUNT(DISTINCT route_number)                        AS routes_affected,
        ROUND(AVG(CASE WHEN is_service_affecting = 1 THEN min_gap END), 1)
                                                            AS avg_gap_min,
        MAX(min_gap)                                        AS worst_gap_min,
        SUM(rider_impact_index)                             AS rider_impact_index,
        SUM(est_excess_rider_minutes)                       AS est_excess_rider_minutes,
        SUM(CASE WHEN severity = 'severe_gap' THEN 1 ELSE 0 END) AS severe_gaps
    FROM cleaned
    GROUP BY location_key
),
dominant AS (
    SELECT location_key, cause_category, impact,
           ROW_NUMBER() OVER (PARTITION BY location_key ORDER BY impact DESC) AS rn
    FROM (
        SELECT location_key, cause_category, SUM(rider_impact_index) AS impact
        FROM cleaned GROUP BY location_key, cause_category
    )
)
SELECT
    a.location_key                                          AS location,
    a.incidents,
    a.service_affecting,
    a.routes_affected,
    a.avg_gap_min,
    a.worst_gap_min,
    a.severe_gaps,
    ROUND(a.rider_impact_index, 0)                          AS rider_impact_index,
    ROUND(a.est_excess_rider_minutes / 60.0, 0)             AS est_excess_rider_hours,
    d.cause_category                                        AS dominant_cause_category,
    ROUND(
        a.rider_impact_index * 100.0
        / NULLIF((SELECT SUM(rider_impact_index) FROM agg), 0)
    , 2)                                                    AS pct_of_total_impact,
    RANK() OVER (ORDER BY a.rider_impact_index DESC)        AS rank_by_impact
FROM agg a
LEFT JOIN dominant d ON d.location_key = a.location_key AND d.rn = 1;


DROP TABLE IF EXISTS mart_route_pareto;

CREATE TABLE mart_route_pareto AS
-- How concentrated is the problem? If a small number of routes carry most of
-- the rider impact, the recommendation is a short list rather than a strategy.
WITH ranked AS (
    SELECT
        route_number,
        route_label,
        rider_impact_index,
        incidents,
        ROW_NUMBER() OVER (ORDER BY rider_impact_index DESC) AS impact_rank
    FROM mart_route_scorecard
),
total AS (
    SELECT SUM(rider_impact_index) AS all_impact,
           SUM(incidents)          AS all_incidents,
           COUNT(*)                AS n_routes
    FROM ranked
)
SELECT
    r.impact_rank,
    r.route_number,
    r.route_label,
    r.incidents,
    ROUND(r.rider_impact_index, 0)                          AS rider_impact_index,
    ROUND(r.rider_impact_index * 100.0 / t.all_impact, 2)   AS pct_of_impact,
    ROUND(
        SUM(r.rider_impact_index) OVER (
            ORDER BY r.impact_rank ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) * 100.0 / t.all_impact
    , 2)                                                    AS cumulative_pct_impact,
    ROUND(r.impact_rank * 100.0 / t.n_routes, 2)            AS cumulative_pct_routes
FROM ranked r
CROSS JOIN total t
ORDER BY r.impact_rank;

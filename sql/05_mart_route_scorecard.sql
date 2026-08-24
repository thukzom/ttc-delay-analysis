-- =============================================================================
-- 05_mart_route_scorecard.sql
-- Purpose : Rank every route by how much waiting it actually inflicts, and
--           show how differently that reads from ranking by incident count.
-- Grain   : one row per route.
-- Notes   : The two rankings are both computed and both kept, because the gap
--           between them is the finding. A route with many short incidents can
--           look terrible on a count and be barely noticeable to a rider; a
--           route with few enormous gaps is the opposite.
-- =============================================================================

DROP TABLE IF EXISTS mart_route_scorecard;

CREATE TABLE mart_route_scorecard AS
WITH base AS (
    SELECT
        route_number,
        route_label,
        service_type,
        COUNT(*)                                        AS incidents,
        SUM(is_service_affecting)                       AS service_affecting,
        SUM(min_delay)                                  AS delay_minutes_total,
        SUM(min_gap)                                    AS gap_minutes_total,
        AVG(CASE WHEN is_service_affecting = 1 THEN min_delay END)
                                                        AS avg_delay_min,
        AVG(CASE WHEN is_service_affecting = 1 THEN min_gap END)
                                                        AS avg_gap_min,
        MAX(min_gap)                                    AS worst_gap_min,
        AVG(headway_min)                                AS avg_headway_min,
        SUM(rider_impact_index)                         AS rider_impact_index,
        SUM(est_excess_rider_minutes)                   AS est_excess_rider_minutes,
        AVG(CASE WHEN is_service_affecting = 1
                 THEN excess_wait_per_rider_min END)    AS avg_excess_wait_min,
        SUM(CASE WHEN severity = 'severe_gap' THEN 1 ELSE 0 END)
                                                        AS severe_gaps,
        SUM(is_peak)                                    AS peak_incidents,
        SUM(is_winter)                                  AS winter_incidents,
        COUNT(DISTINCT delay_date)                      AS days_with_incidents,
        MIN(delay_date)                                 AS first_seen,
        MAX(delay_date)                                 AS last_seen
    FROM fct_delay_incident
    WHERE is_analysable = 1
    GROUP BY route_number, route_label, service_type
),

dominant AS (
    -- The cause category responsible for the most rider impact on each route.
    -- Weighted by impact rather than by count, because the question is "what
    -- is hurting riders here", not "what gets logged most often".
    SELECT route_number, cause_category, impact,
           ROW_NUMBER() OVER (PARTITION BY route_number ORDER BY impact DESC) AS rn
    FROM (
        SELECT route_number, cause_category, SUM(rider_impact_index) AS impact
        FROM fct_delay_incident
        WHERE is_analysable = 1
        GROUP BY route_number, cause_category
    )
),

headway_quality AS (
    SELECT
        route_number,
        SUM(CASE WHEN headway_source = 'default_assumed' THEN 1 ELSE 0 END) AS assumed_bands,
        COUNT(*) AS bands
    FROM int_route_headway
    GROUP BY route_number
)

SELECT
    b.route_number,
    b.route_label,
    b.service_type,

    b.incidents,
    b.service_affecting,
    b.days_with_incidents,
    ROUND(b.incidents * 1.0 / NULLIF(b.days_with_incidents, 0), 2)
                                                        AS incidents_per_active_day,

    b.delay_minutes_total,
    b.gap_minutes_total,
    ROUND(b.avg_delay_min, 1)                           AS avg_delay_min,
    ROUND(b.avg_gap_min, 1)                             AS avg_gap_min,
    b.worst_gap_min,
    ROUND(b.avg_headway_min, 1)                         AS avg_headway_min,
    ROUND(b.avg_excess_wait_min, 2)                     AS avg_excess_wait_min,

    ROUND(b.rider_impact_index, 0)                      AS rider_impact_index,
    ROUND(b.est_excess_rider_minutes / 60.0, 0)         AS est_excess_rider_hours,

    b.severe_gaps,
    ROUND(b.severe_gaps * 100.0 / NULLIF(b.service_affecting, 0), 1)
                                                        AS pct_severe,
    ROUND(b.peak_incidents * 100.0 / NULLIF(b.incidents, 0), 1)
                                                        AS pct_peak,
    ROUND(b.winter_incidents * 100.0 / NULLIF(b.incidents, 0), 1)
                                                        AS pct_winter,

    d.cause_category                                    AS dominant_cause_category,

    -- Confidence marker: routes whose headway had to be assumed rather than
    -- estimated carry a weaker impact figure, and the site says so.
    CASE WHEN hq.assumed_bands = 0 THEN 'estimated'
         WHEN hq.assumed_bands < hq.bands THEN 'partly_assumed'
         ELSE 'assumed' END                             AS headway_confidence,

    -- The two competing rankings.
    RANK() OVER (ORDER BY b.rider_impact_index DESC)    AS rank_by_rider_impact,
    RANK() OVER (ORDER BY b.incidents DESC)             AS rank_by_incident_count,
    RANK() OVER (ORDER BY b.delay_minutes_total DESC)   AS rank_by_delay_minutes,

    -- Positive means the route looks WORSE for riders than a naive incident
    -- count suggests; negative means it looks better.
    (RANK() OVER (ORDER BY b.incidents DESC))
      - (RANK() OVER (ORDER BY b.rider_impact_index DESC))
                                                        AS rank_shift,

    ROUND(
        b.rider_impact_index * 100.0
        / NULLIF((SELECT SUM(rider_impact_index) FROM base), 0)
    , 2)                                                AS pct_of_total_impact
FROM base b
LEFT JOIN dominant d ON d.route_number = b.route_number AND d.rn = 1
LEFT JOIN headway_quality hq ON hq.route_number = b.route_number;

CREATE UNIQUE INDEX idx_scorecard_pk ON mart_route_scorecard (route_number);

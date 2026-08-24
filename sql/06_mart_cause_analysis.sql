-- =============================================================================
-- 06_mart_cause_analysis.sql
-- Purpose : Which causes of delay actually cost riders time, and which of those
--           anything can realistically be done about.
-- Grain   : mart_cause_category = one row per category;
--           mart_cause_detail   = one row per distinct published cause.
-- Notes   : Frequency and impact are reported side by side on purpose. The most
--           frequently logged cause is rarely the most costly one, and a plan
--           built on frequency alone will spend effort in the wrong place.
-- =============================================================================

DROP TABLE IF EXISTS mart_cause_category;

CREATE TABLE mart_cause_category AS
WITH totals AS (
    SELECT
        SUM(rider_impact_index) AS all_impact,
        COUNT(*)                AS all_incidents
    FROM fct_delay_incident
    WHERE is_analysable = 1
),
base AS (
    SELECT
        cause_category,
        COUNT(*)                                            AS incidents,
        SUM(is_service_affecting)                           AS service_affecting,
        SUM(min_delay)                                      AS delay_minutes,
        SUM(min_gap)                                        AS gap_minutes,
        AVG(CASE WHEN is_service_affecting = 1 THEN min_gap END) AS avg_gap_min,
        SUM(rider_impact_index)                             AS rider_impact_index,
        SUM(est_excess_rider_minutes)                       AS est_excess_rider_minutes,
        SUM(CASE WHEN severity = 'severe_gap' THEN 1 ELSE 0 END) AS severe_gaps,
        SUM(is_winter)                                      AS winter_incidents,
        SUM(is_peak)                                        AS peak_incidents,
        COUNT(DISTINCT route_number)                        AS routes_affected
    FROM fct_delay_incident
    WHERE is_analysable = 1
    GROUP BY cause_category
)
SELECT
    b.cause_category,

    -- Who would own reducing this, and whether it is realistically reducible.
    -- Stated in the model rather than left to the reader, because a cause
    -- breakdown with no owner attached is not actionable.
    CASE b.cause_category
        WHEN 'mechanical' THEN 'TTC fleet maintenance and vehicle renewal'
        WHEN 'operator'   THEN 'TTC scheduling, staffing and crew availability'
        WHEN 'passenger'  THEN 'Onboard incidents - largely irreducible'
        WHEN 'security'   THEN 'TTC special constables and police response'
        WHEN 'collision'  THEN 'Road safety - shared with the City'
        WHEN 'external'   THEN 'Weather, traffic and events - outside TTC control'
        ELSE                   'Unclassified'
    END                                                     AS accountable_for,

    CASE b.cause_category
        WHEN 'mechanical' THEN 'addressable'
        WHEN 'operator'   THEN 'addressable'
        WHEN 'collision'  THEN 'partly_addressable'
        WHEN 'security'   THEN 'partly_addressable'
        WHEN 'passenger'  THEN 'largely_irreducible'
        WHEN 'external'   THEN 'largely_irreducible'
        ELSE                   'unknown'
    END                                                     AS tractability,

    b.incidents,
    b.service_affecting,
    b.routes_affected,
    ROUND(b.incidents * 100.0 / t.all_incidents, 2)         AS pct_of_incidents,

    b.delay_minutes,
    b.gap_minutes,
    ROUND(b.avg_gap_min, 1)                                 AS avg_gap_min,
    b.severe_gaps,

    ROUND(b.rider_impact_index, 0)                          AS rider_impact_index,
    ROUND(b.rider_impact_index * 100.0 / t.all_impact, 2)   AS pct_of_rider_impact,
    ROUND(b.est_excess_rider_minutes / 60.0, 0)             AS est_excess_rider_hours,

    -- The headline comparison: does this cause hurt riders more or less than
    -- its share of the incident log suggests?
    ROUND(
        (b.rider_impact_index * 100.0 / t.all_impact)
        - (b.incidents * 100.0 / t.all_incidents)
    , 2)                                                    AS impact_vs_frequency_gap,

    ROUND(b.winter_incidents * 100.0 / NULLIF(b.incidents, 0), 1) AS pct_winter,
    ROUND(b.peak_incidents * 100.0 / NULLIF(b.incidents, 0), 1)   AS pct_peak,

    RANK() OVER (ORDER BY b.rider_impact_index DESC)        AS rank_by_impact,
    RANK() OVER (ORDER BY b.incidents DESC)                 AS rank_by_frequency
FROM base b
CROSS JOIN totals t;


DROP TABLE IF EXISTS mart_cause_detail;

CREATE TABLE mart_cause_detail AS
WITH totals AS (
    SELECT SUM(rider_impact_index) AS all_impact FROM fct_delay_incident
    WHERE is_analysable = 1
)
SELECT
    f.cause_raw,
    MAX(f.cause_code)                                       AS cause_code,
    MAX(f.cause_description)                                AS cause_description,
    MAX(f.cause_category)                                   AS cause_category,
    MAX(c.cause_source)                                     AS cause_source,
    MAX(f.schema_generation)                                AS schema_generation,

    COUNT(*)                                                AS incidents,
    SUM(f.is_service_affecting)                             AS service_affecting,
    ROUND(AVG(CASE WHEN f.is_service_affecting = 1 THEN f.min_gap END), 1)
                                                            AS avg_gap_min,
    ROUND(AVG(CASE WHEN f.is_service_affecting = 1 THEN f.min_delay END), 1)
                                                            AS avg_delay_min,
    MAX(f.min_gap)                                          AS worst_gap_min,
    ROUND(SUM(f.rider_impact_index), 0)                     AS rider_impact_index,
    ROUND(SUM(f.rider_impact_index) * 100.0 / t.all_impact, 2)
                                                            AS pct_of_rider_impact,
    ROUND(SUM(f.est_excess_rider_minutes) / 60.0, 0)        AS est_excess_rider_hours,

    -- Average harm per occurrence. A cause can be rare and still deserve
    -- attention if every occurrence is catastrophic.
    ROUND(
        SUM(f.rider_impact_index) / NULLIF(SUM(f.is_service_affecting), 0)
    , 1)                                                    AS impact_per_incident,

    RANK() OVER (ORDER BY SUM(f.rider_impact_index) DESC)   AS rank_by_impact
FROM fct_delay_incident f
LEFT JOIN dim_cause c ON c.cause_raw = f.cause_raw
CROSS JOIN totals t
WHERE f.is_analysable = 1
GROUP BY f.cause_raw, t.all_impact;

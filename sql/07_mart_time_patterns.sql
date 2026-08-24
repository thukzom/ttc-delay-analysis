-- =============================================================================
-- 07_mart_time_patterns.sql
-- Purpose : When delays happen, and - separately - when they hurt most.
-- Grain   : mart_hour_day = one row per hour x day-of-week (the heatmap grid);
--           mart_time_band = one row per time band;
--           mart_monthly   = one row per calendar month.
-- Notes   : Incident counts follow service levels: more buses running means
--           more logged incidents, which says nothing about reliability. Every
--           measure here is therefore reported both raw and normalised per
--           incident, so a busy hour is not mistaken for a bad one.
-- =============================================================================

DROP TABLE IF EXISTS mart_hour_day;

CREATE TABLE mart_hour_day AS
WITH grid AS (
    SELECT
        hour,
        day_name,
        CASE day_name
            WHEN 'Monday' THEN 1 WHEN 'Tuesday' THEN 2 WHEN 'Wednesday' THEN 3
            WHEN 'Thursday' THEN 4 WHEN 'Friday' THEN 5 WHEN 'Saturday' THEN 6
            WHEN 'Sunday' THEN 7 ELSE 8
        END                                                 AS day_order,
        COUNT(*)                                            AS incidents,
        SUM(is_service_affecting)                           AS service_affecting,
        SUM(min_gap)                                        AS gap_minutes,
        AVG(CASE WHEN is_service_affecting = 1 THEN min_gap END) AS avg_gap_min,
        SUM(rider_impact_index)                             AS rider_impact_index,
        SUM(CASE WHEN severity = 'severe_gap' THEN 1 ELSE 0 END) AS severe_gaps
    FROM fct_delay_incident
    WHERE is_analysable = 1 AND hour IS NOT NULL
    GROUP BY hour, day_name
)
SELECT
    hour,
    day_name,
    day_order,
    incidents,
    service_affecting,
    gap_minutes,
    ROUND(avg_gap_min, 1)                                   AS avg_gap_min,
    ROUND(rider_impact_index, 0)                            AS rider_impact_index,
    severe_gaps,

    -- Harm per logged incident. This is the cell that answers "is this hour
    -- genuinely bad, or just busy?"
    ROUND(rider_impact_index / NULLIF(service_affecting, 0), 1)
                                                            AS impact_per_incident,
    ROUND(severe_gaps * 100.0 / NULLIF(service_affecting, 0), 1)
                                                            AS pct_severe,
    ROUND(
        rider_impact_index * 100.0
        / NULLIF((SELECT SUM(rider_impact_index) FROM grid), 0)
    , 3)                                                    AS pct_of_total_impact
FROM grid
ORDER BY day_order, hour;


DROP TABLE IF EXISTS mart_time_band;

CREATE TABLE mart_time_band AS
SELECT
    time_band,
    CASE time_band
        WHEN 'early'   THEN 1 WHEN 'am_peak' THEN 2 WHEN 'midday' THEN 3
        WHEN 'pm_peak' THEN 4 WHEN 'evening' THEN 5 ELSE 6
    END                                                     AS band_order,
    CASE time_band
        WHEN 'early'   THEN 'Overnight and early (00:00-06:00)'
        WHEN 'am_peak' THEN 'Morning peak (06:00-10:00)'
        WHEN 'midday'  THEN 'Midday (10:00-15:00)'
        WHEN 'pm_peak' THEN 'Afternoon peak (15:00-19:00)'
        WHEN 'evening' THEN 'Evening (19:00-24:00)'
        ELSE                'Unknown'
    END                                                     AS band_label,
    COUNT(*)                                                AS incidents,
    SUM(is_service_affecting)                               AS service_affecting,
    ROUND(AVG(headway_min), 1)                              AS avg_headway_min,
    ROUND(AVG(CASE WHEN is_service_affecting = 1 THEN min_gap END), 1)
                                                            AS avg_gap_min,
    ROUND(AVG(CASE WHEN is_service_affecting = 1
                   THEN excess_wait_per_rider_min END), 2)  AS avg_excess_wait_min,
    ROUND(SUM(rider_impact_index), 0)                       AS rider_impact_index,
    ROUND(SUM(est_excess_rider_minutes) / 60.0, 0)          AS est_excess_rider_hours,
    ROUND(
        SUM(rider_impact_index) * 100.0
        / NULLIF((SELECT SUM(rider_impact_index) FROM fct_delay_incident
                  WHERE is_analysable = 1), 0)
    , 2)                                                    AS pct_of_total_impact
FROM fct_delay_incident
WHERE is_analysable = 1
GROUP BY time_band
ORDER BY band_order;


DROP TABLE IF EXISTS mart_monthly;

CREATE TABLE mart_monthly AS
SELECT
    year_month,
    MIN(year)                                               AS year,
    MIN(month)                                              AS month,
    MIN(CASE WHEN is_winter = 1 THEN 1 ELSE 0 END)          AS is_winter,
    COUNT(DISTINCT delay_date)                              AS days_observed,
    COUNT(*)                                                AS incidents,
    SUM(is_service_affecting)                               AS service_affecting,
    ROUND(COUNT(*) * 1.0 / COUNT(DISTINCT delay_date), 1)   AS incidents_per_day,
    ROUND(AVG(CASE WHEN is_service_affecting = 1 THEN min_gap END), 1)
                                                            AS avg_gap_min,
    ROUND(SUM(rider_impact_index), 0)                       AS rider_impact_index,
    ROUND(SUM(rider_impact_index) / COUNT(DISTINCT delay_date), 0)
                                                            AS impact_per_day,
    SUM(CASE WHEN cause_category = 'external' THEN 1 ELSE 0 END)
                                                            AS external_incidents,
    ROUND(
        SUM(CASE WHEN cause_category = 'external' THEN 1 ELSE 0 END) * 100.0
        / COUNT(*)
    , 1)                                                    AS pct_external,
    ROUND(
        SUM(CASE WHEN cause_category = 'mechanical' THEN 1 ELSE 0 END) * 100.0
        / COUNT(*)
    , 1)                                                    AS pct_mechanical
FROM fct_delay_incident
WHERE is_analysable = 1
GROUP BY year_month
ORDER BY year_month;

-- =============================================================================
-- 01_staging.sql
-- Purpose : One clean, typed, flagged row per logged delay incident.
-- Grain   : one row per incident.
-- Notes   : Nothing is deleted. Records that fail a plausibility test are
--           flagged so that data quality remains a reported metric rather than
--           an invisible filter. Every headline mart reads only rows where
--           is_analysable = 1, and the data-quality mart reports what that
--           excluded.
-- =============================================================================

DROP TABLE IF EXISTS stg_incidents;

CREATE TABLE stg_incidents AS
SELECT
    ROW_NUMBER() OVER (ORDER BY delay_date, route_number, hour) AS incident_id,

    delay_date,
    CAST(STRFTIME('%Y', delay_date) AS INTEGER)          AS year,
    CAST(STRFTIME('%m', delay_date) AS INTEGER)          AS month,
    STRFTIME('%Y-%m', delay_date)                        AS year_month,
    day_name,
    CASE WHEN day_name IN ('Saturday', 'Sunday') THEN 1 ELSE 0 END AS is_weekend,

    -- Meteorological winter. The season this whole project started with.
    CASE WHEN CAST(STRFTIME('%m', delay_date) AS INTEGER) IN (12, 1, 2)
         THEN 1 ELSE 0 END                               AS is_winter,

    hour,
    time_band,
    CASE WHEN time_band IN ('am_peak', 'pm_peak') THEN 1 ELSE 0 END AS is_peak,

    route_number,
    NULLIF(route_name, '')                               AS route_name,
    location,
    direction,
    vehicle,

    cause_raw,
    NULLIF(cause_code, '')                               AS cause_code,
    cause_description,
    cause_category,

    min_delay,
    min_gap,

    -- Winsorised gap. Rider impact is quadratic in this quantity, so the raw
    -- value cannot be used directly: a hundred sentinel entries would otherwise
    -- outweigh every real incident in the dataset combined. See config.py.
    MIN(min_gap, {{GAP_CAP_MINUTES}})                    AS min_gap_capped,
    CASE WHEN min_gap > {{GAP_CAP_MINUTES}} THEN 1 ELSE 0 END AS is_gap_capped,

    -- The difference between the two published measures is the quantity this
    -- project is built on. Min Delay is how late the VEHICLE was; Min Gap is
    -- how long the hole in service was. A rider at a stop experiences the gap.
    CASE WHEN min_gap > 0 AND min_delay > 0 AND min_gap >= min_delay
         THEN min_gap - min_delay END                    AS implied_headway_min,

    schema_generation,
    source_file,

    -- ---- quality flags ------------------------------------------------------
    is_implausible,
    CASE WHEN hour IS NULL THEN 1 ELSE 0 END             AS dq_missing_hour,
    CASE WHEN day_name NOT IN
        ('Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday')
         THEN 1 ELSE 0 END                               AS dq_bad_day_name,
    CASE WHEN cause_category = 'other' THEN 1 ELSE 0 END AS dq_cause_unmapped,
    CASE WHEN min_gap > 0 AND min_gap < min_delay THEN 1 ELSE 0 END
                                                         AS dq_gap_below_delay,

    -- Placeholder values that appear in the published data. Not measurements.
    CASE WHEN min_gap IN ({{GAP_SENTINELS}}) THEN 1 ELSE 0 END
                                                         AS dq_gap_sentinel,

    -- A record is analysable if it is internally consistent. Roughly a third of
    -- logged records have a zero delay and zero gap: these are real log entries
    -- for events that did not hold a bus up, and they are kept for cause
    -- analysis but carry no rider impact.
    CASE WHEN is_implausible = 0 AND hour IS NOT NULL THEN 1 ELSE 0 END
                                                         AS is_analysable,

    CASE WHEN min_gap >= {{MIN_GAP_FOR_IMPACT}} AND is_implausible = 0
         THEN 1 ELSE 0 END                               AS is_service_affecting
FROM raw_incidents;

CREATE INDEX idx_stg_route  ON stg_incidents (route_number, time_band);
CREATE INDEX idx_stg_date   ON stg_incidents (delay_date);
CREATE INDEX idx_stg_cause  ON stg_incidents (cause_category);

-- =============================================================================
-- 09_mart_data_quality.sql
-- Purpose : Report the trustworthiness of the input as a metric, not a footnote.
-- Grain   : mart_dq_by_file = one row per source file; mart_dq_summary = one row.
-- Notes   : The harmonisation between two schema generations is the highest-risk
--           step in this pipeline, so it is measured here explicitly: how many
--           rows came from each generation, how many causes failed to map, and
--           whether any field is systematically emptier in one than the other.
-- =============================================================================

DROP TABLE IF EXISTS mart_dq_by_file;

CREATE TABLE mart_dq_by_file AS
SELECT
    source_file,
    MAX(schema_generation)                                  AS schema_generation,
    COUNT(*)                                                AS rows_loaded,
    MIN(delay_date)                                         AS first_date,
    MAX(delay_date)                                         AS last_date,
    COUNT(DISTINCT delay_date)                              AS distinct_days,
    COUNT(DISTINCT year_month)                              AS months_covered,
    COUNT(DISTINCT route_number)                            AS distinct_routes,

    SUM(dq_missing_hour)                                    AS missing_hour,
    SUM(dq_bad_day_name)                                    AS bad_day_name,
    SUM(dq_cause_unmapped)                                  AS cause_unmapped,
    SUM(dq_gap_below_delay)                                 AS gap_below_delay,
    SUM(dq_gap_sentinel)                                    AS gap_sentinel_values,
    SUM(is_gap_capped)                                      AS gaps_winsorised,
    SUM(is_implausible)                                     AS implausible_rows,
    SUM(CASE WHEN direction = '' THEN 1 ELSE 0 END)         AS missing_direction,
    SUM(CASE WHEN vehicle = 0 THEN 1 ELSE 0 END)            AS missing_vehicle,
    SUM(CASE WHEN TRIM(location) = '' THEN 1 ELSE 0 END)    AS missing_location,

    ROUND(SUM(is_analysable) * 100.0 / COUNT(*), 2)         AS pct_analysable,
    ROUND(SUM(dq_cause_unmapped) * 100.0 / COUNT(*), 2)     AS pct_cause_unmapped,
    ROUND(SUM(is_service_affecting) * 100.0 / COUNT(*), 2)  AS pct_service_affecting
FROM stg_incidents
GROUP BY source_file
ORDER BY first_date;


DROP TABLE IF EXISTS mart_dq_summary;

CREATE TABLE mart_dq_summary AS
SELECT
    (SELECT data_mode FROM meta_build)                          AS data_mode,
    (SELECT built_at  FROM meta_build)                          AS built_at,
    (SELECT provenance_present FROM meta_build)                 AS provenance_present,
    (SELECT COUNT(*) FROM stg_incidents)                        AS rows_loaded,
    (SELECT COUNT(*) FROM mart_dq_by_file)                      AS source_files,
    (SELECT COUNT(DISTINCT schema_generation) FROM stg_incidents) AS schema_generations,
    (SELECT COUNT(*) FROM stg_incidents WHERE schema_generation = 'legacy')  AS rows_legacy_schema,
    (SELECT COUNT(*) FROM stg_incidents WHERE schema_generation = 'current') AS rows_current_schema,
    (SELECT MIN(delay_date) FROM stg_incidents)                 AS first_date,
    (SELECT MAX(delay_date) FROM stg_incidents)                 AS last_date,
    (SELECT COUNT(*) FROM dim_route)                            AS routes,
    (SELECT COUNT(*) FROM dim_cause)                            AS distinct_causes,
    (SELECT COUNT(*) FROM raw_delay_codes)                      AS published_codes,

    (SELECT SUM(is_analysable) FROM stg_incidents)              AS analysable_rows,
    ROUND(
        (SELECT SUM(is_analysable) FROM stg_incidents) * 100.0
        / (SELECT COUNT(*) FROM stg_incidents)
    , 2)                                                        AS pct_analysable,
    ROUND(
        (SELECT SUM(dq_cause_unmapped) FROM stg_incidents) * 100.0
        / (SELECT COUNT(*) FROM stg_incidents)
    , 2)                                                        AS pct_cause_unmapped,
    ROUND(
        (SELECT SUM(is_implausible) FROM stg_incidents) * 100.0
        / (SELECT COUNT(*) FROM stg_incidents)
    , 3)                                                        AS pct_implausible,
    ROUND(
        (SELECT SUM(is_service_affecting) FROM stg_incidents) * 100.0
        / (SELECT COUNT(*) FROM stg_incidents)
    , 2)                                                        AS pct_service_affecting,

    (SELECT SUM(dq_gap_sentinel) FROM stg_incidents)            AS gap_sentinel_values,
    (SELECT SUM(is_gap_capped) FROM stg_incidents)              AS gaps_winsorised,
    ROUND(
        (SELECT SUM(is_gap_capped) FROM stg_incidents) * 100.0
        / (SELECT COUNT(*) FROM stg_incidents)
    , 3)                                                        AS pct_gaps_winsorised,

    -- How much rider impact the winsorising removed. On the first build of this
    -- project, 0.05% of rows carried 57% of total impact because of sentinel
    -- 999-minute gaps. This figure exists so that never goes unnoticed again.
    ROUND(
        (1.0 - (SELECT SUM(rider_impact_index) FROM fct_delay_incident
                 WHERE is_analysable = 1)
             / NULLIF((SELECT SUM(rider_impact_uncapped) FROM fct_delay_incident
                       WHERE is_analysable = 1), 0)) * 100.0
    , 2)                                                        AS pct_impact_removed_by_cap,

    -- Share of total impact carried by the single worst incident, and by the
    -- most extreme 0.1% of incidents. Both are concentration alarms.
    ROUND(
        (SELECT MAX(rider_impact_index) FROM fct_delay_incident
          WHERE is_analysable = 1) * 100.0
        / NULLIF((SELECT SUM(rider_impact_index) FROM fct_delay_incident
                  WHERE is_analysable = 1), 0)
    , 3)                                                        AS pct_impact_worst_incident,

    -- How much of the wait-time model rests on an estimated headway rather than
    -- an assumed default. The lower this is, the weaker the impact figures.
    ROUND(
        (SELECT COUNT(*) FROM int_route_headway
          WHERE headway_source <> 'default_assumed') * 100.0
        / NULLIF((SELECT COUNT(*) FROM int_route_headway), 0)
    , 2)                                                        AS pct_headway_estimated;

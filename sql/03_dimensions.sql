-- =============================================================================
-- 03_dimensions.sql
-- Purpose : Conformed dimensions.
-- Grain   : dim_route = one row per route; dim_cause = one row per distinct
--           cause value; dim_date = one row per calendar day observed.
-- =============================================================================

DROP TABLE IF EXISTS dim_route;

CREATE TABLE dim_route AS
WITH names AS (
    -- A route's name is recorded inconsistently across files and is absent
    -- entirely from the legacy schema. Take the most frequently seen non-null
    -- name per route so the site can label routes the way riders know them.
    SELECT route_number, route_name, COUNT(*) AS n,
           ROW_NUMBER() OVER (PARTITION BY route_number ORDER BY COUNT(*) DESC) AS rn
    FROM stg_incidents
    WHERE route_name IS NOT NULL AND route_name <> ''
    GROUP BY route_number, route_name
),
totals AS (
    SELECT
        route_number,
        COUNT(*)                                      AS incidents_total,
        SUM(is_service_affecting)                     AS incidents_service_affecting,
        MIN(delay_date)                               AS first_seen,
        MAX(delay_date)                               AS last_seen,
        COUNT(DISTINCT delay_date)                    AS active_days
    FROM stg_incidents
    GROUP BY route_number
)
SELECT
    t.route_number,
    COALESCE(n.route_name, '')                        AS route_name,
    CASE WHEN COALESCE(n.route_name, '') = ''
         THEN t.route_number
         ELSE t.route_number || ' ' || n.route_name
    END                                               AS route_label,

    -- TTC route numbering conventions, which carry real service meaning.
    CASE
        WHEN CAST(t.route_number AS INTEGER) BETWEEN 300 AND 399 THEN 'night'
        WHEN CAST(t.route_number AS INTEGER) BETWEEN 900 AND 999 THEN 'express'
        WHEN CAST(t.route_number AS INTEGER) BETWEEN 400 AND 499 THEN 'community'
        ELSE 'regular'
    END                                               AS service_type,

    t.incidents_total,
    t.incidents_service_affecting,
    t.first_seen,
    t.last_seen,
    t.active_days
FROM totals t
LEFT JOIN names n ON n.route_number = t.route_number AND n.rn = 1;

CREATE UNIQUE INDEX idx_dim_route_pk ON dim_route (route_number);


DROP TABLE IF EXISTS dim_cause;

CREATE TABLE dim_cause AS
SELECT
    cause_raw,
    MAX(cause_code)                                   AS cause_code,
    MAX(cause_description)                            AS cause_description,
    MAX(cause_category)                               AS cause_category,
    MAX(schema_generation)                            AS seen_in_schema,
    COUNT(*)                                          AS incidents,
    SUM(is_service_affecting)                         AS service_affecting,
    -- Whether this value came from the published code list or from the legacy
    -- free-text field. Kept because the two are not equally trustworthy.
    CASE WHEN MAX(cause_code) IS NOT NULL
         THEN 'published_code' ELSE 'legacy_free_text' END AS cause_source
FROM stg_incidents
GROUP BY cause_raw;


DROP TABLE IF EXISTS dim_date;

CREATE TABLE dim_date AS
SELECT
    delay_date                                        AS date_key,
    year,
    month,
    year_month,
    day_name,
    is_weekend,
    is_winter,
    CASE month
        WHEN 12 THEN 'Winter' WHEN 1 THEN 'Winter' WHEN 2 THEN 'Winter'
        WHEN 3 THEN 'Spring'  WHEN 4 THEN 'Spring' WHEN 5 THEN 'Spring'
        WHEN 6 THEN 'Summer'  WHEN 7 THEN 'Summer' WHEN 8 THEN 'Summer'
        ELSE 'Fall'
    END                                               AS season
FROM (SELECT DISTINCT delay_date, year, month, year_month, day_name,
                      is_weekend, is_winter
      FROM stg_incidents)
ORDER BY delay_date;

CREATE UNIQUE INDEX idx_dim_date_pk ON dim_date (date_key);

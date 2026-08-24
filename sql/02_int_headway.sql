-- =============================================================================
-- 02_int_headway.sql
-- Purpose : Recover each route's scheduled headway from the delay data itself.
-- Grain   : one row per route per time band.
--
-- Why this exists
-- ---------------
-- To say anything about rider wait time you need to know how often the bus is
-- SUPPOSED to come. The delay dataset does not publish that, and the obvious
-- source (GTFS schedules) is a separate feed that does not go back through the
-- historical years.
--
-- But the schedule is already implicit in the data. If buses run every H
-- minutes and one runs D minutes late, the gap it leaves behind is H + D.
-- So for any incident where both figures are recorded:
--
--       H  =  Min Gap  -  Min Delay
--
-- Individual records are noisy - bunching, short-turns and manual entry all
-- distort a single observation - so the route's headway is taken as the MEDIAN
-- of that difference across all its incidents in a time band. The median is
-- used rather than the mean because the tail is heavy and one cancellation
-- would drag an average badly.
--
-- Estimates built on too few observations, or that land outside a believable
-- range for a bus route, fall back to a documented default and are marked so
-- downstream marts can show which routes are estimated and which are assumed.
--
-- This estimator is validated against known headways on generated data by
-- `python -m src.validate_headway` before it is trusted on real data.
-- =============================================================================

DROP TABLE IF EXISTS int_route_headway;

CREATE TABLE int_route_headway AS
WITH
-- Every route and time band that actually appears in the data. Starting from
-- this rather than from the observations guarantees a headway row exists for
-- each one; building only from observations left any route-band whose
-- incidents all had a zero delay or gap with no headway at all, and those
-- incidents then had nothing to measure their wait against.
route_bands AS (
    SELECT DISTINCT route_number, time_band
    FROM stg_incidents
    WHERE is_analysable = 1
),

observations AS (
    SELECT
        route_number,
        time_band,
        implied_headway_min
    FROM stg_incidents
    WHERE is_analysable = 1
      AND implied_headway_min IS NOT NULL
      AND implied_headway_min BETWEEN 1 AND 120
),

-- SQLite has no MEDIAN(). Standard row-number construction: the middle row for
-- odd counts, the mean of the two middle rows for even counts.
ranked AS (
    SELECT
        route_number,
        time_band,
        implied_headway_min,
        ROW_NUMBER() OVER (
            PARTITION BY route_number, time_band ORDER BY implied_headway_min
        ) AS rn,
        COUNT(*) OVER (PARTITION BY route_number, time_band) AS n
    FROM observations
),

medians AS (
    SELECT
        route_number,
        time_band,
        AVG(implied_headway_min) AS median_headway,
        MAX(n)                   AS n_observations
    FROM ranked
    WHERE rn IN ((n + 1) / 2, (n + 2) / 2)
    GROUP BY route_number, time_band
),

-- Route-level fallback for bands that are too thin on their own: a suburban
-- route may log only a handful of overnight incidents in a whole year.
route_level AS (
    SELECT
        route_number,
        AVG(median_headway) AS route_median_headway,
        SUM(n_observations) AS route_observations
    FROM medians
    GROUP BY route_number
),

spread AS (
    SELECT
        o.route_number,
        o.time_band,
        -- Spread of the underlying observations, kept so I can see how tight
        -- each estimate is rather than trusting the point value blindly.
        MAX(o.implied_headway_min) - MIN(o.implied_headway_min) AS range_min
    FROM observations o
    GROUP BY o.route_number, o.time_band
)

SELECT
    rb.route_number,
    rb.time_band,
    COALESCE(m.n_observations, 0)                       AS n_observations,
    ROUND(m.median_headway, 2)                          AS raw_median_headway_min,
    ROUND(r.route_median_headway, 2)                    AS route_fallback_headway_min,
    s.range_min                                         AS observation_range_min,

    -- The value downstream marts actually use.
    ROUND(
        CASE
            WHEN COALESCE(m.n_observations, 0) >= {{MIN_INCIDENTS_FOR_HEADWAY}}
             AND COALESCE(m.median_headway, -1) BETWEEN {{MIN_PLAUSIBLE_HEADWAY_MIN}}
                                      AND {{MAX_PLAUSIBLE_HEADWAY_MIN}}
                THEN m.median_headway
            WHEN COALESCE(r.route_observations, 0) >= {{MIN_INCIDENTS_FOR_HEADWAY}}
             AND COALESCE(r.route_median_headway, -1) BETWEEN {{MIN_PLAUSIBLE_HEADWAY_MIN}}
                                            AND {{MAX_PLAUSIBLE_HEADWAY_MIN}}
                THEN r.route_median_headway
            ELSE {{FALLBACK_HEADWAY_MIN}}
        END
    , 2)                                                AS headway_min,

    CASE
        WHEN COALESCE(m.n_observations, 0) >= {{MIN_INCIDENTS_FOR_HEADWAY}}
         AND COALESCE(m.median_headway, -1) BETWEEN {{MIN_PLAUSIBLE_HEADWAY_MIN}}
                                  AND {{MAX_PLAUSIBLE_HEADWAY_MIN}}
            THEN 'band_estimate'
        WHEN COALESCE(r.route_observations, 0) >= {{MIN_INCIDENTS_FOR_HEADWAY}}
         AND COALESCE(r.route_median_headway, -1) BETWEEN {{MIN_PLAUSIBLE_HEADWAY_MIN}}
                                        AND {{MAX_PLAUSIBLE_HEADWAY_MIN}}
            THEN 'route_estimate'
        ELSE 'default_assumed'
    END                                                 AS headway_source
FROM route_bands rb
LEFT JOIN medians    m ON m.route_number = rb.route_number
                      AND m.time_band    = rb.time_band
LEFT JOIN route_level r ON r.route_number = rb.route_number
LEFT JOIN spread      s ON s.route_number = rb.route_number
                      AND s.time_band    = rb.time_band;

CREATE UNIQUE INDEX idx_headway_pk ON int_route_headway (route_number, time_band);

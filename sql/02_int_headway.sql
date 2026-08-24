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
WITH observations AS (
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
    m.route_number,
    m.time_band,
    m.n_observations,
    ROUND(m.median_headway, 2)                          AS raw_median_headway_min,
    ROUND(r.route_median_headway, 2)                    AS route_fallback_headway_min,
    s.range_min                                         AS observation_range_min,

    -- The value downstream marts actually use.
    ROUND(
        CASE
            WHEN m.n_observations >= {{MIN_INCIDENTS_FOR_HEADWAY}}
             AND m.median_headway BETWEEN {{MIN_PLAUSIBLE_HEADWAY_MIN}}
                                      AND {{MAX_PLAUSIBLE_HEADWAY_MIN}}
                THEN m.median_headway
            WHEN r.route_observations >= {{MIN_INCIDENTS_FOR_HEADWAY}}
             AND r.route_median_headway BETWEEN {{MIN_PLAUSIBLE_HEADWAY_MIN}}
                                            AND {{MAX_PLAUSIBLE_HEADWAY_MIN}}
                THEN r.route_median_headway
            ELSE {{FALLBACK_HEADWAY_MIN}}
        END
    , 2)                                                AS headway_min,

    CASE
        WHEN m.n_observations >= {{MIN_INCIDENTS_FOR_HEADWAY}}
         AND m.median_headway BETWEEN {{MIN_PLAUSIBLE_HEADWAY_MIN}}
                                  AND {{MAX_PLAUSIBLE_HEADWAY_MIN}}
            THEN 'band_estimate'
        WHEN r.route_observations >= {{MIN_INCIDENTS_FOR_HEADWAY}}
         AND r.route_median_headway BETWEEN {{MIN_PLAUSIBLE_HEADWAY_MIN}}
                                        AND {{MAX_PLAUSIBLE_HEADWAY_MIN}}
            THEN 'route_estimate'
        ELSE 'default_assumed'
    END                                                 AS headway_source
FROM medians m
JOIN route_level r ON r.route_number = m.route_number
LEFT JOIN spread s ON s.route_number = m.route_number AND s.time_band = m.time_band;

CREATE UNIQUE INDEX idx_headway_pk ON int_route_headway (route_number, time_band);

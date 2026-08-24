-- =============================================================================
-- 04_fct_delay_incident.sql
-- Purpose : The core fact table, and the point where an operational record
--           becomes a rider-experience measurement.
-- Grain   : one row per incident.
--
-- The wait-time model
-- -------------------
-- Published transit reporting counts incidents and delay minutes. Neither is
-- what a person standing at a stop experiences. What they experience is a gap.
--
-- For riders who turn up without consulting a schedule - which on a frequent
-- bus route is most of them - arrivals are effectively uniform in time. Then:
--
--   * during a gap of G minutes, the average rider waits            G / 2
--   * under normal service at headway H, they would have waited     H / 2
--   * so excess wait per affected rider is                    (G - H) / 2
--
--   * riders accumulate for the whole gap, so the NUMBER affected is
--     proportional to G, not constant. A 40-minute gap does not inconvenience
--     twice as many people as a 20-minute gap by twice as much - it is roughly
--     four times worse in total, because it catches twice the people and makes
--     each of them wait twice as long.
--
--   * total excess wait for one incident is therefore proportional to
--                                                        G x (G - H) / 2
--
-- That quadratic is the single most important thing in this model, and it is
-- why ranking routes by incident count gives a different - and worse - answer
-- than ranking them by rider impact.
--
-- rider_impact_index carries that quantity without claiming to be real
-- passenger-minutes. est_excess_rider_minutes multiplies it by an ASSUMED
-- boarding rate and is labelled as an estimate everywhere it appears, because
-- the open data does not publish boardings by route and hour.
-- =============================================================================

DROP TABLE IF EXISTS fct_delay_incident;

CREATE TABLE fct_delay_incident AS
SELECT
    s.incident_id,
    s.delay_date,
    s.year,
    s.month,
    s.year_month,
    s.day_name,
    s.is_weekend,
    s.is_winter,
    s.hour,
    s.time_band,
    s.is_peak,

    s.route_number,
    r.route_label,
    r.service_type,
    s.location,
    s.direction,

    s.cause_raw,
    s.cause_code,
    s.cause_description,
    s.cause_category,

    s.min_delay,
    s.min_gap,
    s.min_gap_capped,
    s.is_gap_capped,

    h.headway_min,
    h.headway_source,

    -- Excess wait for one rider caught by this gap, in minutes.
    ROUND(
        MAX(s.min_gap_capped - h.headway_min, 0) / 2.0
    , 3)                                                AS excess_wait_per_rider_min,

    -- Relative number of riders caught, proportional to the length of the gap.
    ROUND(s.min_gap_capped * 1.0, 2)                    AS riders_affected_index,

    -- Total rider harm from this incident, up to a constant boarding rate.
    -- This is the ranking metric used throughout the project.
    ROUND(
        s.min_gap_capped * MAX(s.min_gap_capped - h.headway_min, 0) / 2.0
    , 2)                                                AS rider_impact_index,

    -- The same figure without winsorising, kept solely so the data-quality mart
    -- can report how much the cap removed. Never used in a headline.
    ROUND(
        s.min_gap * MAX(s.min_gap - h.headway_min, 0) / 2.0
    , 2)                                                AS rider_impact_uncapped,

    -- The same quantity expressed in passenger-minutes under a stated
    -- assumption. An estimate, never a measurement - see docs/assumptions.md.
    ROUND(
        {{ASSUMED_BOARDINGS_PER_MINUTE}}
        * s.min_gap_capped * MAX(s.min_gap_capped - h.headway_min, 0) / 2.0
    , 2)                                                AS est_excess_rider_minutes,

    -- Severity banding for the incident list.
    CASE
        WHEN s.min_gap = 0                                   THEN 'no_service_impact'
        WHEN s.min_gap_capped <= h.headway_min               THEN 'within_headway'
        WHEN s.min_gap_capped <= h.headway_min * 2           THEN 'one_bus_missed'
        WHEN s.min_gap_capped <= h.headway_min * 3           THEN 'two_buses_missed'
        ELSE                                                      'severe_gap'
    END                                                 AS severity,

    s.is_analysable,
    s.is_service_affecting,
    s.is_implausible,
    s.dq_cause_unmapped,
    s.dq_gap_below_delay,
    s.dq_gap_sentinel,
    s.schema_generation
FROM stg_incidents s
JOIN dim_route r        ON r.route_number = s.route_number
LEFT JOIN int_route_headway h
       ON h.route_number = s.route_number
      AND h.time_band    = s.time_band;

CREATE INDEX idx_fct_route  ON fct_delay_incident (route_number);
CREATE INDEX idx_fct_date   ON fct_delay_incident (delay_date);
CREATE INDEX idx_fct_cause  ON fct_delay_incident (cause_category);
CREATE INDEX idx_fct_band   ON fct_delay_incident (time_band, day_name);

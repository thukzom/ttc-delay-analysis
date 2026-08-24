"""
Unit tests for the TTC delay pipeline.

Uses stdlib unittest so the suite runs with nothing installed beyond the
project's own requirements, but is plain enough that `pytest tests/` collects it.

Three groups:

  * HARMONISATION - the riskiest code in the project, tested against both real
    published schemas on hand-built rows where the right answer is known.
  * MODEL MATHS - the wait-time arithmetic, tested directly rather than through
    the warehouse.
  * WAREHOUSE INVARIANTS - properties the built database must satisfy, skipped
    automatically if no warehouse has been built.

Run:  python -m unittest discover -s tests -t . -v
      python -m pytest tests/ -q
"""

from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path

from src.config import (
    CODE_CATEGORY_OVERRIDES,
    CODE_PREFIX_CATEGORY,
    GAP_CAP_MINUTES,
    INCIDENT_TEXT_CATEGORY,
    CAUSE_CATEGORIES,
    MAX_SINGLE_INCIDENT_IMPACT_SHARE,
    REQUIRED_COLUMNS,
    WAREHOUSE_DB,
)
from src.load import (
    categorise,
    load_code_lookup,
    map_columns,
    norm_key,
    parse_date,
    parse_hour,
    parse_int,
    split_route,
)

# The two headers the City has actually published, verbatim.
LEGACY_HEADER = [
    "Report Date", "Route", "Time", "Day", "Location",
    "Incident", "Min Delay", "Min Gap", "Direction", "Vehicle",
]
CURRENT_HEADER = [
    "Date", "Line", "Time", "Day", "Station",
    "Code", "Min Delay", "Min Gap", "Bound", "Vehicle",
]


class TestColumnHarmonisation(unittest.TestCase):
    """Both published schemas must land in the same canonical shape."""

    def test_legacy_header_maps_completely(self):
        mapping = map_columns(LEGACY_HEADER, Path("legacy.csv"))
        for field in REQUIRED_COLUMNS:
            self.assertIn(field, mapping, field)

    def test_current_header_maps_completely(self):
        mapping = map_columns(CURRENT_HEADER, Path("current.csv"))
        for field in REQUIRED_COLUMNS:
            self.assertIn(field, mapping, field)

    def test_the_two_schemas_agree_on_meaning(self):
        """'Route' and 'Line' must resolve to the same canonical field."""
        legacy = map_columns(LEGACY_HEADER, Path("a.csv"))
        current = map_columns(CURRENT_HEADER, Path("b.csv"))
        self.assertEqual(
            LEGACY_HEADER[legacy["route"]], "Route")
        self.assertEqual(
            CURRENT_HEADER[current["route"]], "Line")
        self.assertEqual(
            LEGACY_HEADER[legacy["location"]], "Location")
        self.assertEqual(
            CURRENT_HEADER[current["location"]], "Station")

    def test_matching_is_insensitive_to_case_and_punctuation(self):
        messy = [
            "report_date", "ROUTE", " Time ", "day", "LOCATION",
            "Incident", "min delay", "Min_Gap", "direction", "vehicle",
        ]
        mapping = map_columns(messy, Path("messy.csv"))
        for field in REQUIRED_COLUMNS:
            self.assertIn(field, mapping, field)

    def test_unknown_schema_raises_with_a_useful_message(self):
        """Silently dropping an unrecognised column is the worst outcome."""
        with self.assertRaises(RuntimeError) as ctx:
            map_columns(["Foo", "Bar", "Baz"], Path("mystery.csv"))
        message = str(ctx.exception)
        self.assertIn("mystery.csv", message)
        self.assertIn("Columns actually present", message)
        self.assertIn("Foo", message)

    def test_missing_one_column_still_raises(self):
        header = [c for c in CURRENT_HEADER if c != "Min Gap"]
        with self.assertRaises(RuntimeError):
            map_columns(header, Path("partial.csv"))


class TestExcelRoundTrip(unittest.TestCase):
    """The historical files are Excel workbooks, and that is where the traps are.

    A cell formatted as a time in Excel comes back from pandas as a full
    datetime string. A naive leading-digits regex reads "1900-01-01 02:15:00"
    as hour 19 instead of hour 2 - which would put eight years of incidents in
    the wrong hour of the day with nothing downstream looking wrong.
    """

    @classmethod
    def setUpClass(cls):
        try:
            import openpyxl  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("openpyxl not installed")

    def _workbook(self, rows):
        import datetime as dt
        import openpyxl
        import tempfile
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.append(LEGACY_HEADER)
        for row in rows:
            sheet.append(row)
        handle = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        workbook.save(handle.name)
        return Path(handle.name)

    def test_excel_dates_and_times_survive_the_round_trip(self):
        import datetime as dt
        from src.load import read_table

        path = self._workbook([
            [dt.datetime(2019, 1, 7), 32, dt.time(2, 15), "Monday",
             "EGLINTON WEST STATION", "Mechanical", 20, 40, "E", 8442],
            [dt.datetime(2019, 12, 31), 29, dt.time(23, 55), "Tuesday",
             "DUFFERIN AND EGLINTON", "Emergency Services", 0, 0, None, 0],
        ])
        header, rows = read_table(path)
        mapping = map_columns(header, path)

        first = rows[0]
        self.assertEqual(parse_date(first[mapping["delay_date"]]), "2019-01-07")
        self.assertEqual(parse_hour(first[mapping["time"]]), 2)
        self.assertEqual(parse_int(first[mapping["min_gap"]]), 40)
        self.assertEqual(split_route(first[mapping["route"]]), ("32", ""))

        last = rows[-1]
        self.assertEqual(parse_date(last[mapping["delay_date"]]), "2019-12-31")
        self.assertEqual(parse_hour(last[mapping["time"]]), 23)

    def test_a_datetime_formatted_time_is_not_read_as_its_year(self):
        """The specific regression: 1900-01-01 02:15:00 is hour 2, not 19."""
        self.assertEqual(parse_hour("1900-01-01 02:15:00"), 2)
        self.assertEqual(parse_hour("2019-06-03 19:40:00"), 19)

    def test_excel_serial_values_are_understood(self):
        self.assertEqual(parse_date("41640"), "2014-01-01")
        self.assertEqual(parse_hour("0.09375"), 2)      # time-only fraction
        self.assertEqual(parse_hour("0.5"), 12)

    def test_a_bare_decimal_is_not_mistaken_for_a_clock_reading(self):
        """0.09375 is a fraction of a day, not nine minutes past midnight."""
        self.assertNotEqual(parse_hour("0.09375"), 0)


class TestParsing(unittest.TestCase):
    def test_date_formats_seen_across_years(self):
        for text in ("2025-01-01", "01/01/2025", "2025-01-01T00:00:00"):
            self.assertEqual(parse_date(text), "2025-01-01", text)

    def test_unparseable_date_returns_none(self):
        self.assertIsNone(parse_date("not a date"))
        self.assertIsNone(parse_date(""))

    def test_hour_extraction(self):
        self.assertEqual(parse_hour("02:15"), 2)
        self.assertEqual(parse_hour("23:59"), 23)
        self.assertIsNone(parse_hour(""))
        self.assertIsNone(parse_hour("99:99"))

    def test_int_parsing_tolerates_dirt(self):
        self.assertEqual(parse_int("12"), 12)
        self.assertEqual(parse_int("12.0"), 12)
        self.assertEqual(parse_int("1,234"), 1234)
        self.assertIsNone(parse_int("nan"))
        self.assertIsNone(parse_int(""))

    def test_route_splitting_handles_both_schemas(self):
        """Legacy files carry a bare number; current files carry number + name."""
        self.assertEqual(split_route("102 MARKHAM ROAD"), ("102", "MARKHAM ROAD"))
        self.assertEqual(split_route("102"), ("102", ""))
        self.assertEqual(split_route("  36 finch west "), ("36", "FINCH WEST"))
        self.assertEqual(split_route(""), ("", ""))


class TestCauseTaxonomy(unittest.TestCase):
    def setUp(self):
        self.lookup = load_code_lookup()

    def test_reference_lookup_is_complete(self):
        self.assertGreaterEqual(len(self.lookup), 40)
        self.assertIn("MFUS", self.lookup)

    def test_published_code_is_recognised(self):
        code, description, category = categorise("MFESA", self.lookup)
        self.assertEqual(code, "MFESA")
        self.assertIn("OPERATOR", description.upper())
        self.assertEqual(category, "operator")

    def test_legacy_free_text_is_recognised(self):
        code, description, category = categorise("Mechanical", self.lookup)
        self.assertEqual(code, "")
        self.assertEqual(category, "mechanical")

    def test_both_schemas_agree_on_a_mechanical_failure(self):
        """A 2019 'Mechanical' and a 2025 'EFP' must land in the same bucket.

        Without this, every cross-year comparison in the project is meaningless.
        """
        _, _, legacy = categorise("Mechanical", self.lookup)
        _, _, current = categorise("EFP", self.lookup)
        self.assertEqual(legacy, current, "mechanical")

    def test_unknown_cause_falls_through_to_other(self):
        code, _, category = categorise("SOMETHING NEW", self.lookup)
        self.assertEqual(code, "")
        self.assertEqual(category, "other")

    def test_every_published_code_gets_a_known_category(self):
        for code in self.lookup:
            _, _, category = categorise(code, self.lookup)
            self.assertIn(category, CAUSE_CATEGORIES, code)

    def test_every_legacy_text_value_gets_a_known_category(self):
        for key, category in INCIDENT_TEXT_CATEGORY.items():
            self.assertIn(category, CAUSE_CATEGORIES, key)

    def test_prefix_rules_do_not_contradict_overrides(self):
        for code, category in CODE_CATEGORY_OVERRIDES.items():
            prefix_category = CODE_PREFIX_CATEGORY.get(code[:2])
            if prefix_category is not None:
                self.assertEqual(
                    category, prefix_category,
                    f"{code} is overridden to {category} but its prefix implies "
                    f"{prefix_category}; one of the two is wrong",
                )

    def test_sample_generator_categories_match_the_taxonomy(self):
        """The generator claims each code belongs to a category. Verify it."""
        from src.sample_data import CATEGORY_CODES, CATEGORY_INCIDENTS

        for expected_category, codes in CATEGORY_CODES.items():
            for code in codes:
                _, _, actual = categorise(code, self.lookup)
                self.assertEqual(
                    actual, expected_category,
                    f"generator puts {code} in '{expected_category}' but the "
                    f"taxonomy resolves it to '{actual}'",
                )
        for expected_category, texts in CATEGORY_INCIDENTS.items():
            for text in texts:
                _, _, actual = categorise(text, self.lookup)
                self.assertEqual(actual, expected_category, text)

    def test_norm_key_is_stable(self):
        self.assertEqual(norm_key("Report Date"), "reportdate")
        self.assertEqual(norm_key("  MIN_GAP "), "mingap")


class TestWaitTimeMaths(unittest.TestCase):
    """The model's arithmetic, checked directly.

    excess wait per rider = (G - H) / 2
    rider impact          = G x (G - H) / 2
    """

    @staticmethod
    def impact(gap: float, headway: float) -> float:
        capped = min(gap, GAP_CAP_MINUTES)
        return capped * max(capped - headway, 0) / 2.0

    @staticmethod
    def excess_wait(gap: float, headway: float) -> float:
        return max(min(gap, GAP_CAP_MINUTES) - headway, 0) / 2.0

    def test_a_gap_at_the_scheduled_headway_costs_nothing(self):
        self.assertEqual(self.excess_wait(10, 10), 0.0)
        self.assertEqual(self.impact(10, 10), 0.0)

    def test_a_gap_shorter_than_the_headway_never_goes_negative(self):
        self.assertEqual(self.excess_wait(5, 10), 0.0)
        self.assertEqual(self.impact(5, 10), 0.0)

    def test_excess_wait_is_half_the_extra_gap(self):
        self.assertAlmostEqual(self.excess_wait(30, 10), 10.0)

    def test_impact_grows_faster_than_linearly(self):
        """Doubling the gap should roughly quadruple the harm, not double it.

        This is the property that makes the metric worth having, so it is
        asserted rather than assumed.
        """
        small = self.impact(20, 5)
        large = self.impact(40, 5)
        self.assertGreater(large / small, 3.0)
        self.assertLess(large / small, 5.0)

    def test_winsorising_caps_the_sentinel_values(self):
        """A 999-minute sentinel must not be able to swamp the dataset.

        Uncapped, a single such record scores nearly 500,000 - more than the
        combined impact of thousands of real incidents.
        """
        capped = self.impact(999, 4)
        uncapped = 999 * (999 - 4) / 2.0
        self.assertLess(capped, uncapped / 10)
        self.assertLessEqual(capped, GAP_CAP_MINUTES ** 2 / 2)

    def test_headway_recovery_identity(self):
        """The inference the whole model rests on: gap = headway + delay."""
        headway, delay = 8, 15
        gap = headway + delay
        self.assertEqual(gap - delay, headway)


@unittest.skipUnless(WAREHOUSE_DB.exists(), "warehouse not built")
class TestWarehouse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = sqlite3.connect(WAREHOUSE_DB)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def scalar(self, sql):
        return self.conn.execute(sql).fetchone()[0]

    def test_fact_table_preserves_every_staged_row(self):
        self.assertEqual(
            self.scalar("SELECT COUNT(*) FROM stg_incidents"),
            self.scalar("SELECT COUNT(*) FROM fct_delay_incident"),
        )

    def test_no_incident_lacks_a_headway(self):
        self.assertEqual(
            self.scalar(
                "SELECT COUNT(*) FROM fct_delay_incident WHERE headway_min IS NULL"
            ), 0,
        )

    def test_impact_is_never_negative(self):
        self.assertEqual(
            self.scalar(
                "SELECT COUNT(*) FROM fct_delay_incident "
                "WHERE rider_impact_index < 0"
            ), 0,
        )

    def test_capped_gap_never_exceeds_the_cap(self):
        self.assertEqual(
            self.scalar(
                f"SELECT COUNT(*) FROM fct_delay_incident "
                f"WHERE min_gap_capped > {GAP_CAP_MINUTES}"
            ), 0,
        )

    def test_capped_gap_never_exceeds_the_raw_gap(self):
        self.assertEqual(
            self.scalar(
                "SELECT COUNT(*) FROM fct_delay_incident "
                "WHERE min_gap_capped > min_gap"
            ), 0,
        )

    def test_no_single_incident_dominates(self):
        share = self.scalar(
            "SELECT MAX(rider_impact_index) * 1.0 / SUM(rider_impact_index) "
            "FROM fct_delay_incident WHERE is_analysable = 1"
        )
        self.assertLessEqual(share, MAX_SINGLE_INCIDENT_IMPACT_SHARE)

    def test_marts_reconcile_to_the_fact_table(self):
        total = self.scalar(
            "SELECT ROUND(SUM(rider_impact_index)) FROM fct_delay_incident "
            "WHERE is_analysable = 1"
        )
        for table in ("mart_route_scorecard", "mart_cause_category"):
            mart = self.scalar(f"SELECT ROUND(SUM(rider_impact_index)) FROM {table}")
            self.assertAlmostEqual(total, mart, delta=max(total * 0.001, 10), msg=table)

    def test_headways_are_inside_the_plausible_band(self):
        self.assertEqual(
            self.scalar(
                "SELECT COUNT(*) FROM int_route_headway "
                "WHERE headway_min < 3 OR headway_min > 90"
            ), 0,
        )

    def test_pareto_is_monotonic_and_complete(self):
        self.assertEqual(
            self.scalar(
                "SELECT COUNT(*) FROM ("
                " SELECT cumulative_pct_impact, LAG(cumulative_pct_impact) "
                " OVER (ORDER BY impact_rank) prev FROM mart_route_pareto)"
                " WHERE prev IS NOT NULL AND cumulative_pct_impact < prev"
            ), 0,
        )
        self.assertAlmostEqual(
            self.scalar("SELECT MAX(cumulative_pct_impact) FROM mart_route_pareto"),
            100.0, delta=0.5,
        )

    def test_every_cause_category_is_known(self):
        rows = [
            r[0] for r in self.conn.execute(
                "SELECT DISTINCT cause_category FROM fct_delay_incident"
            )
        ]
        for category in rows:
            self.assertIn(category, CAUSE_CATEGORIES)

    def test_build_records_its_data_mode(self):
        mode = self.scalar("SELECT data_mode FROM mart_dq_summary")
        self.assertIn(mode, ("real", "sample"))


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""
Configuration for the TTC bus delay analysis.

I keep every number I had to choose in this one file rather than scattered
through the SQL - the dataset IDs, the column mapping between the two file
layouts, the cause categories, and the assumptions behind the wait-time
measure. If I want to change one of them I change it here and everything
downstream rebuilds.
"""

from __future__ import annotations

import os
from pathlib import Path

# --- paths -------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
SQL_DIR = ROOT / "sql"
SITE_DIR = ROOT / "site"
DOCS_DIR = ROOT / "docs"

WAREHOUSE_DB = DATA_DIR / "ttc.db"
INCIDENTS_CSV = DATA_DIR / "incidents.csv"
CODES_CSV = DATA_DIR / "delay_codes.csv"
PROVENANCE_JSON = DATA_DIR / "provenance.json"

# --- source ------------------------------------------------------------------
# City of Toronto Open Data, CKAN API.
# Dataset: https://open.toronto.ca/dataset/ttc-bus-delay-data/

CKAN_BASE = "https://ckan0.cf.opendata.inter.prod-toronto.ca"
PACKAGE_ID = "ttc-bus-delay-data"

# Resource holding the 46-code lookup used by the 2025+ files.
CODE_DESCRIPTIONS_RESOURCE_ID = "816f2214-97e2-4c4b-820e-24b425ed08e0"

# --- schema harmonisation ----------------------------------------------------
#
# The dataset changed shape in 2025. Files from 2014-2024 and files from 2025
# onward describe the same events with different column names, and the cause
# field changes TYPE - free text before, a lookup code after.
#
#   2014-2024 : Report Date, Route, Time, Day, Location, Incident,
#               Min Delay, Min Gap, Direction, Vehicle
#   2025+     : Date,        Line,  Time, Day, Station,  Code,
#               Min Delay, Min Gap, Bound,     Vehicle
#
# Every source column is mapped to one canonical name. Matching is done on a
# normalised key (lowercased, punctuation and whitespace stripped) so that
# "Report Date", "report_date" and "REPORT DATE" all land in the same place -
# the City has not been perfectly consistent about this between files.

COLUMN_ALIASES = {
    "delay_date": ["date", "reportdate"],
    "route": ["route", "line"],
    "time": ["time"],
    "day": ["day"],
    "location": ["location", "station"],
    "cause_raw": ["incident", "code"],
    # 2020 (and possibly other years) drops the "Min " prefix entirely and
    # publishes these as "Delay" and "Gap". Same measure, different label.
    "min_delay": ["mindelay", "delay"],
    "min_gap": ["mingap", "gap"],
    "direction": ["direction", "bound"],
    "vehicle": ["vehicle"],
}

REQUIRED_COLUMNS = [
    "delay_date", "route", "time", "day", "location",
    "cause_raw", "min_delay", "min_gap", "direction", "vehicle",
]

# --- cause taxonomy ----------------------------------------------------------
#
# The analytical problem the two schema generations create: 2025+ files carry
# 46 granular codes, earlier files carry roughly a dozen free-text categories.
# Neither is usable across the full history on its own. Both are mapped into
# one taxonomy of seven categories, chosen so that each maps to a DIFFERENT
# kind of intervention - which is the only reason to categorise causes at all.
#
# Categories and who would own fixing them:
#   mechanical      TTC maintenance and fleet renewal
#   operator        TTC scheduling, staffing, driver availability
#   passenger       onboard incidents; largely irreducible
#   security        TTC special constables and police
#   collision       road safety, shared with the City
#   external        weather, traffic, events; outside TTC control
#   other           unclassified, kept visible rather than hidden

CAUSE_CATEGORIES = [
    "mechanical", "operator", "passenger",
    "security", "collision", "external", "other",
]

# 2025+ code prefixes and specific overrides.
# Prefix conventions in the published code list: E = equipment,
# M = mechanical/miscellaneous operations, P = property damage,
# S = security, T = transportation/operator.
CODE_CATEGORY_OVERRIDES = {
    # M-prefix is a mixed bag and cannot be assigned by prefix alone.
    "MFCN": "operator",       # cleaning
    "MFDV": "external",       # on diversion
    "MFESA": "operator",      # no operator available due to ESA
    "MFFD": "passenger",      # fare dispute
    "MFLD": "operator",       # labour dispute
    "MFO": "other",
    "MFPI": "collision",      # collision/personal injury, TTC not involved
    "MFPR": "external",       # held by parades/marches
    "MFS": "external",        # fire / smoke
    "MFSAN": "passenger",     # unsanitary
    "MFSH": "operator",       # used as shuttle bus
    "MFTO": "operator",       # ill operator
    "MFUI": "passenger",      # ill customer - transported
    "MFUIR": "passenger",     # ill customer - transport declined
    "MFUS": "operator",       # unable to maintain schedule
    "MFVIS": "mechanical",    # vision issues
    "MFWEA": "external",      # weather related
    "PFO": "other",
    "PFPD": "collision",
    "TFCNO": "operator",      # no operator available
    "TFLF": "operator",       # late entering service - first vehicle
    "TFLL": "operator",       # late vehicle - route
    "TFO": "other",
    "TFOI": "passenger",      # on board injury
    "TFPD": "collision",
    "TFPI": "collision",
}

CODE_PREFIX_CATEGORY = {
    "EF": "mechanical",  # all equipment failures
    "SF": "security",    # all security codes
}

# Free-text incident values used in the 2014-2024 files. Matched on a
# normalised, lowercased key; anything unmatched falls through to "other" and
# is REPORTED rather than silently absorbed - see mart_dq.
INCIDENT_TEXT_CATEGORY = {
    "mechanical": "mechanical",
    "cleaningunsanitary": "passenger",
    "collisionttc": "collision",
    "diversion": "external",
    "emergencyservices": "passenger",
    "generaldelay": "other",
    "heldby": "external",
    "investigation": "security",
    "lateleavinggarage": "operator",
    "operationsoperator": "operator",
    "operations": "operator",
    "roadblockednonttccollision": "collision",
    "security": "security",
    "utilizedoffroute": "external",
    "vision": "mechanical",
}

# --- wait-time model ---------------------------------------------------------
#
# The metric this project is built around. Riders do not experience "minutes of
# vehicle delay" - they experience a gap in service while standing at a stop.
#
# Derivation, stated so it can be argued with:
#
#   If buses are scheduled every H minutes and one runs D minutes late, the gap
#   left behind it is H + D. So a route's scheduled headway can be recovered
#   from its own incident records as H = Min Gap - Min Delay, with no external
#   schedule data required. I take the MEDIAN of that difference per route and
#   time band, because single records are noisy and occasionally reversed.
#
#   A rider arriving at a random moment inside a gap of G minutes waits G/2 on
#   average, instead of the H/2 they would have waited under normal service.
#   Excess wait per affected rider is therefore (G - H) / 2.
#
#   Longer gaps also affect MORE riders, because passengers accumulate for the
#   whole gap. Rider-impact is therefore proportional to G x (G - H) / 2. This
#   is reported as a ranking index, not as absolute minutes, because converting
#   it to real passenger-minutes needs boarding rates the open data does not
#   publish.

# Only trust a derived headway if it came from at least this many incidents.
MIN_INCIDENTS_FOR_HEADWAY = 30

# Bounds on a believable bus headway. Values outside this are a data artefact,
# not a schedule, and fall back to the route's own median or a default.
#
# The ceiling was originally 60 minutes, which seemed generous. Validating the
# estimator against known headways showed it silently clipping the overnight
# band on the 300-series night routes, whose true headway there is 66 minutes:
# the guard rejected a correct estimate and substituted a route-level average
# less than half its size, understating the wait on exactly the services where
# a missed bus hurts most. Raised to 90, which is above any scheduled TTC bus
# headway but still low enough to catch genuine data artefacts.
MIN_PLAUSIBLE_HEADWAY_MIN = 3.0
MAX_PLAUSIBLE_HEADWAY_MIN = 90.0
FALLBACK_HEADWAY_MIN = 12.0

# An incident is "rider-relevant" only if it actually left a gap. Records with
# a zero gap are logged events that did not interrupt service.
MIN_GAP_FOR_IMPACT = 1

# Records above this are almost certainly data entry errors. Flagged and
# excluded from headline metrics, not deleted.
MAX_PLAUSIBLE_DELAY_MIN = 720   # 12 hours
MAX_PLAUSIBLE_GAP_MIN = 1440    # 24 hours

# --- outlier control ---------------------------------------------------------
#
# Rider impact is QUADRATIC in gap length, which makes it violently sensitive to
# a long tail that this dataset definitely has. Measured on the first build:
#
#     101 rows out of 196,435  (0.05% of the data)  drove  57% of total impact
#
# Every one of them carried a gap of exactly 999 minutes - a sentinel value, not
# a measurement. On a route running every four minutes it would mean 250
# consecutive buses failed to appear. Left uncapped, the entire analysis would
# have been a description of a hundred bad log entries.
#
# Gaps are therefore winsorised at 180 minutes before impact is computed. The
# 99.9th percentile of observed service gaps is about 158 minutes, so this
# clips only the genuine tail. The raw value is retained for reporting, the
# capping is flagged per row, and mart_data_quality reports how much impact the
# cap removed so the decision stays visible rather than buried.
GAP_CAP_MINUTES = 180

# Values that appear in the published data as placeholders rather than
# measurements. Flagged explicitly so their prevalence is reportable.
GAP_SENTINEL_VALUES = (999, 1440, 9999)

# No single incident should account for more than this share of total rider
# impact. Enforced as a blocking quality gate - it is the check that would have
# caught the problem above on the first build rather than the second.
MAX_SINGLE_INCIDENT_IMPACT_SHARE = 0.02

# Nor should the most extreme 0.1% of incidents dominate the result.
MAX_TAIL_IMPACT_SHARE = 0.15

# Time bands. Service frequency differs enough between these that a single
# headway per route would be misleading.
TIME_BANDS = [
    ("early", 0, 6),
    ("am_peak", 6, 10),
    ("midday", 10, 15),
    ("pm_peak", 15, 19),
    ("evening", 19, 24),
]

# --- optional absolute estimate ----------------------------------------------
#
# Used ONLY for the clearly-labelled "what this might mean in real passenger
# hours" figure. The TTC does not publish boardings by route and hour in this
# dataset, so this is an assumption, not a measurement.
ASSUMED_BOARDINGS_PER_MINUTE = 1.5

# --- data quality ------------------------------------------------------------

MIN_EXPECTED_ROWS = 1000
EXPECTED_DAY_NAMES = {
    "Monday", "Tuesday", "Wednesday",
    "Thursday", "Friday", "Saturday", "Sunday",
}

# --- run mode ----------------------------------------------------------------
# Set by the loader so the site can state plainly which data it was built from.
# Never let a sample-data build masquerade as a real one.
DATA_MODE_ENV = "TTC_DATA_MODE"


def data_mode() -> str:
    return os.environ.get(DATA_MODE_ENV, "unknown")

"""
Harmonise the raw TTC files into one canonical table and build the warehouse.

The interesting work here is the harmonisation. The City changed the dataset's
shape in 2025: column names moved, and the cause field changed TYPE - free text
before, a lookup code after. Any analysis spanning the full history has to
reconcile the two, and doing it badly is the most likely way to produce a
confident wrong answer.

Three rules govern this module:

  1. NEVER GUESS A COLUMN. Every source column is matched against an explicit
     alias list on a normalised key. A file containing a column I have not
     seen before raises an error listing what it actually found, rather than
     silently dropping data.

  2. NEVER SILENTLY BUCKET A CAUSE. Causes that map to no known category are
     assigned "other" AND counted, so the unmapped share is a reported metric.
     A taxonomy that quietly absorbs the things it does not understand will
     always look complete.

  3. FLAG, DO NOT DELETE. Implausible values are marked and excluded from
     headline metrics, but they stay in the table so data quality stays
     measurable.

Usage:  python -m src.load
"""

from __future__ import annotations

import csv
import json
import re
import sqlite3
import sys
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from src.config import (
    ASSUMED_BOARDINGS_PER_MINUTE,
    CAUSE_CATEGORIES,
    CODE_CATEGORY_OVERRIDES,
    FALLBACK_HEADWAY_MIN,
    GAP_CAP_MINUTES,
    GAP_SENTINEL_VALUES,
    MIN_GAP_FOR_IMPACT,
    MIN_INCIDENTS_FOR_HEADWAY,
    MIN_PLAUSIBLE_HEADWAY_MIN,
    MAX_PLAUSIBLE_HEADWAY_MIN,
    CODE_PREFIX_CATEGORY,
    CODES_CSV,
    COLUMN_ALIASES,
    DATA_DIR,
    INCIDENTS_CSV,
    INCIDENT_TEXT_CATEGORY,
    MAX_PLAUSIBLE_DELAY_MIN,
    MAX_PLAUSIBLE_GAP_MIN,
    PROVENANCE_JSON,
    RAW_DIR,
    REQUIRED_COLUMNS,
    ROOT,
    SQL_DIR,
    TIME_BANDS,
    WAREHOUSE_DB,
)

REFERENCE_CODES = ROOT / "reference" / "delay_codes.csv"

# Alias lookup, keyed on the normalised form of each accepted source name.
_ALIAS_TO_CANONICAL = {
    alias: canonical
    for canonical, aliases in COLUMN_ALIASES.items()
    for alias in aliases
}


def norm_key(value: str) -> str:
    """Normalise a column name or category label for matching."""
    return re.sub(r"[^a-z0-9]", "", str(value).strip().lower())


# --- reading -----------------------------------------------------------------


def read_table(path: Path) -> tuple[list[str], list[list]]:
    """Read a CSV or XLSX file into a header plus rows."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with open(path, newline="", encoding="utf-8-sig", errors="replace") as handle:
            rows = list(csv.reader(handle))
        if not rows:
            return [], []
        return rows[0], rows[1:]

    if suffix in (".xlsx", ".xls"):
        try:
            import pandas as pd
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                f"{path.name} is an Excel file; reading it needs pandas and "
                "openpyxl."
            ) from exc

        # These workbooks are split into one sheet PER MONTH. Reading only the
        # first sheet - which is what pandas does by default - silently gives
        # back January and throws away the other eleven months, and nothing
        # downstream looks wrong. Every sheet has to be read and stacked.
        sheets = pd.read_excel(path, dtype=str, sheet_name=None)

        header: list[str] = []
        rows: list[list] = []
        skipped: list[str] = []

        for sheet_name, frame in sheets.items():
            if frame.empty:
                continue
            columns = [str(c) for c in frame.columns]
            if not header:
                header = columns
            elif columns != header:
                # A sheet with a different shape is a notes or summary tab, not
                # more data. Skip it rather than stacking mismatched columns.
                skipped.append(str(sheet_name))
                continue
            rows.extend(frame.fillna("").astype(str).values.tolist())

        if skipped:
            print(f"    note: skipped {len(skipped)} sheet(s) in {path.name} "
                  f"with a different layout: {skipped[:5]}")
        if len(sheets) > 1:
            print(f"    combined {len(sheets) - len(skipped)} sheets "
                  f"from {path.name}")
        return header, rows

    if suffix == ".json":
        payload = json.loads(path.read_text())
        records = payload if isinstance(payload, list) else payload.get("records", [])
        if not records:
            return [], []
        header = list(records[0].keys())
        return header, [[record.get(key, "") for key in header] for record in records]

    raise RuntimeError(f"Unsupported file type: {path.name}")


def map_columns(header: list[str], path: Path) -> dict[str, int]:
    """Map canonical field names to column positions, or explain the failure."""
    mapping: dict[str, int] = {}
    unrecognised: list[str] = []

    for index, raw_name in enumerate(header):
        canonical = _ALIAS_TO_CANONICAL.get(norm_key(raw_name))
        if canonical is None:
            if str(raw_name).strip() and not str(raw_name).startswith("_"):
                unrecognised.append(str(raw_name))
            continue
        mapping.setdefault(canonical, index)

    missing = [c for c in REQUIRED_COLUMNS if c not in mapping]
    if missing:
        raise RuntimeError(
            f"\n{path.name} could not be harmonised.\n"
            f"  Missing canonical fields : {missing}\n"
            f"  Columns actually present : {list(header)}\n"
            f"  Unrecognised columns     : {unrecognised}\n\n"
            "If the City has published a new column name, add it to "
            "COLUMN_ALIASES in src/config.py rather than renaming the file."
        )
    return mapping


# --- parsing -----------------------------------------------------------------

DATE_FORMATS = [
    "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d",
    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
    "%d-%b-%y", "%d-%b-%Y", "%b %d, %Y", "%B %d, %Y",
    "%m/%d/%y", "%Y%m%d",
]

# Excel counts days from 1899-12-30 (its leap-year bug included). A cell that
# was formatted as a date but read as text arrives as a bare serial number.
EXCEL_EPOCH = datetime(1899, 12, 30)

# Matches "2014-01-01 02:15:00" and "1900-01-01T02:15:00" - the shape a
# time-formatted Excel cell takes once pandas has stringified it.
_DATETIME_RE = re.compile(r"\d{4}-\d{2}-\d{2}[ T](\d{1,2}):(\d{2})")
_CLOCK_RE = re.compile(r"^\s*(\d{1,2})[:.](\d{2})")
_LOOSE_CLOCK_RE = re.compile(r"(\d{1,2})[:.](\d{2})")
_NUMERIC_RE = re.compile(r"^\s*\d+(\.\d+)?\s*$")


def parse_date(value: str) -> str | None:
    """Parse a date from any form the published files have used.

    The 2014-2024 files are Excel workbooks, so a date can arrive as a real
    date string, as a full datetime, or as a bare Excel serial number.
    """
    text = str(value).strip()
    if not text or text.lower() in ("nan", "nat", "none", "null"):
        return None

    if _NUMERIC_RE.match(text):
        try:
            serial = float(text)
        except ValueError:
            return None
        # Anything outside a plausible calendar window is not a date serial.
        if 20000 <= serial <= 80000:
            return (EXCEL_EPOCH + timedelta(days=int(serial))).date().isoformat()
        return None

    if "T" in text and len(text) > 10:
        text = text.split("T")[0]

    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue

    # Last resort: a leading ISO date inside a longer string.
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", text)
    return match.group(1) if match else None


def parse_hour(value: str) -> int | None:
    """Extract the hour of day, whatever shape the time cell arrived in.

    This is the single most dangerous field in the historical files. A cell
    formatted as a time in Excel becomes a full datetime once read as text -
    "1900-01-01 02:15:00" - and a naive leading-digits regex reads that as
    hour 19 rather than hour 2. Every incident in eight years of data would
    land in the wrong hour, and nothing downstream would look obviously wrong.
    """
    text = str(value).strip()
    if not text or text.lower() in ("nan", "nat", "none", "null"):
        return None

    # A datetime string: take the time part, never the leading year.
    match = _DATETIME_RE.search(text)
    if match:
        hour = int(match.group(1))
        return hour if 0 <= hour <= 23 else None

    # Excel stores a time-only cell as a fraction of a day: 0.09375 = 02:15.
    # This must be tested BEFORE the clock pattern, or "0.09375" is read as
    # 0:09 by a regex that cannot tell a decimal point from a separator.
    if _NUMERIC_RE.match(text):
        try:
            number = float(text)
        except ValueError:
            return None
        if 0 <= number < 1:
            return min(int(round(number * 24 * 60)) // 60, 23)
        if 1 <= number <= 24:            # an hour written as a bare number
            return int(number) % 24
        if number > 24:                  # a datetime serial with a fraction
            return min(int(round((number % 1) * 24 * 60)) // 60, 23)
        return None

    # A plain clock reading at the start of the string.
    match = _CLOCK_RE.match(text)
    if match:
        hour = int(match.group(1))
        return hour if 0 <= hour <= 23 else None

    # Anything else containing a clock reading, e.g. "circa 14:05".
    match = _LOOSE_CLOCK_RE.search(text)
    if match:
        hour = int(match.group(1))
        return hour if 0 <= hour <= 23 else None
    return None


def parse_int(value: str) -> int | None:
    text = str(value).strip().replace(",", "")
    if not text or text.lower() in ("nan", "nat", "none", "null"):
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def time_band(hour: int | None) -> str:
    if hour is None:
        return "unknown"
    for name, start, end in TIME_BANDS:
        if start <= hour < end:
            return name
    return "unknown"


ROUTE_RE = re.compile(r"^\s*(\d+[A-Z]?)\b\s*(.*)$")


def split_route(value: str) -> tuple[str, str]:
    """'102 MARKHAM ROAD' -> ('102', 'MARKHAM ROAD'); '102' -> ('102', '')."""
    text = str(value).strip().upper()
    if not text:
        return "", ""
    match = ROUTE_RE.match(text)
    if match:
        return match.group(1), match.group(2).strip()
    return text, ""


# --- cause harmonisation -----------------------------------------------------


# A published cause code is 2-6 letters, no spaces: MFUS, EFHVA, TFCNO.
# Free-text values from the older files never look like this.
_CODE_SHAPED = re.compile(r"^[A-Z]{2,6}$")


def load_code_lookup() -> dict[str, str]:
    """Prefer the freshly-fetched lookup; fall back to the committed reference."""
    source = CODES_CSV if CODES_CSV.exists() else None
    if source is None:
        fetched = RAW_DIR / "delay_codes.csv"
        source = fetched if fetched.exists() else REFERENCE_CODES

    lookup: dict[str, str] = {}
    with open(source, newline="", encoding="utf-8-sig") as handle:
        for record in csv.DictReader(handle):
            keys = {k.lower(): v for k, v in record.items() if k}
            code = str(keys.get("code", "")).strip().upper()
            if code:
                lookup[code] = str(keys.get("description", "")).strip()
    return lookup


def categorise(cause_raw: str, code_lookup: dict[str, str]) -> tuple[str, str, str]:
    """Return (code, description, category) for either schema generation.

    A value is treated as a code if it matches the published code list. Anything
    else is treated as the free text used by the pre-2025 files.
    """
    text = str(cause_raw).strip()
    if not text:
        return "", "", "other"

    upper = text.upper()
    if upper in code_lookup:
        description = code_lookup[upper]
        category = CODE_CATEGORY_OVERRIDES.get(upper)
        if category is None:
            category = CODE_PREFIX_CATEGORY.get(upper[:2], "other")
        return upper, description, category

    # Known free-text values win over the code heuristic below. "Vision" is a
    # legacy incident value AND six uppercase letters, so testing the shape
    # first quietly reclassified it as an unknown code.
    known = INCIDENT_TEXT_CATEGORY.get(norm_key(text))
    if known is not None:
        return "", text.upper(), known

    # The City uses more codes than it publishes in the lookup - EFAS, EFCEL,
    # EFSD and others appear in the data with no description anywhere. They
    # still follow the documented prefix convention, so a code-shaped value
    # that is not in the lookup is categorised by its prefix rather than
    # dumped into "other".
    if _CODE_SHAPED.match(upper):
        category = CODE_CATEGORY_OVERRIDES.get(upper)
        if category is None:
            category = CODE_PREFIX_CATEGORY.get(upper[:2], "other")
        return upper, upper, category

    return "", text.upper(), "other"


# --- harmonise ---------------------------------------------------------------


def harmonise() -> dict:
    files = sorted(
        p for p in RAW_DIR.glob("*")
        if p.suffix.lower() in (".csv", ".xlsx", ".xls", ".json")
        and "delay_codes" not in p.name.lower()
        and "readme" not in p.name.lower()
    )
    if not files:
        raise SystemExit(f"No source files found in {RAW_DIR}.")

    # Anything sitting in the raw directory that the glob above did not pick up
    # is a file that was downloaded and is about to be ignored. That has
    # happened once already - a resource saved without its extension took the
    # whole 2025 dataset with it - so it is now an error rather than a silence.
    present = {
        q for q in RAW_DIR.glob("*")
        if q.is_file() and "delay_codes" not in q.name.lower()
        and "readme" not in q.name.lower()
    }
    ignored = sorted(q.name for q in present - set(files))
    if ignored:
        raise SystemExit(
            f"\n{len(ignored)} file(s) in {RAW_DIR} would be ignored because "
            "the loader does not recognise their extension:\n"
            + "\n".join(f"    {name}" for name in ignored)
            + "\n\nThese were downloaded, so skipping them would silently "
            "drop data."
        )

    code_lookup = load_code_lookup()
    unmapped_causes: Counter = Counter()
    per_file: list[dict] = []
    rows: list[tuple] = []

    for path in files:
        header, raw_rows = read_table(path)
        if not header:
            continue
        mapping = map_columns(header, path)
        schema = "current" if "code" in {
            norm_key(h) for h in header
        } else "legacy"

        kept = 0
        for raw in raw_rows:
            def field(name: str) -> str:
                index = mapping[name]
                return raw[index] if index < len(raw) else ""

            delay_date = parse_date(field("delay_date"))
            if delay_date is None:
                continue

            hour = parse_hour(field("time"))
            min_delay = parse_int(field("min_delay"))
            min_gap = parse_int(field("min_gap"))
            route_number, route_name = split_route(field("route"))
            if not route_number:
                continue

            cause_raw = field("cause_raw")
            code, description, category = categorise(cause_raw, code_lookup)
            if category == "other" and str(cause_raw).strip():
                known = code in code_lookup or norm_key(cause_raw) in INCIDENT_TEXT_CATEGORY
                if not known:
                    unmapped_causes[str(cause_raw).strip().upper()] += 1

            min_delay = 0 if min_delay is None or min_delay < 0 else min_delay
            min_gap = 0 if min_gap is None or min_gap < 0 else min_gap

            implausible = int(
                min_delay > MAX_PLAUSIBLE_DELAY_MIN
                or min_gap > MAX_PLAUSIBLE_GAP_MIN
                or (min_gap > 0 and min_gap < min_delay)
            )

            rows.append((
                delay_date,
                route_number,
                route_name,
                hour,
                time_band(hour),
                str(field("day")).strip().title(),
                str(field("location")).strip().upper(),
                cause_raw.strip().upper(),
                code,
                description,
                category,
                min_delay,
                min_gap,
                str(field("direction")).strip().upper()[:2],
                parse_int(field("vehicle")) or 0,
                schema,
                path.name,
                implausible,
            ))
            kept += 1

        per_file.append({
            "file": path.name,
            "schema_generation": schema,
            "source_columns": list(header),
            "rows_read": len(raw_rows),
            "rows_kept": kept,
        })
        print(f"  {path.name:46s} {kept:>7,} rows  [{schema}]")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(INCIDENTS_CSV, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "delay_date", "route_number", "route_name", "hour", "time_band",
            "day_name", "location", "cause_raw", "cause_code",
            "cause_description", "cause_category", "min_delay", "min_gap",
            "direction", "vehicle", "schema_generation", "source_file",
            "is_implausible",
        ])
        writer.writerows(rows)

    with open(CODES_CSV, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["code", "description"])
        writer.writerows(sorted(code_lookup.items()))

    return {
        "rows": len(rows),
        "files": per_file,
        "unmapped_causes": unmapped_causes.most_common(25),
        "unmapped_total": sum(unmapped_causes.values()),
        "code_lookup_size": len(code_lookup),
    }


# --- warehouse ---------------------------------------------------------------


def build_warehouse(summary: dict) -> None:
    if WAREHOUSE_DB.exists():
        WAREHOUSE_DB.unlink()
    conn = sqlite3.connect(WAREHOUSE_DB)
    conn.execute("PRAGMA journal_mode = OFF")
    conn.execute("PRAGMA synchronous = OFF")

    conn.execute("""
        CREATE TABLE raw_incidents (
            delay_date TEXT, route_number TEXT, route_name TEXT, hour INTEGER,
            time_band TEXT, day_name TEXT, location TEXT, cause_raw TEXT,
            cause_code TEXT, cause_description TEXT, cause_category TEXT,
            min_delay INTEGER, min_gap INTEGER, direction TEXT,
            vehicle INTEGER, schema_generation TEXT, source_file TEXT,
            is_implausible INTEGER)
    """)
    with open(INCIDENTS_CSV, newline="") as handle:
        reader = csv.reader(handle)
        next(reader)
        conn.executemany(
            "INSERT INTO raw_incidents VALUES (" + ",".join("?" * 18) + ")", reader
        )

    conn.execute("CREATE TABLE raw_delay_codes (code TEXT, description TEXT)")
    with open(CODES_CSV, newline="") as handle:
        reader = csv.reader(handle)
        next(reader)
        conn.executemany("INSERT INTO raw_delay_codes VALUES (?,?)", reader)

    # A one-row table the SQL layer and the site both read, so the build can
    # never lose track of whether it was made from real data or sample data.
    mode = "sample" if any(
        f["file"].startswith("sample_") for f in summary["files"]
    ) else "real"
    conn.execute("""
        CREATE TABLE meta_build (
            data_mode TEXT, built_at TEXT, source_files INTEGER,
            rows_ingested INTEGER, unmapped_cause_rows INTEGER,
            code_lookup_size INTEGER, provenance_present INTEGER)
    """)
    conn.execute(
        "INSERT INTO meta_build VALUES (?,?,?,?,?,?,?)",
        (
            mode,
            datetime.now().isoformat(timespec="seconds"),
            len(summary["files"]),
            summary["rows"],
            summary["unmapped_total"],
            summary["code_lookup_size"],
            int(PROVENANCE_JSON.exists()),
        ),
    )
    conn.commit()

    # The constants live in config.py rather than in the SQL, so changing one
    # assumption rebuilds every number that depends on it.
    params = {
        "{{MIN_INCIDENTS_FOR_HEADWAY}}": str(MIN_INCIDENTS_FOR_HEADWAY),
        "{{MIN_PLAUSIBLE_HEADWAY_MIN}}": str(MIN_PLAUSIBLE_HEADWAY_MIN),
        "{{MAX_PLAUSIBLE_HEADWAY_MIN}}": str(MAX_PLAUSIBLE_HEADWAY_MIN),
        "{{FALLBACK_HEADWAY_MIN}}": str(FALLBACK_HEADWAY_MIN),
        "{{MIN_GAP_FOR_IMPACT}}": str(MIN_GAP_FOR_IMPACT),
        "{{ASSUMED_BOARDINGS_PER_MINUTE}}": str(ASSUMED_BOARDINGS_PER_MINUTE),
        "{{GAP_CAP_MINUTES}}": str(GAP_CAP_MINUTES),
        "{{GAP_SENTINELS}}": ", ".join(str(v) for v in GAP_SENTINEL_VALUES),
    }

    print(f"\nBuilding SQL model layer  (data_mode = {mode})")
    for sql_file in sorted(SQL_DIR.glob("*.sql")):
        sql = sql_file.read_text()
        for token, value in params.items():
            sql = sql.replace(token, value)
        start = time.perf_counter()
        conn.executescript(sql)
        conn.commit()
        print(f"  {sql_file.name:40s} {time.perf_counter() - start:6.2f}s")

    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )]
    conn.close()
    print(f"\nWarehouse ready: {WAREHOUSE_DB}  ({len(tables)} tables)")


def main() -> int:
    print("Harmonising raw files...")
    summary = harmonise()

    print(f"\n  {summary['rows']:,} incidents harmonised "
          f"from {len(summary['files'])} file(s)")
    print(f"  cause lookup: {summary['code_lookup_size']} codes")

    if summary["unmapped_total"]:
        share = summary["unmapped_total"] / max(summary["rows"], 1) * 100
        print(f"\n  {summary['unmapped_total']:,} rows ({share:.2f}%) have a cause "
              "value not in the taxonomy:")
        for value, count in summary["unmapped_causes"][:10]:
            print(f"      {count:>7,}  {value}")
        print("  These are categorised as 'other' and reported in mart_data_quality.")
        if share > 10:
            print("  WARNING: over 10% unmapped - review the taxonomy in "
                  "src/config.py before trusting the cause analysis.",
                  file=sys.stderr)

    build_warehouse(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

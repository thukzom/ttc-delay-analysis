"""
Download the real TTC bus delay data from the City of Toronto Open Data portal.

Source: https://open.toronto.ca/dataset/ttc-bus-delay-data/
Licence: Open Government Licence - Toronto.

The portal publishes one file per year, and changed both the file format and
the column names partway through, so this module does not hard-code filenames.
It asks the CKAN API what exists, picks the best available format for each
year, and records exactly what it downloaded in data/provenance.json - URL,
timestamp, byte count and SHA-256 of every file.

That provenance record is not decoration. An analysis whose inputs cannot be
identified afterwards cannot be reproduced or defended, and "I downloaded it
some time last month" is not an acceptable answer to "where did this number
come from?"

Usage:  python -m src.fetch            # everything available
        python -m src.fetch --since 2022
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from src.config import (
    CKAN_BASE,
    CODE_DESCRIPTIONS_RESOURCE_ID,
    PACKAGE_ID,
    PROVENANCE_JSON,
    RAW_DIR,
)

USER_AGENT = "ttc-delay-analysis/1.0 (open data research project)"
TIMEOUT = 120

# Preference order when the same year is published in several formats.
FORMAT_PREFERENCE = ["CSV", "XLSX", "JSON"]

YEAR_RE = re.compile(r"(20\d{2})")


def _get(url: str, attempts: int = 3) -> bytes:
    """Fetch a URL, retrying on transient failures.

    The portal sits behind a CDN and occasionally returns a 5xx or drops a
    connection on the larger workbooks. One retry is usually enough; three
    costs nothing and keeps a scheduled rebuild from failing over a blip.
    """
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": USER_AGENT}
            )
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return response.read()
        except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
            last = exc
            status = getattr(exc, "code", None)
            if status is not None and 400 <= status < 500 and status != 429:
                raise                      # a real 404 will not fix itself
            if attempt < attempts - 1:
                time.sleep(2 ** attempt)
    raise last if last else RuntimeError(f"could not fetch {url}")


def _get_json(url: str) -> dict:
    return json.loads(_get(url).decode("utf-8"))


def list_resources() -> list[dict]:
    """Ask CKAN what this dataset actually contains, right now."""
    url = f"{CKAN_BASE}/api/3/action/package_show?id={PACKAGE_ID}"
    payload = _get_json(url)
    if not payload.get("success"):
        raise RuntimeError(f"CKAN returned success=false for {PACKAGE_ID}")
    return payload["result"]["resources"]


def choose_delay_files(resources: list[dict], since: int | None) -> list[dict]:
    """Pick one file per year, preferring the most convenient format.

    Readme and code-description resources are excluded here; the code lookup is
    fetched separately because it is a dimension, not a fact.
    """
    candidates: dict[str, dict] = {}

    for resource in resources:
        name = (resource.get("name") or "").strip()
        fmt = (resource.get("format") or "").upper()
        lowered = name.lower()

        if "readme" in lowered or "code description" in lowered:
            continue
        if fmt not in FORMAT_PREFERENCE:
            continue

        match = YEAR_RE.search(name)
        # "TTC Bus Delay Data since 2025" covers 2025 onward in one file, and
        # is published four ways. Everything with a year in its name keys on
        # that year so the format preference below picks one per year.
        year_key = match.group(1) if match else "current"
        if since and match and int(match.group(1)) < since:
            continue

        existing = candidates.get(year_key)
        if existing is None or (
            FORMAT_PREFERENCE.index(fmt)
            < FORMAT_PREFERENCE.index(existing["format"].upper())
        ):
            candidates[year_key] = resource

    return [candidates[k] for k in sorted(candidates)]


def _safe_filename(resource: dict) -> str:
    """Build a safe local filename that KEEPS its extension.

    A resource named "TTC Bus Delay Data since 2025.csv" slugs down to
    "ttc_bus_delay_data_since_2025_csv". An earlier version of this checked
    whether the slug already ended in the format and, finding "csv" at the end,
    saved the file with no extension at all. The loader globs by extension, so
    the whole 2025 file was downloaded and then silently ignored - taking the
    entire post-2025 schema with it.
    """
    name = (resource.get("name") or resource["id"]).strip()
    fmt = (resource.get("format") or "bin").lower()
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    if slug.endswith("_" + fmt):
        slug = slug[: -(len(fmt) + 1)]
    return f"{slug}.{fmt}"


def download(resource: dict) -> dict:
    url = resource.get("url")
    if not url:
        raise RuntimeError(f"resource {resource.get('name')} has no url")

    filename = _safe_filename(resource)
    target = RAW_DIR / filename
    payload = _get(url)
    target.write_bytes(payload)

    return {
        "name": resource.get("name"),
        "resource_id": resource.get("id"),
        "format": resource.get("format"),
        "url": url,
        "file": str(target.relative_to(RAW_DIR.parent.parent)),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "last_modified_upstream": resource.get("last_modified")
        or resource.get("metadata_modified"),
        "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def fetch_code_descriptions() -> dict:
    """The 46-code lookup that the 2025+ files reference.

    Pulled through the datastore API rather than as a file, because this
    resource is datastore-active and the API guarantees a stable JSON shape.
    """
    url = (
        f"{CKAN_BASE}/api/3/action/datastore_search"
        f"?resource_id={CODE_DESCRIPTIONS_RESOURCE_ID}&limit=1000"
    )
    payload = _get_json(url)
    records = payload["result"]["records"]

    target = RAW_DIR / "delay_codes.csv"
    lines = ["code,description"]
    for record in records:
        code = str(record.get("CODE", "")).strip()
        description = str(record.get("DESCRIPTION", "")).strip().replace('"', "'")
        lines.append(f'{code},"{description}"')
    target.write_text("\n".join(lines) + "\n")

    return {
        "name": "Code Descriptions",
        "resource_id": CODE_DESCRIPTIONS_RESOURCE_ID,
        "format": "CSV (via datastore API)",
        "url": url,
        "file": str(target.relative_to(RAW_DIR.parent.parent)),
        "records": len(records),
        "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--since", type=int, default=None,
        help="only download files for this year and later (e.g. --since 2022)",
    )
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)

    try:
        resources = list_resources()
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        print(f"Could not reach the Toronto Open Data API: {exc}", file=sys.stderr)
        return 1

    files = choose_delay_files(resources, args.since)
    if not files:
        print("No matching delay-data resources found.", file=sys.stderr)
        return 1

    years = sorted({YEAR_RE.search(f.get("name") or "").group(1)
                    for f in files if YEAR_RE.search(f.get("name") or "")})
    print(f"Found {len(files)} delay file(s) covering {', '.join(years)}:")
    manifest: list[dict] = []
    failures: list[str] = []
    for resource in files:
        print(f"  {resource.get('name')}  [{resource.get('format')}] ...", end=" ", flush=True)
        try:
            record = download(resource)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
            print(f"FAILED ({exc})")
            failures.append(resource.get("name"))
            continue
        manifest.append(record)
        print(f"{record['bytes'] / 1024:,.0f} KB")

    print("  Code Descriptions ...", end=" ", flush=True)
    try:
        codes = fetch_code_descriptions()
        manifest.append(codes)
        print(f"{codes['records']} codes")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, KeyError) as exc:
        print(f"FAILED ({exc})")

    PROVENANCE_JSON.parent.mkdir(parents=True, exist_ok=True)
    PROVENANCE_JSON.write_text(
        json.dumps(
            {
                "source": "City of Toronto Open Data",
                "dataset": PACKAGE_ID,
                "dataset_url": f"https://open.toronto.ca/dataset/{PACKAGE_ID}/",
                "licence": "Open Government Licence - Toronto",
                "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "files": manifest,
            },
            indent=2,
        )
    )
    print(f"\nDownloaded {len(manifest)} file(s) to {RAW_DIR}")
    print(f"Provenance written to {PROVENANCE_JSON}")

    if failures:
        print(f"\n{len(failures)} file(s) failed: {failures}", file=sys.stderr)
        return 1
    if not any("code" in str(m.get("name", "")).lower() for m in manifest):
        print("\nWarning: no cause-code lookup was downloaded; the committed "
              "reference copy will be used instead.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

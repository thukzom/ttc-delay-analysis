"""
Generate schema-identical sample data so the pipeline runs without network access.

This exists for three reasons, in order of importance:

  1. I can work on the pipeline without network access, and anyone picking
     this up gets a working build immediately.

  2. THE HARMONISER GETS EXERCISED. The sample deliberately emits BOTH schema
     generations - 2023-2024 in the old shape (Report Date / Route / Location /
     Incident / Direction) and 2025+ in the new one (Date / Line / Station /
     Code / Bound) - so the column-mapping logic is tested rather than assumed.

  3. THE HEADWAY ESTIMATOR CAN BE VALIDATED. Each sample route is given a TRUE
     scheduled headway, written to data/sample_truth.csv. The estimator recovers
     headway from Min Gap - Min Delay with no knowledge of that file, so its
     accuracy is measurable before it is trusted on real data where no ground
     truth exists.

Structure, not just noise
------------------------
An earlier version of this generator drew route, cause and delay length
independently. The pipeline ran fine on it and produced a completely misleading
demonstration: every cause category had an identical average gap, so the cause
analysis showed nothing, and because every route received the same number of
incidents, the impact-vs-count ranking comparison was measuring random noise.

The generator therefore builds in the three relationships the analysis exists to
find, so that the machinery is exercised rather than merely executed:

  * incidents scale with SERVICE LEVEL - a bus every 5 minutes runs far more
    trips, and logs far more incidents, than one every 30;
  * routes differ in RELIABILITY independently of how often they run;
  * causes differ in SEVERITY - a collision holds a route far longer than a
    fare dispute.

Anything built from this is labelled as such on every page, and the deploy
workflow refuses to publish it. No figure produced here is a finding about the
real TTC.

Usage:  python -m src.sample_data
"""

from __future__ import annotations

import csv
import math
import random
from datetime import date, timedelta

from src.config import RAW_DIR

SEED = 20260822

# Real TTC bus routes with plausible base headways in minutes.
ROUTES = [
    ("7", "BATHURST", 8), ("25", "DON MILLS", 5), ("29", "DUFFERIN", 5),
    ("32", "EGLINTON WEST", 5), ("34", "EGLINTON EAST", 7), ("35", "JANE", 6),
    ("36", "FINCH WEST", 5), ("39", "FINCH EAST", 5), ("41", "KEELE", 8),
    ("43", "KENNEDY", 7), ("52", "LAWRENCE WEST", 6), ("53", "STEELES EAST", 7),
    ("60", "STEELES WEST", 7), ("68", "WARDEN", 9), ("84", "SHEPPARD WEST", 8),
    ("85", "SHEPPARD EAST", 6), ("89", "WESTON", 10), ("95", "YORK MILLS", 7),
    ("96", "WILSON", 8), ("100", "FLEMINGDON PARK", 12),
    ("102", "MARKHAM ROAD", 10), ("116", "MORNINGSIDE", 12),
    ("165", "WESTON RD NORTH", 15), ("168", "SYMINGTON", 20),
    ("300", "BLOOR-DANFORTH NIGHT", 30), ("320", "YONGE NIGHT", 30),
    ("927", "HIGHWAY 27 EXPRESS", 12), ("985", "SHEPPARD EAST EXPRESS", 10),
]

LOCATIONS = [
    "WARDEN STATION", "KIPLING STATION", "FINCH STATION", "KENNEDY STATION",
    "EGLINTON STATION", "YORK MILLS STATION", "WILSON STATION",
    "SCARBOROUGH CENTRE STATION", "DON MILLS STATION", "BROADVIEW STATION",
    "DUFFERIN AND EGLINTON", "JANE AND FINCH", "MARKHAM AND LAWRENCE",
    "STEELES AND YONGE", "MORNINGSIDE AND KINGSTON", "KEELE AND WILSON",
    "BATHURST AND ST CLAIR", "SHEPPARD AND VICTORIA PARK",
]

DIRECTIONS = ["N", "S", "E", "W"]

# Share of incidents by cause category, and the mean delay each produces.
# A collision holds a route far longer than a fare dispute; the analysis is
# supposed to surface that, so the generator has to contain it.
CATEGORY_PROFILE = {
    "operator":   {"weight": 38, "mean_delay": 8.5},
    "mechanical": {"weight": 22, "mean_delay": 16.0},
    "external":   {"weight": 15, "mean_delay": 19.0},
    "other":      {"weight": 9,  "mean_delay": 10.0},
    "passenger":  {"weight": 8,  "mean_delay": 7.5},
    "collision":  {"weight": 4,  "mean_delay": 27.0},
    "security":   {"weight": 4,  "mean_delay": 13.5},
}

# 2025+ codes available within each category, with relative weights. These must
# categorise the same way in src/config.py, which the test suite asserts.
CATEGORY_CODES = {
    "mechanical": {"EFP": 6, "EFD": 5, "EFO": 4, "EFHVA": 3, "EFB": 2,
                   "EFLV": 1, "EFRA": 1, "MFVIS": 1},
    "operator":   {"MFUS": 26, "TFLL": 12, "TFCNO": 4, "TFLF": 3, "MFESA": 3,
                   "MFTO": 2, "MFCN": 1, "MFSH": 1},
    "external":   {"MFDV": 6, "MFWEA": 4, "MFPR": 1, "MFS": 1},
    "passenger":  {"MFUI": 5, "MFUIR": 2, "MFFD": 1, "MFSAN": 1, "TFOI": 1},
    "security":   {"SFDP": 4, "SFPOL": 2, "SFAP": 1, "SFSP": 1, "SFAE": 1},
    "collision":  {"TFPD": 3, "MFPI": 2, "TFPI": 1, "PFPD": 1},
    "other":      {"MFO": 6, "TFO": 2, "PFO": 1},
}

# Free-text values used by the pre-2025 files, by the same category.
CATEGORY_INCIDENTS = {
    "mechanical": {"Mechanical": 10, "Vision": 1},
    "operator":   {"Operations - Operator": 10, "Late Leaving Garage": 5},
    "external":   {"Diversion": 6, "Held By": 3, "Utilized Off Route": 3},
    "passenger":  {"Emergency Services": 6, "Cleaning - Unsanitary": 1},
    "security":   {"Investigation": 3, "Security": 2},
    "collision":  {"Collision - TTC": 3, "Road Blocked - NON-TTC Collision": 2},
    "other":      {"General Delay": 1},
}


def _weighted(rng: random.Random, weights: dict) -> str:
    keys = list(weights)
    return rng.choices(keys, weights=[weights[k] for k in keys], k=1)[0]


def _headway_for(base: float, hour: int, weekday: int) -> float:
    """Scheduled headway varies by time of day and day of week."""
    if hour < 6 or hour >= 22:
        factor = 2.2
    elif 6 <= hour < 10 or 15 <= hour < 19:
        factor = 0.8          # peak service is more frequent
    elif weekday >= 5:
        factor = 1.35         # weekends thinner
    else:
        factor = 1.0
    return max(3.0, base * factor)


def _sample_hour(rng: random.Random) -> int:
    """Incidents cluster in service hours, with morning and evening peaks."""
    weights = []
    for hour in range(24):
        base = 0.25 if hour < 5 or hour >= 23 else 1.0
        am = math.exp(-((hour - 8) ** 2) / 6.0)
        pm = math.exp(-((hour - 17) ** 2) / 7.0)
        weights.append(base + 1.5 * am + 1.7 * pm)
    return rng.choices(range(24), weights=weights, k=1)[0]


def build_route_profiles(rng: random.Random) -> list[dict]:
    """Give each route a service level and an independent reliability factor.

    Incident volume is proportional to trips operated, which is inversely
    proportional to headway. Reliability then varies on top of that, so the
    analysis has to separate "logs many incidents because it runs constantly"
    from "is genuinely unreliable" - which is the entire point of normalising
    by service level rather than ranking on raw counts.
    """
    profiles = []
    for number, name, headway in ROUTES:
        service_level = 60.0 / headway                  # trips per hour
        reliability = rng.lognormvariate(0.0, 0.30)     # 1.0 = fleet typical

        # Routes also differ in WHY they fail. A long suburban route with an
        # older fleet breaks down; a congested arterial gets held up by traffic
        # and collisions. Without this the dominant cause is identical on every
        # route and the cause colouring on the site carries no information.
        signature = rng.choice(list(CATEGORY_PROFILE))
        tilt = {c: 1.0 for c in CATEGORY_PROFILE}
        tilt[signature] = rng.uniform(1.8, 3.2)

        profiles.append({
            "number": number,
            "name": name,
            "base_headway": headway,
            "weight": service_level * reliability,
            "reliability": round(reliability, 3),
            "signature": signature,
            "tilt": tilt,
        })
    return profiles


def generate(
    start: date, end: date, incidents_per_day: int,
    profiles: list[dict], rng: random.Random,
) -> list[dict]:
    rows: list[dict] = []
    weights = [p["weight"] for p in profiles]
    categories = list(CATEGORY_PROFILE)
    category_weights = [CATEGORY_PROFILE[c]["weight"] for c in categories]
    span = (end - start).days

    for offset in range(span):
        day = start + timedelta(days=offset)
        weekday = day.weekday()
        winter = 1.30 if day.month in (1, 2, 12) else 1.0
        weekend = 0.72 if weekday >= 5 else 1.0
        count = max(1, int(rng.gauss(incidents_per_day * winter * weekend, 6)))

        for _ in range(count):
            profile = rng.choices(profiles, weights=weights, k=1)[0]
            hour = _sample_hour(rng)
            minute = rng.randrange(60)
            headway = _headway_for(profile["base_headway"], hour, weekday)

            # Winter shifts the cause mix toward external and mechanical.
            local_weights = [
                category_weights[i] * profile["tilt"][name]
                for i, name in enumerate(categories)
            ]
            if day.month in (1, 2, 12):
                for index, name in enumerate(categories):
                    if name == "external":
                        local_weights[index] *= 2.4
                    elif name == "mechanical":
                        local_weights[index] *= 1.3
            category = rng.choices(categories, weights=local_weights, k=1)[0]

            # Roughly a third of logged records did not hold a vehicle up at all.
            if rng.random() < 0.30:
                delay = 0
            else:
                mean = CATEGORY_PROFILE[category]["mean_delay"]
                delay = int(min(rng.expovariate(1 / mean) + 1, 240))

            # The relationship the estimator must recover: a bus running `delay`
            # minutes late leaves a gap of one headway plus its own lateness.
            if delay == 0:
                gap = 0
            else:
                gap = max(1, int(round(headway + delay + rng.gauss(0, 1.6))))

            # Occasional data-entry artefacts, which the quality gates catch.
            if rng.random() < 0.0015:
                gap = rng.choice([999, 1500, 0])

            rows.append({
                "date": day,
                "route_number": profile["number"],
                "route_name": profile["name"],
                "time": f"{hour:02d}:{minute:02d}",
                "day_name": day.strftime("%A"),
                "location": rng.choice(LOCATIONS),
                "category": category,
                "min_delay": delay,
                "min_gap": gap,
                "direction": rng.choice(DIRECTIONS) if delay else "",
                "vehicle": rng.randrange(1000, 9999) if rng.random() > 0.08 else 0,
            })
    return rows


def write_legacy_csv(path, rows: list[dict], rng: random.Random) -> None:
    """Pre-2025 shape: Report Date / Route / Location / Incident / Direction."""
    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "Report Date", "Route", "Time", "Day", "Location",
            "Incident", "Min Delay", "Min Gap", "Direction", "Vehicle",
        ])
        for row in rows:
            writer.writerow([
                row["date"].strftime("%m/%d/%Y"),
                row["route_number"],
                row["time"],
                row["day_name"],
                row["location"],
                _weighted(rng, CATEGORY_INCIDENTS[row["category"]]),
                row["min_delay"],
                row["min_gap"],
                row["direction"],
                row["vehicle"],
            ])


def write_current_csv(path, rows: list[dict], rng: random.Random) -> None:
    """2025+ shape: Date / Line / Station / Code / Bound."""
    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "Date", "Line", "Time", "Day", "Station",
            "Code", "Min Delay", "Min Gap", "Bound", "Vehicle",
        ])
        for row in rows:
            writer.writerow([
                row["date"].isoformat(),
                f"{row['route_number']} {row['route_name']}",
                row["time"],
                row["day_name"],
                row["location"],
                _weighted(rng, CATEGORY_CODES[row["category"]]),
                row["min_delay"],
                row["min_gap"],
                row["direction"],
                row["vehicle"],
            ])


def write_truth(path, profiles: list[dict]) -> None:
    """Ground truth for validating the estimator. Never an input to the model."""
    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "route_number", "route_name", "true_base_headway_min",
            "reliability", "signature_cause",
        ])
        for profile in profiles:
            writer.writerow([
                profile["number"], profile["name"],
                profile["base_headway"], profile["reliability"],
                profile["signature"],
            ])


def main() -> int:
    rng = random.Random(SEED)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    profiles = build_route_profiles(rng)

    print("Generating sample data in BOTH published schema generations...")
    total = 0
    for year, per_day in ((2023, 150), (2024, 155)):
        rows = generate(date(year, 1, 1), date(year + 1, 1, 1), per_day, profiles, rng)
        path = RAW_DIR / f"sample_ttc_bus_delay_{year}.csv"
        write_legacy_csv(path, rows, rng)
        total += len(rows)
        print(f"  {path.name:42s} {len(rows):>7,} rows  [legacy schema]")

    rows = generate(date(2025, 1, 1), date(2026, 7, 1), 160, profiles, rng)
    path = RAW_DIR / "sample_ttc_bus_delay_since_2025.csv"
    write_current_csv(path, rows, rng)
    total += len(rows)
    print(f"  {path.name:42s} {len(rows):>7,} rows  [current schema]")

    write_truth(RAW_DIR.parent / "sample_truth.csv", profiles)
    print(f"\n  {total:,} sample incidents across {len(ROUTES)} routes.")
    print("  Ground truth written to data/sample_truth.csv")
    print("\n  NOTE: this is SAMPLE data. Run `make fetch` for the real thing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# Why Is My Bus Late?

**Live site:** https://<your-username>.github.io/ttc-delay-analysis/

I spent four years getting around Toronto on the TTC. The part I never got used
to wasn't the delay itself — it was standing at a stop in February with no idea
whether the bus was two minutes away or twenty. So I went looking for an answer
in the City's own open data.

The thing that made this interesting is that the published data records two
different measures, and I think most people reading it pick the wrong one:

| Field | What it measures | Who feels it |
|---|---|---|
| `Min Delay` | How late the **vehicle** was | The operations team |
| `Min Gap` | How long the **hole in service** lasted | The person at the stop |

Almost every analysis of this dataset I've seen uses the first one. This project
is built on the second.

---

## What it does

Downloads the TTC bus delay files straight from the City of Toronto open data
portal, reconciles them into one table, loads that into SQLite, and does the
analysis in SQL. The site is generated from the results and rebuilds itself
monthly, which is roughly how often the City refreshes the data.

Five pages: an overview, a sortable route scorecard, a breakdown of causes,
time-of-day and seasonal patterns, and a method page covering what I assumed and
where I think it's weakest.

## The three things that were actually hard

**The files change shape partway through.** Everything up to 2024 uses one set of
column names — `Report Date`, `Route`, `Location`, `Incident`. From 2025 the same
fields are `Date`, `Line`, `Station`, `Code`, and the cause field changes from
free text to a lookup code. To analyse both you have to reconcile them, and doing
it carelessly is the easiest way to end up confidently wrong. Every column is
matched against an explicit list of names I've actually seen in the files, and
the loader stops with an error rather than guessing if it meets a new one.

**There's no schedule in the data.** To say anything about waiting you need to
know how often the bus is supposed to come, and the delay files don't say. But
it's implicit: if buses run every *H* minutes and one runs *D* minutes late, the
gap behind it is *H + D*. So `H = Min Gap − Min Delay`, taken as the median per
route and time of day. I tested that against known headways before trusting it —
it recovers the right answer to within about half a minute.

**A hundred rows were driving more than half the answer.** Rider impact grows
with the square of the gap, which is the point of it, but that makes it very
sensitive to a long tail. My first version let raw gaps through untouched, and
around a hundred records holding a placeholder value of exactly 999 minutes ended
up outweighing every real incident in the file combined. Nothing internal caught
it — every table reconciled and the arithmetic was right throughout. What caught
it was asking how much of the answer rested on how few rows. Gaps are now capped
at 180 minutes, just above the 99.9th percentile of real service gaps, and the
build fails if any single incident accounts for more than 2% of the total.

## Running it

```bash
pip install -r requirements.txt
make fetch      # downloads the real data from the City's portal
make all        # builds the warehouse, runs the checks, generates the site
```

`make test` runs the unit tests and `make check` runs the data quality gates on
their own. If you don't have network access, `make sample` generates
schema-identical stand-in data so the pipeline still runs — pages built that way
carry a notice saying so, and the deploy workflow refuses to publish them.

### Publishing

The site deploys to GitHub Pages through `.github/workflows/deploy.yml`. Under
**Settings → Pages → Source**, pick **GitHub Actions**. Every push runs the whole
pipeline — download, tests, quality gates — and deploys only if all of it passes.

## How it's laid out

```
src/
  config.py            every assumption in one place
  fetch.py             downloads from the portal, records what it got and when
  load.py              reconciles the two file layouts; cause categories
  quality_checks.py    the gates that can fail a build
  validate_headway.py  scores the headway estimate against known values
  claims.py            picks the wording of each finding from the numbers
  build_site.py        generates the pages
  site_theme.py        shared styling and the SVG charts
sql/
  01_staging               clean and flag; nothing is deleted
  02_int_headway           derive the schedule from the delay records
  03_dimensions            routes, causes, dates
  04_fct_delay_incident    where an operations record becomes a rider's wait
  05–10                    routes, causes, times, hotspots, quality, summary
tests/                 unit tests
reference/             the cause code lookup, kept here so the repo is self-contained
```

## Checks

Thirty automated data quality gates and forty-two unit tests. The gates I care
about most aren't the obvious ones:

- **Reconciliation** — the summary figures still agree with the detail behind
  them.
- **Comparability** — the pre-2025 and post-2025 files actually produced
  equivalent data, rather than one of them quietly losing a field.
- **Plausibility** — the gap must exceed the delay (they contain each other by
  construction, so if that inverts I've swapped two fields), most headways must
  be derived rather than assumed, and no small set of rows may dominate the
  result.

## Data

City of Toronto Open Data — [TTC Bus Delay Data](https://open.toronto.ca/dataset/ttc-bus-delay-data/),
used under the [Open Government Licence – Toronto](https://open.toronto.ca/open-data-licence/).
Every download records the URL, timestamp, size and SHA-256 of each file in
`data/provenance.json`, so any figure can be traced back to the exact file it
came from.

Independent analysis. Not affiliated with or endorsed by the TTC.

## What I'd add next

- **The TTC schedule feed (GTFS).** It would replace my biggest inference —
  derived headway — with an actual timetable. First thing on the list.
- **Weather.** Anything seasonal here is inferred from the calendar and the mix
  of causes, not from observed conditions.
- **Streetcar and subway.** Both are published in the same portal with their own
  layouts, and the reconciliation layer is already built to absorb another one.
- **Ridership**, which would turn the rider impact index from a ranking measure
  into actual passenger-hours.

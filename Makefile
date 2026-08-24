# Why Is My Bus Late? - TTC bus delay analysis

PY := python3

.PHONY: all fetch sample load check test validate site clean rebuild help

help:
	@echo "fetch      download the delay files from the City of Toronto portal"
	@echo "all        load -> quality gates -> validation -> site"
	@echo "load       reconcile the raw files and run the SQL models"
	@echo "check      data quality gates; non-zero exit on failure"
	@echo "test       unit tests"
	@echo "validate   score the headway estimate against known values"
	@echo "site       generate the pages into site/"
	@echo "sample     stand-in data for working without network access"
	@echo "clean      remove generated data and the built site"

all: load check validate site
	@echo ""
	@echo "Done. Open site/index.html"

fetch:
	$(PY) -m src.fetch

sample:
	$(PY) -m src.sample_data

load:
	$(PY) -m src.load

check:
	$(PY) -m src.quality_checks

test:
	$(PY) -m unittest discover -s tests -t . -v

validate:
	$(PY) -m src.validate_headway

site:
	$(PY) -m src.build_site

rebuild: clean sample all

clean:
	rm -rf data site __pycache__ src/__pycache__ tests/__pycache__

# BC Bill 35 short-term-rental analysis
#   make all             live data with automatic fixture/synthetic fallback
#   make all OFFLINE=1   fully offline (fixtures + synthetic panel only)
# Windows without GNU make: `python run.py all` runs the identical steps.

PYTHON ?= python3
ifeq ($(OS),Windows_NT)
  VENV_PY := .venv/Scripts/python.exe
else
  VENV_PY := .venv/bin/python
endif
PY := $(if $(wildcard $(VENV_PY)),$(VENV_PY),$(PYTHON))
export STR_OFFLINE := $(if $(OFFLINE),1,)

.PHONY: install data sql model plots test app app-data site all clean

install:
	$(PYTHON) -m venv .venv
	$(VENV_PY) -m pip install --upgrade pip
	$(VENV_PY) -m pip install -e ".[dev]"

data:
	$(PY) -m src.ingest

sql:
	$(PY) -m src.database

model:
	$(PY) -m src.models
	$(PY) -m src.plots

plots:
	$(PY) -m src.plots

test:
	$(PY) -m pytest

app:
	$(PY) -m streamlit run app/app.py

# Refresh the small committed database the dashboard reads (run after `make all`).
app-data:
	$(PY) -m src.database --export-app

# Re-export the static dashboard's data (docs/, served by GitHub Pages) from data/app/.
site:
	$(PY) scripts/export_dashboard.py

all: data sql model test

clean:
	rm -f data/str_analysis.duckdb data/processed/*.parquet data/processed/*.json data/processed/*.csv assets/*.png

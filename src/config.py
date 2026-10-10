"""Central configuration: paths, markets, policy calendar, and data-source endpoints.

Everything that encodes a research-design decision lives here so it is reviewable
in one place (and so the SQL, models, plots, app, and tests agree on it).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
FIXTURES = DATA / "fixtures"
QUERIES = ROOT / "queries"
ASSETS = ROOT / "assets"
DB_PATH = DATA / "str_analysis.duckdb"
RESULTS_PATH = PROCESSED / "model_results.json"
MANIFEST_PATH = RAW / "manifest.json"
SYNTHETIC_PARQUET = PROCESSED / "synthetic_listings.parquet"

# Committed snapshot the dashboard's data are exported from (the full database is ~110 MB and
# depends on gitignored raw downloads). Refresh with `make app-data`.
APP_DATA = DATA / "app"
APP_DB_PATH = APP_DATA / "str_app.duckdb"
APP_RESULTS_PATH = APP_DATA / "model_results.json"
APP_TABLES = ["str_rent_panel", "str_nbhd_panel", "snapshot_months"]

SEED = 20240501  # Phase-1 enforcement date; fixes every random draw in the repo.

# --------------------------------------------------------------------------- panel
PANEL_START = date(2022, 1, 1)
PANEL_END = date(2026, 6, 1)  # inclusive month

# --------------------------------------------------------------------------- policy
ANNOUNCE_MONTH = date(2023, 10, 1)   # Bill 35 introduced 16 Oct 2023, Royal Assent 26 Oct 2023
PHASE1_MONTH = date(2024, 5, 1)      # principal-residence requirement in force
PHASE2_MONTH = date(2025, 5, 1)      # provincial registry opens (platform validation from 1 Jun 2025)
EVENT_MIN, EVENT_MAX = -12, 24       # event-study window, months relative to PHASE1_MONTH
# Last clean pre-period month. Normalising to t=-1 (Apr 2024) would bake six months of
# anticipation (Oct 2023 - Apr 2024) into the reference and understate the effect.
EVENT_REF = -8                       # Sep 2023


@dataclass(frozen=True)
class Market:
    key: str
    label: str
    province: str
    iab_path: str          # path segment on data.insideairbnb.com
    cpi_geo_member: int | None  # StatCan 18-10-0004-01 geography member id
    treated: bool          # subject to BC Bill 35


MARKETS: dict[str, Market] = {
    "vancouver": Market("vancouver", "Vancouver", "BC", "canada/bc/vancouver", 27, True),
    "victoria": Market("victoria", "Victoria (CRD)", "BC", "canada/bc/victoria", 28, True),
    "ottawa": Market("ottawa", "Ottawa", "ON", "canada/on/ottawa", 15, False),
    "seattle": Market("seattle", "Seattle", "WA", "united-states/wa/seattle", None, False),
}
BC_MARKETS = [k for k, m in MARKETS.items() if m.treated]
# Montreal is deliberately absent: Quebec's post-March-2023 crackdown (Bill 25
# enforcement, platform registration-number requirement from Sept 2023) is a
# contemporaneous treatment, so it cannot serve as an untreated control.

# Inside Airbnb's "Victoria" file covers the whole Capital Regional District.
# Bill 35's principal-residence requirement (PRR) exempts most regional-district
# electoral areas and Islands Trust areas, and municipalities under 10,000 people
# only if they are NOT within 15 km of a larger municipality. So Metchosin and
# Highlands (small, but next to Langford/Saanich) are covered from May 2024 and are
# deliberately absent here. Exempt areas are still subject to the Phase-2 registry.
# Value = first month the PRR applies after an opt-in (None = exempt throughout).
# Source: gov.bc.ca "principal residence requirement" community list; Salt Spring
# Local Trust Committee opt-in effective 1 Nov 2025 (Gulf Islands Driftwood, Mar 2025).
PR_EXEMPT_NEIGHBOURHOODS: dict[tuple[str, str], date | None] = {
    ("victoria", "Juan de Fuca"): None,                      # CRD electoral area
    ("victoria", "Southern Gulf Islands"): None,             # Islands Trust area
    ("victoria", "Salt Spring Island"): date(2025, 11, 1),   # Islands Trust; opted in
}

# --------------------------------------------------------------------------- sources
IAB_INDEX_URL = "https://insideairbnb.com/get-the-data/"
# Gatsby static-query payload behind the page; lists every *published* snapshot
# (Inside Airbnb only publishes the trailing ~12 months).
IAB_STATIC_QUERY_URL = "https://insideairbnb.com/page-data/sq/d/3176684073.json"
IAB_DATA_ROOT = "https://data.insideairbnb.com"

STATCAN_WDS = "https://www150.statcan.gc.ca/t1/wds/rest"
CPI_PRODUCT_ID = 18100004
CPI_PRODUCTS = {80: "rented_accommodation", 81: "rent", 2: "all_items"}

BOC_POLICY_RATE_URL = "https://www.bankofcanada.ca/valet/observations/V39079/json"

HTTP_TIMEOUT = 60
USER_AGENT = "bc-str-ban-analysis/1.0 (academic policy research)"

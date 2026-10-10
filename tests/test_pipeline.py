"""Pipeline assertions and econometric validation.

Run after `make model` (the `built` fixture builds the database offline if it is missing).
"""
from __future__ import annotations

import hashlib
import json
import math

import duckdb
import numpy as np
import pandas as pd
import pytest

from src import config as cfg
from src import database as db
from src import ingest, synthetic

PANEL_MONTHS = (cfg.PANEL_END.year - cfg.PANEL_START.year) * 12 + cfg.PANEL_END.month - cfg.PANEL_START.month + 1

PRIMARY_KEYS = {
    "listings_clean": ["data_source", "city", "snapshot_date", "listing_id"],
    "monthly_nbhd": ["data_source", "city", "neighbourhood", "room_type", "year_month"],
    "monthly_city": ["data_source", "city", "room_type", "year_month"],
    "str_rent_panel": ["data_source", "city", "room_type", "year_month"],
    "str_nbhd_panel": ["data_source", "city", "neighbourhood", "room_type", "year_month"],
}


@pytest.fixture(scope="session")
def built():
    if not cfg.DB_PATH.exists():
        ingest.run(offline=True)
        db.build()
    if not cfg.RESULTS_PATH.exists():
        from src import models
        models.run_all()
    return db.connect(read_only=True)


@pytest.fixture(scope="session")
def results(built):
    return json.loads(cfg.RESULTS_PATH.read_text())


def _result(results, spec, source):
    return next((r for r in results["results"] if r["spec"] == spec and r["data_source"] == source), None)


# =========================================================================== SQL unit test
def test_clean_listings_sql_edge_cases():
    """Run 01_clean_listings.sql against hand-written edge cases in an in-memory DB."""
    con = duckdb.connect()
    con.execute("SET VARIABLE active_window_days = 180")
    sample = pd.read_csv(cfg.FIXTURES / "listings_sample.csv", dtype=str, keep_default_na=False)
    raw = sample.drop(columns="expect_note").assign(data_source="test")
    con.register("raw_df", raw)
    con.execute("CREATE TABLE raw_listings AS SELECT * FROM raw_df")
    con.execute("CREATE TABLE ref_pr_exempt AS SELECT 'victoria' AS city, 'Juan de Fuca' AS neighbourhood")
    con.execute((cfg.QUERIES / "01_clean_listings.sql").read_text())
    out = con.execute("SELECT * FROM listings_clean ORDER BY listing_id").df().set_index("listing_id")

    assert len(out) == 6, "missing-id row and the duplicate scrape must be dropped"
    assert out.loc["101", "price"] == 1234.0, "comma-formatted price, latest scrape wins"
    assert bool(out.loc["101", "is_commercial_host"]) and bool(out.loc["101", "has_provincial_registration"])
    assert not out.loc["102", "is_active"], "dormant listing"
    assert bool(out.loc["103", "is_active"]) and bool(out.loc["103", "pr_exempt"]) and pd.isna(out.loc["103", "price"])
    assert out.loc["104", "room_type"] == "other"
    assert pd.isna(out.loc["105", "price"]) and not out.loc["105", "has_licence"]
    assert bool(out.loc["201", "is_active"]) and bool(out.loc["201", "reviewed_180d"])


# =========================================================================== keys & continuity
@pytest.mark.parametrize("table", list(PRIMARY_KEYS))
def test_primary_keys_not_null_and_unique(built, table):
    keys = PRIMARY_KEYS[table]
    nulls = built.execute(
        f"SELECT count(*) FROM {table} WHERE " + " OR ".join(f"{k} IS NULL" for k in keys)).fetchone()[0]
    assert nulls == 0, f"{table}: NULL primary-key values"
    dups = built.execute(
        f"SELECT count(*) FROM (SELECT {', '.join(keys)} FROM {table} GROUP BY ALL HAVING count(*) > 1)").fetchone()[0]
    assert dups == 0, f"{table}: duplicate primary keys"


@pytest.mark.parametrize("table,unit", [
    ("str_rent_panel", "data_source, city, room_type"),
    ("str_nbhd_panel", "data_source, city, neighbourhood, room_type"),
])
def test_panel_month_continuity(built, table, unit):
    df = built.execute(f"""
        SELECT {unit}, count(*) n, min(year_month) lo, max(year_month) hi,
               max(gap) max_gap
        FROM (SELECT *, datediff('month', lag(year_month) OVER (PARTITION BY {unit} ORDER BY year_month),
                                 year_month) AS gap FROM {table})
        GROUP BY ALL""").df()
    assert (df["n"] == PANEL_MONTHS).all(), "every unit must have every month"
    assert (pd.to_datetime(df["lo"]) == pd.Timestamp(cfg.PANEL_START)).all()
    assert (pd.to_datetime(df["hi"]) == pd.Timestamp(cfg.PANEL_END)).all()
    assert (df["max_gap"] == 1).all(), "no missing monthly buckets"


def test_synthetic_panel_fully_observed(built):
    unobs = built.execute(
        "SELECT count(*) FROM str_rent_panel WHERE data_source = 'synthetic' AND NOT is_observed").fetchone()[0]
    assert unobs == 0


def test_dedup_removed_raw_duplicates(built):
    raw = built.execute("SELECT count(*) FROM raw_listings_synthetic").fetchone()[0]
    clean = built.execute("SELECT count(*) FROM listings_clean WHERE data_source = 'synthetic'").fetchone()[0]
    assert raw > clean, "synthetic data contains injected duplicates that must be removed"


def test_policy_flags_consistent(built):
    bad = built.execute("""
        SELECT count(*) FROM str_rent_panel
        WHERE (post_phase2 AND NOT post_phase1) OR (anticipation AND post_phase1)
           OR (year_month = DATE '2024-05-01' AND event_time <> 0)""").fetchone()[0]
    assert bad == 0


def test_cpi_join_coverage(built):
    """Canadian markets must have CPI rent for every panel month; Seattle must not."""
    df = built.execute("""
        SELECT city, count(*) FILTER (WHERE cpi_rent IS NULL) AS missing FROM str_rent_panel
        WHERE year_month <= DATE '2026-06-01' GROUP BY city""").df().set_index("city")
    for c in ["vancouver", "victoria", "ottawa"]:
        assert df.loc[c, "missing"] == 0, c
    assert df.loc["seattle", "missing"] > 0


# =========================================================================== offline guarantee
def test_offline_discovery_uses_fixture_list():
    snaps = ingest.discover_snapshots(None, offline=True)
    known = json.loads((cfg.FIXTURES / "known_archive_snapshots.json").read_text())["snapshots"]
    for city, dates in known.items():
        assert set(d for d in dates if d <= "2026-06-30") <= set(snaps[city])


def test_fixtures_present_for_offline_run():
    for f in ["cpi_18100004.csv", "boc_policy_rate_monthly.csv", "cmhc_rms_benchmarks.csv",
              "calibration_anchors.json", "dgp_parameters.json", "known_archive_snapshots.json"]:
        assert (cfg.FIXTURES / f).exists(), f


def test_synthetic_generation_is_deterministic(tmp_path):
    p = tmp_path / "a.parquet"
    synthetic.generate(p)
    q = "SELECT city, room_type, count(*) n, sum(hash(id)) h FROM '{}' GROUP BY ALL ORDER BY ALL"
    a = duckdb.sql(q.format(p.as_posix())).df()
    b = duckdb.sql(q.format(cfg.SYNTHETIC_PARQUET.as_posix())).df()
    pd.testing.assert_frame_equal(a, b)
    assert hashlib.md5(a.to_csv().encode()).hexdigest() == hashlib.md5(b.to_csv().encode()).hexdigest()


# =========================================================================== models
def test_models_yield_non_null_coefficients(results):
    assert results["results"], "no models were estimated"
    for r in results["results"]:
        assert r["nobs"] > 0
        assert r["coefs"], r["label"]
        for c in r["coefs"]:
            assert c["estimate"] is not None and math.isfinite(c["estimate"]), (r["label"], c["term"])
            assert c["se"] is not None and c["se"] > 0, (r["label"], c["term"])
        if r["spec"] != "S1-ppml":
            assert r["r2"] is not None and 0 <= r["r2"] <= 1


def test_primary_did_present_for_each_source(results):
    for src in {r["data_source"] for r in results["results"]}:
        r = _result(results, "S1", src)
        assert r is not None and {c["term"] for c in r["coefs"]} == {"ent_antic", "ent_p1", "ent_p2"}
        assert r["n_clusters"] >= 30, "inference must use neighbourhood clusters, not 4 city x room cells"


@pytest.mark.parametrize("spec,terms", [("S1", ["ent_p1", "ent_p2"]), ("S2a", ["ent_p1", "ent_p2"]),
                                        ("S1-ppml", ["ent_p1"])])
def test_synthetic_parameter_recovery(results, spec, terms):
    """Estimates on the synthetic panel must cover the known DGP estimand."""
    r = _result(results, spec, "synthetic")
    for t in terms:
        c = next(x for x in r["coefs"] if x["term"] == t)
        assert c["truth"] is not None
        assert abs(c["estimate"] - c["truth"]) < 3 * c["se"], (spec, t, c)


def test_cross_market_recovery(results):
    r = next(x for x in results["results"] if x["spec"] == "S4b" and x["data_source"] == "synthetic"
             and "Ottawa+Seattle" in x["label"])
    c = next(x for x in r["coefs"] if x["term"] == "ent_p1")
    assert abs(c["estimate"] - c["truth"]) < 3 * c["se"]


def test_event_study_window_and_pretrends(results):
    r = _result(results, "S3", "synthetic")
    ks = sorted(c["event_time"] for c in r["coefs"])
    assert ks[0] == cfg.EVENT_MIN and ks[-1] == cfg.EVENT_MAX
    assert cfg.EVENT_REF not in ks, "reference period must be omitted"
    assert len(ks) == cfg.EVENT_MAX - cfg.EVENT_MIN, "one coefficient per non-reference month"
    pt = r["extra"]["pretrend_test"]
    assert pt["p"] is not None and pt["p"] > 0.01, "parallel pre-trends hold by construction in the DGP"
    post = [c for c in r["coefs"] if c["event_time"] >= 3]
    assert np.mean([c["estimate"] for c in post]) < 0, "post-period delisting must be negative"


def test_rent_models_run(results):
    rf = results["rent"]["rent_reduced_form"]
    assert rf["nobs"] > 100 and all(math.isfinite(c["estimate"]) for c in rf["coefs"])

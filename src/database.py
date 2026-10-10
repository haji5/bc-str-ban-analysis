"""DuckDB initialisation and SQL execution engine.

Raw sources are exposed as views; the transformation logic lives entirely in the
pure-SQL files under ``queries/`` which are executed in lexical order. Research-design
constants (panel bounds, policy dates) are injected as DuckDB session variables so
the SQL reads them with ``getvariable('...')`` instead of hard-coding them.
"""
from __future__ import annotations

import argparse
import logging
import shutil
from pathlib import Path

import duckdb
import pandas as pd

from src import config as C

log = logging.getLogger("database")

IAB_GLOB = (C.RAW / "insideairbnb" / "*" / "*" / "listings.csv.gz").as_posix()
LISTING_COLS = [
    "id", "last_scraped", "host_id", "neighbourhood_cleansed", "room_type", "price",
    "availability_365", "number_of_reviews", "number_of_reviews_ltm", "first_review",
    "last_review", "license", "calculated_host_listings_count", "latitude", "longitude",
]


def connect(path: Path | None = None, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    # Resolved at call time so the dashboard can point C.DB_PATH at the committed bundle.
    path = path or C.DB_PATH
    if not read_only:
        path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path), read_only=read_only)


def _set_variables(con: duckdb.DuckDBPyConnection) -> None:
    for name, val in {
        "panel_start": C.PANEL_START, "panel_end": C.PANEL_END,
        "announce_month": C.ANNOUNCE_MONTH, "phase1_month": C.PHASE1_MONTH,
        "phase2_month": C.PHASE2_MONTH,
    }.items():
        con.execute(f"SET VARIABLE {name} = DATE '{val.isoformat()}'")
    con.execute(f"SET VARIABLE active_window_days = {180}")


def register_sources(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Create raw_* views/tables. Missing live files -> empty, schema-compatible view."""
    cols = ", ".join(f"CAST({c} AS VARCHAR) AS {c}" for c in LISTING_COLS)
    has_live = any((C.RAW / "insideairbnb").glob("*/*/listings.csv.gz"))
    if has_live:
        con.execute(f"""
            CREATE OR REPLACE TABLE raw_listings_live AS
            SELECT 'live' AS data_source,
                   regexp_extract(path, 'insideairbnb/([a-z]+)/(\\d{{4}}-\\d{{2}}-\\d{{2}})', 1) AS city,
                   regexp_extract(path, 'insideairbnb/([a-z]+)/(\\d{{4}}-\\d{{2}}-\\d{{2}})', 2) AS snapshot_date,
                   {cols}
            FROM (SELECT *, replace(filename, chr(92), '/') AS path FROM read_csv('{IAB_GLOB}', all_varchar = true, union_by_name = true,
                          filename = true, header = true, quote = '"', escape = '"',
                          strict_mode = false, max_line_size = 10000000))
        """)
    else:
        log.warning("no live Inside Airbnb files found; live panel will be empty")
        con.execute(f"""
            CREATE OR REPLACE TABLE raw_listings_live AS
            SELECT 'live' AS data_source, NULL::VARCHAR AS city, NULL::VARCHAR AS snapshot_date,
                   {', '.join(f'NULL::VARCHAR AS {c}' for c in LISTING_COLS)}
            WHERE false
        """)
    if C.SYNTHETIC_PARQUET.exists():
        con.execute(f"""
            CREATE OR REPLACE VIEW raw_listings_synthetic AS
            SELECT 'synthetic' AS data_source, city, snapshot_date, {cols}
            FROM read_parquet('{C.SYNTHETIC_PARQUET.as_posix()}')
        """)
    else:
        raise FileNotFoundError(f"{C.SYNTHETIC_PARQUET} missing - run `make data` first")
    con.execute("""
        CREATE OR REPLACE VIEW raw_listings AS
        SELECT * FROM raw_listings_live UNION ALL BY NAME SELECT * FROM raw_listings_synthetic
    """)

    exempt = pd.DataFrame(sorted(C.PR_EXEMPT_NEIGHBOURHOODS), columns=["city", "neighbourhood"])
    con.register("exempt_df", exempt)
    con.execute("CREATE OR REPLACE TABLE ref_pr_exempt AS SELECT * FROM exempt_df")
    markets = pd.DataFrame([{"city": k, "province": m.province, "treated_market": m.treated}
                            for k, m in C.MARKETS.items()])
    con.register("markets_df", markets)
    con.execute("CREATE OR REPLACE TABLE ref_markets AS SELECT * FROM markets_df")

    raw = {
        "ref_cpi": C.RAW / "statcan" / "cpi_18100004.csv",
        "ref_boc": C.RAW / "boc" / "policy_rate_monthly.csv",
        "ref_cmhc": C.RAW / "cmhc" / "cmhc_rms.csv",
    }
    fallback = {
        "ref_cpi": C.FIXTURES / "cpi_18100004.csv",
        "ref_boc": C.FIXTURES / "boc_policy_rate_monthly.csv",
        "ref_cmhc": C.FIXTURES / "cmhc_rms_benchmarks.csv",
    }
    for tbl, p in raw.items():
        src = p if p.exists() else fallback[tbl]
        con.execute(f"CREATE OR REPLACE TABLE {tbl} AS SELECT * FROM read_csv_auto('{src.as_posix()}', header = true)")
    return {
        t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        for t in ["raw_listings_live", "raw_listings_synthetic", "ref_cpi", "ref_boc", "ref_cmhc"]
    }


def run_sql_files(con: duckdb.DuckDBPyConnection, directory: Path = C.QUERIES) -> list[str]:
    ran = []
    for f in sorted(directory.glob("*.sql")):
        log.info("executing %s", f.name)
        con.execute(f.read_text(encoding="utf-8"))
        ran.append(f.name)
    return ran


def build(path: Path = C.DB_PATH) -> dict:
    con = connect(path)
    try:
        _set_variables(con)
        counts = register_sources(con)
        ran = run_sql_files(con)
        for t in ["listings_clean", "monthly_nbhd", "monthly_city", "str_rent_panel", "str_nbhd_panel"]:
            counts[t] = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        return {"sql_files": ran, "row_counts": counts}
    finally:
        con.close()


def query(sql: str, path: Path | None = None) -> pd.DataFrame:
    con = connect(path, read_only=True)
    try:
        return con.execute(sql).df()
    finally:
        con.close()


def export_app_bundle(src: Path | None = None, dest: Path = C.APP_DB_PATH,
                      results: Path = C.RESULTS_PATH) -> dict[str, int]:
    """Copy the tables the dashboard reads into a small, committable database.

    Written in the DuckDB v1.0 storage format so any duckdb >= 1.0 (whatever the
    deployment host resolves) can open it. Rows are sorted so an unchanged rebuild
    produces the same content.
    """
    src = src or C.DB_PATH
    if not (src.exists() and results.exists()):
        raise FileNotFoundError("full database or model results missing - run `make all` first")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    con = duckdb.connect()
    try:
        con.execute(f"ATTACH '{src.as_posix()}' AS full_db (READ_ONLY)")
        con.execute(f"ATTACH '{tmp.as_posix()}' AS app_db (STORAGE_VERSION 'v1.0.0')")
        counts = {}
        for t in C.APP_TABLES:
            con.execute(f"CREATE TABLE app_db.{t} AS SELECT * FROM full_db.{t} ORDER BY ALL")
            counts[t] = con.execute(f"SELECT count(*) FROM app_db.{t}").fetchone()[0]
        con.execute("DETACH app_db")
    finally:
        con.close()
    tmp.replace(dest)
    shutil.copyfile(results, C.APP_RESULTS_PATH)
    return counts


def main() -> None:
    p = argparse.ArgumentParser(description="Build the DuckDB analysis database")
    p.add_argument("--export-app", action="store_true",
                   help="instead of building, export the dashboard bundle to data/app/")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if a.export_app:
        for k, v in export_app_bundle().items():
            print(f"{k:28s} {v:>12,}")
        print(f"bundle: {C.APP_DB_PATH.relative_to(C.ROOT)} ({C.APP_DB_PATH.stat().st_size / 1e6:.1f} MB)")
        return
    out = build()
    for k, v in out["row_counts"].items():
        print(f"{k:28s} {v:>12,}")


if __name__ == "__main__":
    main()

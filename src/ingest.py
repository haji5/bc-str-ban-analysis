"""Data ingestion with a hard offline guarantee.

Sources
-------
1. Inside Airbnb ``listings.csv.gz`` snapshots (never ``calendar.csv.gz``).
   * Published snapshots are discovered from the get-the-data page's static-query
     payload (only the trailing ~12 months are published).
   * Older snapshots still exist on the CDN but are unlisted; the ones we have
     verified are kept in ``data/fixtures/known_archive_snapshots.json``
     (extend it with ``--probe-archive`` or by dropping files obtained through an
     Inside Airbnb data request into ``data/raw/insideairbnb/<city>/<YYYY-MM-DD>/``).
2. StatCan CPI, Table 18-10-0004-01 (Rented accommodation / Rent / All-items) via WDS.
3. Bank of Canada target overnight rate (macro confounder) via Valet.
4. CMHC Rental Market Survey benchmarks (no stable API): a user drop-in at
   ``data/raw/cmhc/cmhc_rms.csv`` overrides the curated fixture.

Every network call is wrapped: on any failure (timeout, 403/404, rate-limit) the
cached fixture is used, and a calibrated synthetic listing panel is always built
so ``make all`` runs end-to-end with no network at all. ``data/raw/manifest.json``
records exactly which path each source took.
"""
from __future__ import annotations

import argparse
import gzip
import json
import logging
import shutil
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

from src import config as C

log = logging.getLogger("ingest")

IAB_RAW = C.RAW / "insideairbnb"
KNOWN_SNAPSHOTS = C.FIXTURES / "known_archive_snapshots.json"
CPI_RAW = C.RAW / "statcan" / "cpi_18100004.csv"
BOC_RAW = C.RAW / "boc" / "policy_rate_monthly.csv"
CMHC_RAW = C.RAW / "cmhc" / "cmhc_rms.csv"
CPI_FIXTURE = C.FIXTURES / "cpi_18100004.csv"
BOC_FIXTURE = C.FIXTURES / "boc_policy_rate_monthly.csv"
CMHC_FIXTURE = C.FIXTURES / "cmhc_rms_benchmarks.csv"
ANCHORS_FIXTURE = C.FIXTURES / "calibration_anchors.json"

# Columns kept from Inside Airbnb files (the full file has ~80; we need ~15).
IAB_COLUMNS = [
    "id", "last_scraped", "host_id", "neighbourhood_cleansed", "room_type", "price",
    "availability_365", "number_of_reviews", "number_of_reviews_ltm", "first_review",
    "last_review", "license", "calculated_host_listings_count", "latitude", "longitude",
]


# =========================================================================== HTTP
def _session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = C.USER_AGENT
    return s


def _get(session: requests.Session, url: str, *, retries: int = 3, **kw) -> requests.Response:
    """GET with exponential backoff on 429/5xx; raises on final failure."""
    for attempt in range(retries):
        try:
            r = session.get(url, timeout=C.HTTP_TIMEOUT, **kw)
            if r.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"HTTP {r.status_code}", response=r)
            r.raise_for_status()
            return r
        except requests.RequestException as exc:
            if attempt == retries - 1 or (
                isinstance(exc, requests.HTTPError)
                and exc.response is not None
                and exc.response.status_code in (403, 404)
            ):
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("unreachable")


# =========================================================================== Inside Airbnb
def discover_snapshots(session: requests.Session | None, offline: bool) -> dict[str, list[str]]:
    """Return {city: sorted snapshot dates} from published + known-archive lists."""
    known = json.loads(KNOWN_SNAPSHOTS.read_text())["snapshots"]
    found: dict[str, set[str]] = {k: set(v) for k, v in known.items()}
    if not offline and session is not None:
        try:
            payload = _get(session, C.IAB_STATIC_QUERY_URL).json()
            for ds in payload["data"]["allData"]["datasets"]:
                for key, m in C.MARKETS.items():
                    if ds["dataRoot"].rstrip("/").endswith(m.iab_path):
                        found[key].add(ds["publishDate"])
        except Exception as exc:  # noqa: BLE001 - any failure -> known list only
            log.warning("Snapshot discovery failed (%s); using known archive list only", exc)
    # Manual drop-ins from an Inside Airbnb data request.
    for key in C.MARKETS:
        city_dir = IAB_RAW / key
        if city_dir.exists():
            found[key].update(p.name for p in city_dir.iterdir() if (p / "listings.csv.gz").exists())
    end = (C.PANEL_END.replace(day=28) + timedelta(days=4)).replace(day=1)  # first day after panel
    return {
        k: sorted(d for d in v if C.PANEL_START.isoformat() <= d < end.isoformat())
        for k, v in found.items()
    }


def download_listings(session, snapshots: dict[str, list[str]], offline: bool) -> dict:
    """Download each listings.csv.gz once; returns per-city status."""
    status: dict[str, dict] = {}
    for key, dates in snapshots.items():
        m = C.MARKETS[key]
        ok, failed = [], []
        for d in dates:
            dest = IAB_RAW / key / d / "listings.csv.gz"
            if dest.exists() and dest.stat().st_size > 0:
                ok.append(d)
                continue
            if offline:
                failed.append(d)
                continue
            url = f"{C.IAB_DATA_ROOT}/{m.iab_path}/{d}/data/listings.csv.gz"
            try:
                r = _get(session, url)
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = dest.with_suffix(".part")
                tmp.write_bytes(r.content)
                tmp.replace(dest)
                ok.append(d)
                log.info("downloaded %s %s (%.1f MB)", key, d, len(r.content) / 1e6)
                time.sleep(0.5)  # be polite to a volunteer-run CDN
            except Exception as exc:  # noqa: BLE001
                log.warning("listings %s %s unavailable: %s", key, d, exc)
                failed.append(d)
        status[key] = {"available": ok, "failed": failed}
    return status


def probe_archive(session, cities: list[str], span_days: int = 12) -> dict[str, list[str]]:
    """Bounded HEAD probe for unlisted quarterly snapshots (opt-in; ~25 requests/quarter/city)."""
    hits: dict[str, list[str]] = {c: [] for c in cities}
    mids = pd.date_range("2022-02-15", C.PANEL_END.isoformat(), freq="3MS") + pd.Timedelta(days=14)
    for city in cities:
        m = C.MARKETS[city]
        for mid in mids:
            for off in range(-span_days, span_days + 1):
                d = (mid + pd.Timedelta(days=off)).date().isoformat()
                url = f"{C.IAB_DATA_ROOT}/{m.iab_path}/{d}/data/listings.csv.gz"
                try:
                    if session.head(url, timeout=10).status_code == 200:
                        hits[city].append(d)
                except requests.RequestException:
                    pass
                time.sleep(0.15)
    return hits


def read_listing_snapshot(path: Path) -> pd.DataFrame:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        df = pd.read_csv(fh, usecols=lambda c: c in IAB_COLUMNS, dtype=str, keep_default_na=False)
    return df


def compute_anchors(snapshots: dict[str, list[str]]) -> dict:
    """Aggregate real snapshots into calibration anchors for the synthetic generator.

    Only aggregates are stored in the repo (no listing microdata), so fixtures stay
    small and contain no host-level information.
    """
    anchors: dict = {"generated": date.today().isoformat(), "cities": {}}
    for key, dates in snapshots.items():
        city: dict = {"snapshots": {}}
        for d in dates:
            p = IAB_RAW / key / d / "listings.csv.gz"
            if not p.exists():
                continue
            df = read_listing_snapshot(p).drop_duplicates("id")
            snap = pd.Timestamp(d)
            lr = pd.to_datetime(df["last_review"], errors="coerce")
            avail = pd.to_numeric(df["availability_365"], errors="coerce").fillna(0)
            df["active"] = ((snap - lr).dt.days <= 180) | (avail > 0)
            df["rt"] = df["room_type"].map(
                {"Entire home/apt": "entire_home", "Private room": "private_room"}
            ).fillna("other")
            price = pd.to_numeric(df["price"].str.replace(r"[$,]", "", regex=True), errors="coerce")
            df["price"] = price
            cells = (
                df.groupby(["neighbourhood_cleansed", "rt"])
                .agg(n=("id", "size"), n_active=("active", "sum"))
                .reset_index()
            )
            city["snapshots"][d] = {
                "cells": [
                    [r.neighbourhood_cleansed, r.rt, int(r.n), int(r.n_active)]
                    for r in cells.itertuples()
                ],
                "median_price": {
                    rt: float(g["price"].median()) for rt, g in df.groupby("rt") if g["price"].notna().any()
                },
                "mean_availability_365": {rt: float(pd.to_numeric(g["availability_365"], errors="coerce").mean())
                                          for rt, g in df.groupby("rt")},
                "share_commercial_host": {
                    rt: float((pd.to_numeric(g["calculated_host_listings_count"], errors="coerce") > 1).mean())
                    for rt, g in df.groupby("rt")
                },
            }
        anchors["cities"][key] = city
    return anchors


# =========================================================================== StatCan CPI
def fetch_cpi(session) -> pd.DataFrame:
    coords = [
        (geo, prod)
        for geo in [m.cpi_geo_member for m in C.MARKETS.values() if m.cpi_geo_member] + [26, 2]
        for prod in C.CPI_PRODUCTS
    ]
    body = [{"productId": C.CPI_PRODUCT_ID, "coordinate": f"{g}.{p}.0.0.0.0.0.0.0.0"} for g, p in coords]
    r = session.post(f"{C.STATCAN_WDS}/getSeriesInfoFromCubePidCoord", json=body, timeout=C.HTTP_TIMEOUT)
    r.raise_for_status()
    # WDS does not return items in request order: key everything on the response's own
    # coordinate, never on position.
    meta = {}
    for item in r.json():
        if item.get("status") != "SUCCESS":
            continue
        obj = item["object"]
        g, p = (int(x) for x in obj["coordinate"].split(".")[:2])
        meta[obj["vectorId"]] = (g, p, obj["SeriesTitleEn"])
    vec = ",".join(f'"{v}"' for v in meta)
    r = _get(
        session,
        f"{C.STATCAN_WDS}/getDataFromVectorByReferencePeriodRange",
        params={"vectorIds": vec, "startRefPeriod": "2019-01-01", "endReferencePeriod": "2026-12-01"},
    )
    geo_key = {m.cpi_geo_member: k for k, m in C.MARKETS.items() if m.cpi_geo_member}
    geo_key.update({26: "bc", 2: "canada"})
    rows = []
    for item in r.json():
        obj = item["object"]
        g, p, title = meta[obj["vectorId"]]
        for dp in obj["vectorDataPoint"]:
            rows.append({
                "geo": geo_key[g], "product": C.CPI_PRODUCTS[p], "vector_id": obj["vectorId"],
                "ref_month": dp["refPer"], "value": dp["value"], "series_title": title,
            })
    df = pd.DataFrame(rows)
    if df.empty:
        raise ValueError("StatCan returned no CPI datapoints")
    return df


# =========================================================================== Bank of Canada
def fetch_boc(session) -> pd.DataFrame:
    r = _get(session, C.BOC_POLICY_RATE_URL, params={"start_date": "2019-01-01"})
    obs = pd.DataFrame(
        [{"d": o["d"], "v": float(o["V39079"]["v"])} for o in r.json()["observations"] if o.get("V39079")]
    )
    obs["ref_month"] = pd.to_datetime(obs["d"]).dt.to_period("M").dt.to_timestamp().dt.date.astype(str)
    return obs.groupby("ref_month", as_index=False)["v"].mean().rename(columns={"v": "policy_rate"})


# =========================================================================== orchestration
def _with_fallback(name: str, fetch, raw: Path, fixture: Path, offline: bool, manifest: dict, session):
    if not offline:
        try:
            df = fetch(session)
            raw.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(raw, index=False)
            manifest[name] = {"status": "live", "rows": len(df), "path": str(raw.relative_to(C.ROOT))}
            return df
        except Exception as exc:  # noqa: BLE001
            log.warning("%s fetch failed (%s); falling back to fixture", name, exc)
    raw.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(fixture, raw)
    df = pd.read_csv(raw)
    manifest[name] = {"status": "fixture", "rows": len(df), "path": str(fixture.relative_to(C.ROOT))}
    return df


def live_coverage(status: dict) -> dict:
    """Is the real-snapshot panel adequate for the monthly causal design?"""
    out = {}
    for key, s in status.items():
        dates = s["available"]
        pre = [d for d in dates if d < C.ANNOUNCE_MONTH.isoformat()]
        mid = [d for d in dates if C.PHASE1_MONTH.isoformat() <= d < C.PHASE2_MONTH.isoformat()]
        post = [d for d in dates if d >= C.PHASE2_MONTH.isoformat()]
        out[key] = {"n_snapshots": len(dates), "pre_announcement": len(pre),
                    "phase1_window": len(mid), "phase2_window": len(post)}
    bc_ok = all(out.get(k, {}).get("pre_announcement", 0) >= 2 and out[k]["phase1_window"] >= 1
                for k in C.BC_MARKETS)
    return {"by_city": out, "bc_snapshot_did_feasible": bool(bc_ok)}


def run(offline: bool = False, refresh_fixtures: bool = False, probe: bool = False) -> dict:
    from src import synthetic  # local import keeps `ingest` importable without numpy-heavy deps

    C.RAW.mkdir(parents=True, exist_ok=True)
    C.PROCESSED.mkdir(parents=True, exist_ok=True)
    session = None if offline else _session()
    manifest: dict = {"run_date": date.today().isoformat(), "offline": offline}

    if probe and session is not None:
        hits = probe_archive(session, list(C.MARKETS))
        known = json.loads(KNOWN_SNAPSHOTS.read_text())
        for k, v in hits.items():
            known["snapshots"][k] = sorted(set(known["snapshots"].get(k, [])) | set(v))
        KNOWN_SNAPSHOTS.write_text(json.dumps(known, indent=2))

    snapshots = discover_snapshots(session, offline)
    status = download_listings(session, snapshots, offline)
    manifest["insideairbnb"] = {"snapshots": status, "coverage": live_coverage(status)}

    cpi = _with_fallback("statcan_cpi", fetch_cpi, CPI_RAW, CPI_FIXTURE, offline, manifest, session)
    boc = _with_fallback("boc_policy_rate", fetch_boc, BOC_RAW, BOC_FIXTURE, offline, manifest, session)

    CMHC_RAW.parent.mkdir(parents=True, exist_ok=True)
    user_cmhc = C.RAW / "cmhc" / "cmhc_rms_user.csv"
    src = user_cmhc if user_cmhc.exists() else CMHC_FIXTURE
    shutil.copyfile(src, CMHC_RAW)
    manifest["cmhc_rms"] = {"status": "user_dropin" if src == user_cmhc else "fixture_curated",
                            "path": str(src.relative_to(C.ROOT))}

    if refresh_fixtures:
        cpi.to_csv(CPI_FIXTURE, index=False)
        boc.to_csv(BOC_FIXTURE, index=False)
        anchors = compute_anchors({k: v["available"] for k, v in status.items()})
        ANCHORS_FIXTURE.write_text(json.dumps(anchors, indent=1))
        log.info("fixtures refreshed from live sources")

    n = synthetic.generate(C.SYNTHETIC_PARQUET)
    manifest["synthetic"] = {"status": "generated", "rows": n, "seed": C.SEED,
                             "path": str(C.SYNTHETIC_PARQUET.relative_to(C.ROOT))}
    C.MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))
    log.info("manifest written: %s", C.MANIFEST_PATH)
    return manifest


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--offline", action="store_true", help="never touch the network")
    p.add_argument("--refresh-fixtures", action="store_true",
                   help="overwrite cached CPI/BoC fixtures and calibration anchors from live data")
    p.add_argument("--probe-archive", action="store_true",
                   help="HEAD-probe for unlisted historical snapshots (slow, ~2k requests)")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    import os
    offline = a.offline or os.environ.get("STR_OFFLINE") == "1"
    m = run(offline=offline, refresh_fixtures=a.refresh_fixtures, probe=a.probe_archive)
    print(json.dumps(m["insideairbnb"]["coverage"], indent=2))


if __name__ == "__main__":
    main()

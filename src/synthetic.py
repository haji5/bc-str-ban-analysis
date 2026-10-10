"""Calibrated synthetic Inside Airbnb panel (offline fallback + parameter-recovery harness).

Design
------
* Listing-level microdata in the Inside Airbnb ``listings.csv`` schema, one snapshot
  per month (15th) from PANEL_START to PANEL_END, so the *same* SQL runs on real
  and synthetic data.
* Neighbourhood x room-type cell sizes are anchored to the latest real snapshot in
  ``data/fixtures/calibration_anchors.json``; policy effects, growth, seasonality,
  and noise come from ``data/fixtures/dgp_parameters.json``.
* Known pathologies of the real data are reproduced on purpose so the pipeline is
  tested against them: duplicate rows within a snapshot, ``$1,234.00`` price strings,
  missing prices, dormant listings, scrape-coverage shocks common to a city-month,
  and policy-induced exits concentrated among commercial (multi-listing) hosts.
* The private-room control is *partly treated* (as in the real data), so the
  room-type DiD estimand is ``tau_entire - tau_private``, not ``tau_entire``.

Everything is driven by a single ``numpy.random.Generator(SEED)``; output is
bit-for-bit reproducible.
"""
from __future__ import annotations

import json
import zlib
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from src import config as C

ROOM_LABEL = {"entire_home": "Entire home/apt", "private_room": "Private room"}
CITY_CENTRE = {
    "vancouver": (49.2827, -123.1207), "victoria": (48.4284, -123.3656),
    "ottawa": (45.4215, -75.6972), "seattle": (47.6062, -122.3321),
}


def load_params() -> dict:
    return json.loads((C.FIXTURES / "dgp_parameters.json").read_text())


def load_anchors() -> dict:
    return json.loads((C.FIXTURES / "calibration_anchors.json").read_text())


def months() -> pd.DatetimeIndex:
    return pd.date_range(C.PANEL_START.isoformat(), C.PANEL_END.isoformat(), freq="MS")


def months_between(a: date | pd.Timestamp, b: date | pd.Timestamp) -> int:
    a, b = pd.Timestamp(a), pd.Timestamp(b)
    return (b.year - a.year) * 12 + (b.month - a.month)


def effect_segment(city: str, nbhd: str) -> str:
    return f"{city}_exempt" if (city, nbhd) in C.PR_EXEMPT_NEIGHBOURHOODS else city


def true_effect(params: dict, city: str, nbhd: str, rt: str, month: pd.Timestamp) -> float:
    """Ground-truth policy effect (log points) for a cell-month."""
    seg = params["effects"].get(effect_segment(city, nbhd), {}).get(rt)
    if seg is None:
        return 0.0
    m = pd.Timestamp(month)
    ann, p1, p2 = (pd.Timestamp(x) for x in (C.ANNOUNCE_MONTH, C.PHASE1_MONTH, C.PHASE2_MONTH))
    tau = 0.0
    if ann <= m < p1:  # linear anticipation ramp toward anticipation_share * phase1
        frac = (months_between(ann, m) + 1) / (months_between(ann, p1) + 1)
        tau += params["anticipation_share"] * seg["phase1"] * frac
    if m >= p1:
        tau += seg["phase1"]
    if m >= p2:
        tau += seg["phase2"]
    return tau


def did_estimand(params: dict, cities: list[str], nbhds_by_city: dict[str, list[str]], phase: str) -> float:
    """Unit-weighted entire-minus-private estimand for a phase, as recovered by the
    neighbourhood-level room-type DiD with unit and city x month fixed effects."""
    vals = []
    for c in cities:
        for n in nbhds_by_city[c]:
            seg = params["effects"][effect_segment(c, n)]
            vals.append(seg["entire_home"][phase] - seg["private_room"][phase])
    return float(np.mean(vals))


def _common_log_path(params: dict, city: str, ms: pd.DatetimeIndex, rng) -> np.ndarray:
    kink = pd.Timestamp("2023-07-01")
    g1 = params["annual_growth_until_2023_07"][city] / 12
    g2 = params["annual_growth_after"][city] / 12
    t = np.arange(len(ms))
    tk = months_between(ms[0], kink)
    trend = np.where(t <= tk, g1 * t, g1 * tk + g2 * (t - tk))
    coverage = rng.normal(0, params["scrape_coverage_sd"], len(ms))  # common to all cells
    return trend + coverage


def _season(params: dict, rt: str, ms: pd.DatetimeIndex) -> np.ndarray:
    return params["seasonal_amplitude"][rt] * np.cos(2 * np.pi * (ms.month.values - 7) / 12)


def _hash01(*parts: str) -> float:
    return zlib.crc32("|".join(parts).encode()) / 2**32


def generate(out_path: Path) -> int:
    params, anchors = load_params(), load_anchors()
    rng = np.random.default_rng(C.SEED)
    ms = months()
    snap_dates = ms + pd.Timedelta(days=14)
    p1, p2 = pd.Timestamp(C.PHASE1_MONTH), pd.Timestamp(C.PHASE2_MONTH)

    rows_snap, rows_id = [], []                    # (month index, listing id) per row
    attr: dict[str, list] = {k: [] for k in
                             ["city", "nbhd", "rt", "commercial", "host_id", "born", "base_price",
                              "base_avail", "lat", "lon"]}
    next_id = 10_000_000

    for city, m in C.MARKETS.items():
        snaps = anchors["cities"][city]["snapshots"]
        ref_date = max(d for d in snaps if d[:7] <= C.PANEL_END.isoformat()[:7])
        cells = snaps[ref_date]["cells"]
        price_ref = snaps[ref_date]["median_price"] or {}
        common = _common_log_path(params, city, ms, rng)
        t_ref = min(months_between(ms[0], pd.Timestamp(ref_date)), len(ms) - 1)
        host_pool = rng.integers(1_000_000, 9_999_999, size=400) + zlib.crc32(city.encode()) % 1000

        for nbhd, rt, n_ref, _ in cells:
            ott = np.array([
                params["ottawa_2022_bylaw_entire_home"] * min(1.0, (i + 1) / 12)
                if city == "ottawa" and rt == "entire_home" else 0.0
                for i in range(len(ms))
            ])
            tau = np.array([true_effect(params, city, nbhd, rt, mm) for mm in ms])
            amp_rt = rt if rt in params["seasonal_amplitude"] else "other"
            mu = common + _season(params, amp_rt, ms) + tau + ott
            eps = np.zeros(len(ms))
            for i in range(len(ms)):
                prev = eps[i - 1] if i else 0.0
                eps[i] = params["cell_noise_rho"] * prev + rng.normal(0, params["cell_noise_sd"])
            base = max(n_ref, 0.3) / np.exp(mu[t_ref])
            expected = base * np.exp(mu + eps)
            # Policy-driven decline in BC cells after announcement -> commercial hosts exit first.
            declining = np.r_[False, np.diff(tau) < 0]

            p_comm = {"entire_home": 0.45, "private_room": 0.25}.get(rt, 0.6)
            med_price = price_ref.get(rt, 150.0 if rt == "entire_home" else 90.0)
            ox, oy = (_hash01(city, nbhd, "x") - 0.5) * 0.12, (_hash01(city, nbhd, "y") - 0.5) * 0.08
            pool = np.empty(0, dtype=np.int64)
            pool_comm = np.empty(0, dtype=bool)
            for i in range(len(ms)):
                k = rng.poisson(expected[i])
                if pool.size:
                    keep = rng.random(pool.size) > params["monthly_churn"]
                    pool, pool_comm = pool[keep], pool_comm[keep]
                if pool.size > k:
                    policy_exit = declining[i] or (m.treated and tau[i] < 0)
                    w = np.where(pool_comm & policy_exit, params["commercial_exit_weight"], 1.0)
                    drop = rng.choice(pool.size, size=pool.size - k, replace=False, p=w / w.sum())
                    pool, pool_comm = np.delete(pool, drop), np.delete(pool_comm, drop)
                n_new = k - pool.size
                if n_new > 0:
                    ids = np.arange(next_id, next_id + n_new)
                    next_id += n_new
                    comm_new = rng.random(n_new) < p_comm
                    attr["city"] += [city] * n_new
                    attr["nbhd"] += [nbhd] * n_new
                    attr["rt"] += [rt] * n_new
                    attr["commercial"] += comm_new.tolist()
                    attr["host_id"] += np.where(comm_new, rng.choice(host_pool, n_new),
                                                rng.integers(10_000_000, 600_000_000, n_new)).tolist()
                    attr["born"] += [i] * n_new
                    attr["base_price"] += (med_price * np.exp(rng.normal(0, 0.45, n_new))).tolist()
                    attr["base_avail"] += np.clip(rng.normal(150, 75, n_new) + 40 * comm_new, 1, 365).tolist()
                    lat0, lon0 = CITY_CENTRE[city]
                    attr["lat"] += (lat0 + oy + rng.normal(0, 0.006, n_new)).tolist()
                    attr["lon"] += (lon0 + ox + rng.normal(0, 0.009, n_new)).tolist()
                    pool = np.concatenate([pool, ids])
                    pool_comm = np.concatenate([pool_comm, comm_new])
                rows_snap.append(np.full(pool.size, i, dtype=np.int16))
                rows_id.append(pool.copy())

    # ------------------------------------------------------------------ row assembly
    A = pd.DataFrame(attr)
    A.index = np.arange(10_000_000, 10_000_000 + len(A))
    t_idx = np.concatenate(rows_snap).astype(int)
    ids = np.concatenate(rows_id)
    df = A.loc[ids].reset_index(names="id")
    df["t"] = t_idx
    snap = snap_dates[t_idx]
    month_ts = ms[t_idx]
    n = len(df)
    bc = df["city"].isin(C.BC_MARKETS).to_numpy()
    entire = (df["rt"] == "entire_home").to_numpy()
    exempt = np.array([(c, nb) in C.PR_EXEMPT_NEIGHBOURHOODS for c, nb in zip(df["city"], df["nbhd"])])
    post1 = (month_ts >= p1)
    post2 = (month_ts >= p2)

    season = 0.5 * 0.10 * np.cos(2 * np.pi * (month_ts.month.values - 7) / 12)
    price = df["base_price"].to_numpy() * np.exp(
        season + params["bc_entire_price_effect_phase1"] * (bc & entire & ~exempt & post1) + rng.normal(0, 0.08, n))
    price_str = np.char.add("$", np.array([f"{p:,.2f}" for p in price]))
    price_str[rng.random(n) < 0.02] = ""

    dormant = rng.random(n) < 0.08
    reviewed = (~dormant) & (rng.random(n) < 0.85)
    lag_days = np.where(dormant, rng.integers(200, 900, n),
                        np.where(reviewed, rng.integers(0, 170, n), rng.integers(190, 700, n)))
    last_review = (snap - pd.to_timedelta(lag_days, unit="D")).strftime("%Y-%m-%d").to_numpy().astype(object)
    never = (~reviewed) & (~dormant) & (rng.random(n) < 0.4)
    last_review[never] = ""
    avail = df["base_avail"].to_numpy() + params["bc_entire_availability_shift_days"] * (bc & entire & ~exempt & post1)
    avail = np.where(dormant, 0, np.clip(np.round(avail + rng.normal(0, 20, n)), 1, 365)).astype(int)
    born_ts = ms[df["born"].to_numpy()]
    first_review = (born_ts + pd.Timedelta(days=30)).strftime("%Y-%m-%d").to_numpy().astype(object)
    first_review[never] = ""

    lic = np.full(n, "", dtype=object)
    van = (df["city"] == "vancouver").to_numpy()
    lic[van & (rng.random(n) < 0.85)] = "Municipal registration number: 24-156789"
    vic = (df["city"] == "victoria").to_numpy()
    lic[vic & (rng.random(n) < 0.35)] = "Municipal registration number: 00012345"
    lic[bc & post2 & (rng.random(n) < 0.75)] = "Provincial registration number: H123456789"
    sea = (df["city"] == "seattle").to_numpy()
    lic[sea & (rng.random(n) < 0.8)] = "STR-OPLI-19-001234"
    ott_c = (df["city"] == "ottawa").to_numpy()
    lic[ott_c & (rng.random(n) < 0.6)] = "STR-845-123"

    other_label = np.where(rng.random(n) < 0.7, "Hotel room", "Shared room")
    room_type = np.where(entire, ROOM_LABEL["entire_home"],
                         np.where(df["rt"] == "private_room", ROOM_LABEL["private_room"], other_label))

    out = pd.DataFrame({
        "city": df["city"],
        "snapshot_date": snap.strftime("%Y-%m-%d"),
        "id": df["id"].astype(str),
        "last_scraped": snap.strftime("%Y-%m-%d"),
        "host_id": df["host_id"].astype(str),
        "neighbourhood_cleansed": df["nbhd"],
        "room_type": room_type,
        "price": price_str,
        "availability_365": avail.astype(str),
        "number_of_reviews": rng.poisson(40, n).astype(str),
        "number_of_reviews_ltm": np.where(reviewed, rng.poisson(10, n), 0).astype(str),
        "first_review": first_review,
        "last_review": last_review,
        "license": lic,
        "calculated_host_listings_count": np.where(df["commercial"], rng.integers(2, 30, n), 1).astype(str),
        "latitude": df["lat"].round(5).astype(str),
        "longitude": df["lon"].round(5).astype(str),
    })
    # Duplicate-row pathology: ~0.3% of rows re-scraped a day earlier with a stale price.
    dup = out.sample(frac=0.003, random_state=C.SEED).copy()
    dup["last_scraped"] = (pd.to_datetime(dup["last_scraped"]) - pd.Timedelta(days=1)).dt.strftime("%Y-%m-%d")
    out = pd.concat([out, dup], ignore_index=True)

    import duckdb

    out_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.register("out_df", out)
    con.execute(f"COPY out_df TO '{out_path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.close()
    return len(out)


if __name__ == "__main__":
    import time

    t0 = time.time()
    print(generate(C.SYNTHETIC_PARQUET), "rows in", round(time.time() - t0, 1), "s")

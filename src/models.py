"""Causal models for Bill 35 (pyfixest for high-dimensional FE, statsmodels for rent).

Every specification runs on each available ``data_source``:

* ``live``      - real Inside Airbnb snapshots (~quarterly). Results are empirical.
* ``synthetic`` - calibrated monthly panel with *known* ground truth. Results are a
  parameter-recovery check of the estimator, not findings; the truth is stored next
  to each estimate.

Specifications
--------------
S1  Within-BC room-type DiD (primary).  log(1+active) on EntireHome x {Anticipation,
    PostMay2024, PostMay2025} | unit FE + city x month FE, CRV1 by neighbourhood.
    PostMay2024 stays on after May 2025, so the Phase-2 term is *incremental*.
S2  Victoria CRD spatial DiD. Entire homes in principal-residence-covered vs exempt
    neighbourhoods (exempt areas are untreated by Phase 1) + a triple difference.
S3  Dynamic event study, t in [-12, +24] around May 2024, reference t = -8 (Sep 2023,
    last pre-announcement month); endpoints binned; joint pre-trend Wald test on
    pre-announcement leads. Live data are binned to quarters (snapshots are quarterly).
S4  Cross-market event study / DiD: BC vs Ottawa + Seattle entire homes, with a
    leave-one-control-out check and wild-cluster bootstrap p-values (few treated clusters).
S5  Rent transmission (real data only - synthetic STR is never regressed on real rents):
    (a) reduced form: CPI-rent growth, BC CMAs vs Ottawa, Driscoll-Kraay SEs;
    (b) association of CPI-rent growth with observed STR contraction + macro controls;
    (c) mechanical back-of-envelope bound.
"""
from __future__ import annotations

import json
import logging
import warnings
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import pyfixest as pf
import statsmodels.formula.api as smf
from scipy import stats

from src import config as cfg
from src import database as db
from src import synthetic as syn

log = logging.getLogger("models")
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

MIN_PRE_MEAN = 5  # drop neighbourhood x room cells averaging < 5 active listings pre-announcement

# Approximate renter households (2021 Census) for the IAB footprints; verify before citing.
RENTER_HOUSEHOLDS = {"vancouver": 166_000, "victoria": 66_000}


# =========================================================================== data
def load_nbhd_panel(source: str, drop_incomplete: bool = True) -> pd.DataFrame:
    """Observed neighbourhood x room-type x month cells. Truncated scrapes are dropped by
    default: their truncation is spatially uneven, so time FE cannot absorb it."""
    flt = " AND NOT scrape_incomplete" if drop_incomplete else ""
    df = db.query(f"SELECT * FROM str_nbhd_panel WHERE data_source = '{source}' AND is_observed{flt}")
    if df.empty:
        return df
    df["year_month"] = pd.to_datetime(df["year_month"])
    df["y"] = np.log1p(df["n_active"].astype(float))
    df["y_reviewed"] = np.log1p(df["n_reviewed_180d"].astype(float))
    df["ent"] = df["is_entire_home"].astype(float)
    df["covered"] = (~df["pr_exempt"].astype(bool)).astype(float)
    df["bc"] = df["treated_market"].astype(float)
    for c in ["anticipation", "post_phase1", "post_phase2"]:
        df[c] = df[c].astype(float)
    df["ym"] = df["year_month"].dt.strftime("%Y-%m")
    df["city_month"] = df["city"] + "|" + df["ym"]
    df["rt_month"] = df["room_type"] + "|" + df["ym"]
    df["rt_cal_month"] = df["room_type"] + "|" + df["year_month"].dt.month.astype(str)
    df["cov_month"] = df["covered"].astype(int).astype(str) + "|" + df["ym"]
    # Integer cluster codes: wildboottest's numba kernels reject object-dtype cluster ids.
    df["nbhd_cl"] = pd.factorize(df["nbhd_id"])[0].astype(np.int64)
    pre = df[df["year_month"] < pd.Timestamp(cfg.ANNOUNCE_MONTH)]
    keep = pre.groupby("unit_id")["n_active"].mean()
    df = df[df["unit_id"].isin(keep[keep >= MIN_PRE_MEAN].index)].copy()
    return df


def available_sources() -> list[str]:
    out = db.query("SELECT data_source, count(*) n FROM str_nbhd_panel WHERE is_observed GROUP BY 1")
    return sorted(out.loc[out["n"] > 0, "data_source"].tolist())


# =========================================================================== results
@dataclass
class ModelResult:
    spec: str
    label: str
    data_source: str
    coefs: list[dict]
    nobs: int
    r2: float | None
    r2_within: float | None
    n_clusters: int | None
    fe: str
    notes: str = ""
    extra: dict = field(default_factory=dict)

    def coef(self, term: str) -> dict | None:
        return next((c for c in self.coefs if c["term"] == term), None)


def _tidy(fit, terms: list[str] | None = None, truth: dict | None = None) -> list[dict]:
    t = fit.tidy()
    rows = []
    for term, r in t.iterrows():
        if terms and term not in terms:
            continue
        rows.append({
            "term": term, "estimate": float(r["Estimate"]), "se": float(r["Std. Error"]),
            "p": float(r["Pr(>|t|)"]), "ci_low": float(r["2.5%"]), "ci_high": float(r["97.5%"]),
            "truth": None if truth is None else truth.get(term),
        })
    return rows


def _record(fit, spec, label, source, fe, terms=None, truth=None, notes="", extra=None) -> ModelResult:
    G = getattr(fit, "_G", None)
    return ModelResult(
        spec=spec, label=label, data_source=source, coefs=_tidy(fit, terms, truth),
        nobs=int(fit._N), r2=float(fit._r2) if getattr(fit, "_r2", None) is not None else None,
        r2_within=float(fit._r2_within) if getattr(fit, "_r2_within", None) is not None else None,
        n_clusters=int(G[0]) if G else None, fe=fe, notes=notes, extra=extra or {},
    )


def _wild_p(fit, param: str, seed: int = cfg.SEED) -> float | None:
    try:
        return float(fit.wildboottest(param=param, reps=999, seed=seed)["Pr(>|t|)"])
    except Exception as exc:  # noqa: BLE001
        log.warning("wild bootstrap failed for %s: %s", param, exc)
        return None


# =========================================================================== S1
DID_TERMS = ["ent_antic", "ent_p1", "ent_p2"]


def _did_cols(df: pd.DataFrame, treat: str) -> pd.DataFrame:
    df = df.copy()
    df["ent_antic"] = df[treat] * df["anticipation"]
    df["ent_p1"] = df[treat] * df["post_phase1"]
    df["ent_p2"] = df[treat] * df["post_phase2"]
    return df


def _truth_bc(df: pd.DataFrame, cities: list[str]) -> dict:
    p = syn.load_params()
    nb = {c: sorted(df.loc[(df.city == c) & (df.room_type == "entire_home"), "neighbourhood"].unique())
          for c in cities}
    p1 = syn.did_estimand(p, cities, nb, "phase1")
    n_antic = (cfg.PHASE1_MONTH.year - cfg.ANNOUNCE_MONTH.year) * 12 + cfg.PHASE1_MONTH.month - cfg.ANNOUNCE_MONTH.month
    ramp = np.mean([(i + 1) / (n_antic + 1) for i in range(n_antic)])  # mirrors syn.true_effect
    return {"ent_antic": p["anticipation_share"] * p1 * ramp, "ent_p1": p1,
            "ent_p2": syn.did_estimand(p, cities, nb, "phase2")}


def did_bc_roomtype(df: pd.DataFrame, source: str, cities: list[str] | None = None,
                    outcome: str = "y", extra_fe: str = "", poisson: bool = False,
                    spec: str = "S1", label: str | None = None) -> ModelResult:
    cities = cities or cfg.BC_MARKETS
    d = _did_cols(df[df.city.isin(cities) & (df.covered == 1)], "ent")
    fe = "unit_id + city_month" + (f" + {extra_fe}" if extra_fe else "")
    if poisson:
        fit = pf.fepois(f"n_active ~ {' + '.join(DID_TERMS)} | {fe}", data=d, vcov={"CRV1": "nbhd_cl"})
    else:
        fit = pf.feols(f"{outcome} ~ {' + '.join(DID_TERMS)} | {fe}", data=d, vcov={"CRV1": "nbhd_cl"})
    truth = _truth_bc(d, cities) if source == "synthetic" else None
    return _record(
        fit, spec, label or f"Room-type DiD ({', '.join(c.title() for c in cities)})", source, fe,
        DID_TERMS, truth,
        notes="Treated: entire homes; control: private rooms in PR-covered neighbourhoods. "
              "Phase-2 term is incremental to Phase 1. Control is partly treated (registry "
              "applies to all STRs; ~75% of private-room listings belong to multi-listing hosts), "
              "so estimates are a lower bound on the entire-home effect.",
    )


# =========================================================================== S2
def did_victoria_exempt(df: pd.DataFrame, source: str) -> list[ModelResult]:
    v = df[df.city == "victoria"]
    out = []
    d = _did_cols(v[v.room_type == "entire_home"], "covered")
    fit = pf.feols(f"y ~ {' + '.join(DID_TERMS)} | unit_id + ym", data=d, vcov={"CRV1": "nbhd_cl"})
    truth = None
    if source == "synthetic":
        p = syn.load_params()["effects"]
        truth = {f"ent_{k}": p["victoria"]["entire_home"][ph] - p["victoria_exempt"]["entire_home"][ph]
                 for k, ph in [("p1", "phase1"), ("p2", "phase2")]}
    wild = {t: _wild_p(fit, t) for t in ["ent_p1", "ent_p2"]}
    out.append(_record(fit, "S2a", "Victoria entire homes: PR-covered vs exempt areas", source,
                       "unit_id + month", DID_TERMS, truth,
                       notes="Coefficients named ent_* for comparability; treatment here is "
                             "'PR-covered neighbourhood'. Only 5 exempt (control) clusters -> "
                             "see wild-bootstrap p-values.",
                       extra={"wild_bootstrap_p": wild}))
    # Triple difference: (entire - private) x (covered - exempt) x post.
    d3 = v.copy()
    for k, col in [("antic", "anticipation"), ("p1", "post_phase1"), ("p2", "post_phase2")]:
        d3[f"ddd_{k}"] = d3["ent"] * d3["covered"] * d3[col]
        d3[f"cov_{k}"] = d3["covered"] * d3[col]
    terms = ["ddd_antic", "ddd_p1", "ddd_p2", "cov_antic", "cov_p1", "cov_p2"]
    fit3 = pf.feols(f"y ~ {' + '.join(terms)} | unit_id + rt_month", data=d3, vcov={"CRV1": "nbhd_cl"})
    out.append(_record(fit3, "S2b", "Victoria triple difference (room x coverage x post)", source,
                       "unit_id + room_type x month", ["ddd_antic", "ddd_p1", "ddd_p2"],
                       notes="Differences out both the registry shock common to room types and the "
                             "exempt-area trend."))
    return out


# =========================================================================== S3 / S4
def _bin(event_time: pd.Series, freq: str, window: tuple[int, int]) -> tuple[pd.Series, int]:
    lo, hi = window
    if freq == "M":
        return event_time.clip(lo, hi).astype(int), cfg.EVENT_REF
    q = np.round(event_time / 3).astype(int)
    return q.clip(int(np.floor(lo / 3)), int(np.floor(hi / 3))), int(np.round(cfg.EVENT_REF / 3))


def _name(k: int) -> str:
    return f"es_m{abs(k)}" if k < 0 else f"es_p{k}"


def _joint_wald(fit, names: list[str]) -> dict:
    names = [n for n in names if n in fit._coefnames]
    if not names:
        return {"F": None, "p": None, "df": 0}
    idx = [fit._coefnames.index(n) for n in names]
    b = fit.coef().iloc[idx].values
    V = fit._vcov[np.ix_(idx, idx)]
    q = len(idx)
    F = float(b @ np.linalg.pinv(V) @ b) / q
    G = int(fit._G[0]) if getattr(fit, "_G", None) else fit._N
    return {"F": F, "p": float(1 - stats.f.cdf(F, q, max(G - 1, 1))), "df": q}


def event_study(df: pd.DataFrame, source: str, design: str = "roomtype",
                window: tuple[int, int] = (cfg.EVENT_MIN, cfg.EVENT_MAX),
                controls: list[str] | None = None) -> ModelResult:
    """design='roomtype': entire vs private within BC (PR-covered areas), city x month FE.
       design='cross':    BC vs control-city entire homes, month FE."""
    freq = "M" if source == "synthetic" else "Q"
    if not window[0] < cfg.EVENT_REF < window[1]:
        raise ValueError(f"window {window} must strictly contain the reference period t={cfg.EVENT_REF} (Sep 2023)")
    if design == "roomtype":
        d = df[df.city.isin(cfg.BC_MARKETS) & (df.covered == 1)].copy()
        treat, fe = "ent", "unit_id + city_month"
    else:
        ctrl = controls or [k for k, m in cfg.MARKETS.items() if not m.treated]
        d = df[(df.room_type == "entire_home") & (df.city.isin(cfg.BC_MARKETS + ctrl)) & (df.covered == 1)].copy()
        treat, fe = "bc", "unit_id + ym"
        # Trim (not bin) for the cross-market design: binning would load Ottawa's 2022 bylaw
        # roll-out and BC's faster post-COVID rebound onto the t=-12 endpoint.
        d = d[(d["event_time"] >= window[0]) & (d["event_time"] <= window[1])]
    d["k"], ref = _bin(d["event_time"], freq, window)
    ks = sorted(k for k in d["k"].unique() if k != ref)
    for k in ks:
        d[_name(k)] = d[treat] * (d["k"] == k)
    names = [_name(k) for k in ks]
    fit = pf.feols(f"y ~ {' + '.join(names)} | {fe}", data=d, vcov={"CRV1": "nbhd_cl"})
    scale = 1 if freq == "M" else 3
    announce_k = (cfg.ANNOUNCE_MONTH.year - cfg.PHASE1_MONTH.year) * 12 + cfg.ANNOUNCE_MONTH.month - cfg.PHASE1_MONTH.month
    pre_names = [_name(k) for k in ks if k * scale < announce_k and k < ref]
    truth = None
    if source == "synthetic" and design == "roomtype":
        p = syn.load_params()
        truth = {}
        nb = {c: sorted(d.loc[d.city == c, "neighbourhood"].unique()) for c in cfg.BC_MARKETS}
        months_ = pd.date_range(cfg.PANEL_START.isoformat(), cfg.PANEL_END.isoformat(), freq="MS")
        ref_m = pd.Timestamp(cfg.PHASE1_MONTH) + pd.DateOffset(months=cfg.EVENT_REF)

        def gap(mm):
            vals = [syn.true_effect(p, c, n, "entire_home", mm) - syn.true_effect(p, c, n, "private_room", mm)
                    for c in cfg.BC_MARKETS for n in nb[c]]
            return float(np.mean(vals))
        g_ref = gap(ref_m)
        for mm in months_:
            k = (mm.year - cfg.PHASE1_MONTH.year) * 12 + mm.month - cfg.PHASE1_MONTH.month
            if window[0] < k < window[1] and k != ref:
                truth[_name(k)] = gap(mm) - g_ref
    rec = _record(fit, "S3" if design == "roomtype" else "S4",
                  f"Event study ({'entire vs private, BC' if design == 'roomtype' else 'BC vs ' + '+'.join(controls or ['ottawa', 'seattle'])})",
                  source, fe, names, truth,
                  notes=f"Reference period {'t=' + str(ref) if freq == 'M' else 'quarter bin ' + str(ref)} "
                        f"(Sep 2023); endpoints binned; {'monthly' if freq == 'M' else 'quarterly bins (k = round(t/3))'}.",
                  extra={"freq": freq, "ref": ref, "window": list(window), "pretrend_test": _joint_wald(fit, pre_names),
                         "pre_terms": pre_names})
    for c in rec.coefs:
        k = c["term"]
        kk = -int(k[4:]) if k.startswith("es_m") else int(k[4:])
        c["event_time"] = kk * scale
    return rec


def pretrend_slope(df: pd.DataFrame, source: str) -> dict:
    """Differential linear trend (entire vs private, BC) using pre-announcement data only."""
    d = df[df.city.isin(cfg.BC_MARKETS) & (df.covered == 1) & (df.year_month < pd.Timestamp(cfg.ANNOUNCE_MONTH))].copy()
    d["ent_trend"] = d["ent"] * (d["event_time"] / 12.0)
    if d["ym"].nunique() < 3:
        return {"estimate": None, "note": "fewer than 3 pre-announcement periods"}
    fit = pf.feols("y ~ ent_trend | unit_id + city_month", data=d, vcov={"CRV1": "nbhd_cl"})
    t = fit.tidy().loc["ent_trend"]
    return {"estimate_per_year": float(t["Estimate"]), "se": float(t["Std. Error"]), "p": float(t["Pr(>|t|)"]),
            "n_periods": int(d["ym"].nunique())}


def did_cross_market(df: pd.DataFrame, source: str, controls: list[str]) -> ModelResult:
    d = df[(df.room_type == "entire_home") & df.city.isin(cfg.BC_MARKETS + controls) & (df.covered == 1)]
    d = _did_cols(d[d.event_time >= cfg.EVENT_MIN], "bc")
    fit = pf.feols(f"y ~ {' + '.join(DID_TERMS)} | unit_id + ym", data=d, vcov={"CRV1": "nbhd_cl"})
    truth = None
    if source == "synthetic":
        p = syn.load_params()["effects"]
        nb = {c: d.loc[d.city == c, "neighbourhood"].unique() for c in cfg.BC_MARKETS}
        truth = {f"ent_{k}": float(np.mean([p[syn.effect_segment(c, n)]["entire_home"][ph]
                                            for c in cfg.BC_MARKETS for n in nb[c]]))
                 for k, ph in [("p1", "phase1"), ("p2", "phase2")]}
    wild = {t: _wild_p(fit, t) for t in ["ent_p1", "ent_p2"]}
    return _record(fit, "S4b", f"Cross-market DiD: BC vs {'+'.join(c.title() for c in controls)}",
                   source, "unit_id + month", DID_TERMS, truth,
                   notes="Sample starts May 2023 (t=-12) so Ottawa's 2022 bylaw roll-out does not "
                         "contaminate the pre-period. Treatment varies by province -> effectively "
                         "2 treated clusters; rely on wild-bootstrap p-values and leave-one-out.",
                   extra={"wild_bootstrap_p": wild})


# =========================================================================== S5 rent
def rent_models() -> dict:
    p = db.query("""
        SELECT city, year_month, cpi_rent, cpi_rent_yoy_log, cpi_real_rent_yoy_log, policy_rate,
               cmhc_vacancy_rate, treated_market, post_phase1, post_phase2, anticipation
        FROM str_rent_panel
        WHERE data_source = (SELECT min(data_source) FROM str_rent_panel)
          AND room_type = 'entire_home' AND city IN ('vancouver','victoria','ottawa')
          AND cpi_rent_yoy_log IS NOT NULL
        ORDER BY city, year_month
    """)
    out: dict = {}
    if p.empty:
        return {"note": "CPI not available"}
    p["year_month"] = pd.to_datetime(p["year_month"])
    p["g"] = 100 * p["cpi_rent_yoy_log"]
    p["g_real"] = 100 * p["cpi_real_rent_yoy_log"]
    for c in ["post_phase1", "post_phase2", "anticipation", "treated_market"]:
        p[c] = p[c].astype(float)
    p["bc_p1"] = p["treated_market"] * p["post_phase1"]
    p["bc_p2"] = p["treated_market"] * p["post_phase2"]
    p["bc_antic"] = p["treated_market"] * p["anticipation"]
    p["t"] = (p["year_month"].dt.year - 2022) * 12 + p["year_month"].dt.month
    p["ym"] = p["year_month"].dt.strftime("%Y-%m")
    tvec = p["t"].values

    def fit(formula, data, tv, name):
        # Patsy silently drops NA rows; align the Driscoll-Kraay time index with the rows it kept.
        model = smf.ols(formula, data=data)
        kept = model.data.row_labels
        tv = data.loc[kept, "t"].values
        m = model.fit(cov_type="hac-groupsum", cov_kwds={"time": tv, "maxlags": 12})
        rows = []
        for term in m.params.index:
            if term.startswith(("C(", "Intercept")):
                continue
            ci = m.conf_int().loc[term]
            rows.append({"term": term, "estimate": float(m.params[term]), "se": float(m.bse[term]),
                         "p": float(m.pvalues[term]), "ci_low": float(ci[0]), "ci_high": float(ci[1])})
        return {"label": name, "coefs": rows, "nobs": int(m.nobs), "r2": float(m.rsquared),
                "se_type": "Driscoll-Kraay (HAC group-sum, 12 lags)"}

    # Primary: log *levels*. In y/y growth a one-off level shift at May 2024 appears as -x for
    # twelve months and +x exactly when the May-2025 dummy switches on, so the growth spec
    # cannot separate Phase 2 from the mechanical reversal of Phase 1.
    p["ln_rent"] = 100 * np.log(p["cpi_rent"])
    out["rent_level_did"] = fit("ln_rent ~ bc_antic + bc_p1 + bc_p2 + C(city) + C(ym)", p, tvec,
                                "100 x ln CPI rented accommodation: BC CMAs vs Ottawa (level DiD)")
    out["rent_reduced_form"] = fit("g ~ bc_antic + bc_p1 + bc_p2 + C(city) + C(ym)", p, tvec,
                                   "CPI rented-accommodation y/y growth (pp): BC CMAs vs Ottawa")
    out["rent_reduced_form_real"] = fit("g_real ~ bc_antic + bc_p1 + bc_p2 + C(city) + C(ym)", p, tvec,
                                        "Real CPI rent y/y growth (pp, deflated by all-items)")
    out["rent_macro"] = fit("g ~ policy_rate + cmhc_vacancy_rate + bc_p1 + bc_p2 + C(city)",
                            p.dropna(subset=["cmhc_vacancy_rate", "policy_rate"]),
                            p.dropna(subset=["cmhc_vacancy_rate", "policy_rate"])["t"].values,
                            "CPI rent y/y growth on macro controls (no month FE)")

    # (b) association with *observed* STR contraction (live snapshots only)
    live = db.query("""
        SELECT city, year_month, n_active_pr_covered AS n, cpi_rent, policy_rate, cmhc_vacancy_rate
        FROM str_rent_panel
        WHERE data_source = 'live' AND room_type = 'entire_home' AND is_observed
          AND city IN ('vancouver','victoria') AND cpi_rent IS NOT NULL
    """)
    if len(live) >= 8:
        live["ln_rent"] = 100 * np.log(live["cpi_rent"])
        live["ln_str"] = 100 * np.log(live["n"].astype(float))
        live["t"] = (pd.to_datetime(live["year_month"]).dt.year - 2022) * 12 + pd.to_datetime(live["year_month"]).dt.month
        live["trend_city"] = live["t"] * (live["city"] == "victoria")
        out["rent_on_str_live"] = fit("ln_rent ~ ln_str + policy_rate + t + trend_city + C(city)", live,
                                      live["t"].values,
                                      "100*ln CPI rent on 100*ln active entire-home STRs (live snapshots)")
    # (c) mechanical bound from observed real declines
    bound = db.query(f"""
        WITH s AS (
          SELECT city, year_month, n_active_pr_covered AS n FROM str_rent_panel
          WHERE data_source = 'live' AND room_type = 'entire_home' AND is_observed AND treated_market)
        SELECT city,
               arg_max(n, year_month) FILTER (WHERE year_month < DATE '{cfg.ANNOUNCE_MONTH}') AS n_pre,
               max(year_month) FILTER (WHERE year_month < DATE '{cfg.ANNOUNCE_MONTH}')        AS pre_month,
               arg_max(n, year_month)                                                              AS n_post,
               max(year_month)                                                                     AS post_month
        FROM s GROUP BY city
    """) if _has_live() else pd.DataFrame()
    rows = []
    for r in bound.itertuples():
        removed = max(float(r.n_pre - r.n_post), 0.0)
        stock = RENTER_HOUSEHOLDS.get(r.city)
        share = removed / stock if stock else None
        rows.append({"city": r.city, "pre_month": str(r.pre_month)[:7], "post_month": str(r.post_month)[:7],
                     "active_pre": int(r.n_pre), "active_post": int(r.n_post), "units_removed": removed,
                     "renter_households": stock, "supply_shock_pct": None if share is None else 100 * share,
                     "rent_effect_pct_range": None if share is None else
                     [-100 * share * 0.25 * 1.0, -100 * share * 1.0 * 2.0]})
    out["mechanical_bound"] = {
        "rows": rows,
        "assumptions": "Rent effect = -(units removed / renter households) x conversion share [0.25, 1] "
                       "x inverse demand elasticity [1, 2]. Upper bound: assumes every delisted unit "
                       "enters the long-term market at once.",
    }
    return out


def _has_live() -> bool:
    return "live" in available_sources()


# =========================================================================== orchestration
def run_all() -> dict:
    results: list[ModelResult] = []
    diagnostics: dict = {}
    for source in available_sources():
        df = load_nbhd_panel(source)
        if df.empty:
            continue
        log.info("[%s] panel rows=%d units=%d", source, len(df), df.unit_id.nunique())
        results.append(did_bc_roomtype(df, source))
        for c in cfg.BC_MARKETS:
            results.append(did_bc_roomtype(df, source, cities=[c], spec=f"S1-{c}"))
        results.append(did_bc_roomtype(df, source, poisson=True, spec="S1-ppml", label="Room-type DiD, PPML (counts)"))
        results.append(did_bc_roomtype(df, source, outcome="y_reviewed", spec="S1-reviewed",
                                       label="Room-type DiD, reviewed-in-180d outcome"))
        if source == "synthetic":
            results.append(did_bc_roomtype(df, source, extra_fe="rt_cal_month", spec="S1-season",
                                           label="Room-type DiD + room-type x calendar-month FE"))
        results += did_victoria_exempt(df, source)
        results.append(event_study(df, source, "roomtype"))
        diagnostics[f"pretrend_slope_{source}"] = pretrend_slope(df, source)

        # A control market is eligible only with >= 3 pre-announcement snapshots inside the
        # event window; a market observed only post-treatment would just add noise to the
        # month FE (live Seattle archives start in 2025).
        win = df[(df.event_time >= cfg.EVENT_MIN) & (df.year_month < pd.Timestamp(cfg.ANNOUNCE_MONTH))]
        eligible = [c for c, m in cfg.MARKETS.items() if not m.treated
                    and win.loc[win.city == c, "ym"].nunique() >= (3 if source == "synthetic" else 2)]
        diagnostics[f"cross_market_controls_{source}"] = eligible
        if eligible:
            results.append(event_study(df, source, "cross", controls=eligible))
            results.append(did_cross_market(df, source, eligible))
            if len(eligible) > 1:
                for c in eligible:
                    results.append(did_cross_market(df, source, [c]))

    rent = rent_models()
    payload = {
        "results": [r.__dict__ for r in results],
        "rent": rent,
        "diagnostics": diagnostics,
        "manifest": json.loads(cfg.MANIFEST_PATH.read_text()) if cfg.MANIFEST_PATH.exists() else {},
    }
    cfg.RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    cfg.RESULTS_PATH.write_text(json.dumps(payload, indent=2, default=str))
    table = pd.DataFrame([{**{k: v for k, v in r.__dict__.items() if k not in ("coefs", "extra", "notes")}, **c}
                          for r in results for c in r.coefs])
    table.to_csv(cfg.PROCESSED / "regression_table.csv", index=False)
    return payload


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    out = run_all()
    for r in out["results"]:
        if r["spec"] in ("S3", "S4"):
            pt = r["extra"]["pretrend_test"]
            print(f"[{r['data_source']:9s}] {r['spec']:10s} {r['label']}: pre-trend F={pt['F']} p={pt['p']}")
            continue
        cs = "  ".join(f"{c['term']}={c['estimate']:+.3f}({c['se']:.3f})"
                       + (f"[true {c['truth']:+.3f}]" if c.get("truth") is not None else "")
                       for c in r["coefs"])
        print(f"[{r['data_source']:9s}] {r['spec']:10s} {r['label']}: {cs}  N={r['nobs']} R2w={r['r2_within']}")
    for k, v in out["rent"].items():
        if isinstance(v, dict) and "coefs" in v:
            print("RENT", k, [(c["term"], round(c["estimate"], 3), round(c["se"], 3)) for c in v["coefs"]])
    print(json.dumps(out["rent"].get("mechanical_bound", {}), indent=1, default=str))
    print(json.dumps(out["diagnostics"], indent=1, default=str))


if __name__ == "__main__":
    main()

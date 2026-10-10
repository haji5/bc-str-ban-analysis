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
    neighbourhoods (exempt areas are untreated by Phase 1; an area leaves the control
    group when it opts in) + its event study + a triple difference. Only 2-3 control
    clusters, so inference adds placebo-in-space randomization inference.
S3  Dynamic event study, t in [-12, +24] around May 2024, reference t = -8 (Sep 2023,
    last pre-announcement month); joint pre-trend Wald test on pre-announcement leads.
    Synthetic (monthly) data bin the endpoints. Live data use one bin per snapshot
    quarter and never pool leads, so each pre-announcement snapshot is its own lead.
S4  Cross-market event study / DiD: BC vs Ottawa + Seattle entire homes, with a
    leave-one-control-out check and wild-cluster bootstrap p-values (few treated clusters).
S5  Rent transmission (real data only - synthetic STR is never regressed on real rents):
    (a) reduced form: CPI-rent growth, BC CMAs vs Ottawa, Driscoll-Kraay SEs;
    (b) association of CPI-rent growth with observed STR contraction + macro controls;
    (c) mechanical back-of-envelope bound.
"""
from __future__ import annotations

import itertools
import json
import logging
import math
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
    # Sorted: cluster codes (and so wild-bootstrap draws) depend on row order, which DuckDB
    # does not fix across rebuilds.
    df = db.query(f"SELECT * FROM str_nbhd_panel WHERE data_source = '{source}' AND is_observed{flt} "
                  "ORDER BY city, neighbourhood, room_type, year_month")
    if df.empty:
        return df
    df["year_month"] = pd.to_datetime(df["year_month"])
    df["y"] = np.log1p(df["n_active"].astype(float))
    df["y_reviewed"] = np.log1p(df["n_reviewed_180d"].astype(float))
    df["ent"] = df["is_entire_home"].astype(float)
    # covered = under the principal-residence requirement from Phase 1 (fixed geography);
    # opted_in = an exempt area after its opt-in, which leaves the exempt-area control.
    df["covered"] = (~df["pr_exempt"].astype(bool)).astype(float)
    df["opted_in"] = (df["pr_exempt"].astype(bool) & ~df["pr_exempt_now"].astype(bool)).astype(float)
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
    # 9,999 draws: with 999 the p-value moved by ~0.015 when only the row order changed.
    try:
        return float(fit.wildboottest(param=param, reps=9_999, seed=seed)["Pr(>|t|)"])
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
              "Phase-2 term is incremental to Phase 1. The control is partly treated: the "
              "Phase-2 registry applies to every STR, and private rooms in Victoria's covered "
              "areas fell ~25%. Renting rooms in one's own principal residence stays legal, so "
              "the size of the Phase-1 spill-over is unknown; read as a lower bound.",
    )


# =========================================================================== S2
def _placebo_p(d: pd.DataFrame, treat: str, terms: dict[str, str], max_draws: int = 20_000,
               seed: int = cfg.SEED, joint: list[str] | None = None) -> dict:
    """Placebo-in-space randomization inference for a design with few control clusters.

    Every set of as many neighbourhoods as there are real controls (all combinations when
    feasible, else ``max_draws`` random sets) is relabelled as the control group and the
    two-way FE regression is re-estimated; ``terms`` maps each coefficient to the period
    column it interacts with treatment. p = share of placebo |estimates| >= the actual
    |estimate| (the actual assignment is one of the draws). ``joint`` adds a p-value for the
    sum of squared coefficients over those terms (a pre-trend test). Valid under the sharp
    null with exchangeable neighbourhoods. With 2-3 control clusters, cluster-robust and
    wild-bootstrap p-values are unreliable (CRV1 over-rejects), so this is the benchmark.
    """
    units = pd.factorize(d["nbhd_id"])[0]
    times = pd.factorize(d["ym"])[0]
    n_u = int(units.max()) + 1
    base = np.hstack([np.eye(n_u)[units], np.eye(int(times.max()) + 1)[times][:, 1:]])
    y = d["y"].to_numpy(float)
    period = np.column_stack([d[c].to_numpy(float) for c in terms.values()])
    is_ctrl = (pd.Series(d[treat].to_numpy()).groupby(units).first() == 0).to_numpy()

    def est(ctrl: np.ndarray) -> np.ndarray:
        x = (~ctrl[units]).astype(float)[:, None] * period
        return np.linalg.lstsq(np.hstack([x, base]), y, rcond=None)[0][: period.shape[1]]

    k = int(is_ctrl.sum())
    n_comb = math.comb(n_u, k)
    if n_comb <= max_draws:
        draws = itertools.combinations(range(n_u), k)
    else:
        rng = np.random.default_rng(seed)
        draws = (rng.choice(n_u, k, replace=False) for _ in range(max_draws))
    actual = est(is_ctrl)
    perm = []
    for c in draws:
        m = np.zeros(n_u, dtype=bool)
        m[list(c)] = True
        perm.append(est(m))
    perm = np.array(perm)
    hits = (np.abs(perm) >= np.abs(actual) - 1e-12).mean(axis=0)
    out = {"p": {t: float(h) for t, h in zip(terms, hits)}, "n_placebos": len(perm),
           "exhaustive": n_comb <= max_draws, "n_controls": k, "n_units": n_u}
    if joint:
        j = [list(terms).index(t) for t in joint]
        ss = (perm[:, j] ** 2).sum(axis=1)
        out["joint_p"] = float((ss >= (actual[j] ** 2).sum() - 1e-12).mean())
        out["joint_terms"] = list(joint)
    return out


def _exempt_truth() -> dict:
    p = syn.load_params()
    e = p["effects"]
    n_antic = (cfg.PHASE1_MONTH.year - cfg.ANNOUNCE_MONTH.year) * 12 + cfg.PHASE1_MONTH.month - cfg.ANNOUNCE_MONTH.month
    ramp = np.mean([(i + 1) / (n_antic + 1) for i in range(n_antic)])  # mirrors syn.true_effect
    gap = {ph: e["victoria"]["entire_home"][ph] - e["victoria_exempt"]["entire_home"][ph]
           for ph in ("phase1", "phase2")}
    return {"ent_antic": p["anticipation_share"] * gap["phase1"] * ramp,
            "ent_p1": gap["phase1"], "ent_p2": gap["phase2"]}


def did_victoria_exempt(df: pd.DataFrame, source: str, inference: bool = True) -> list[ModelResult]:
    """Victoria entire homes, PR-covered vs exempt areas (preferred design), its
    robustness variants, and the triple difference. An exempt area that opts in leaves
    the control group from its opt-in month (Salt Spring Island, Nov 2025).
    ``inference=False`` skips the resampling (randomization inference, wild bootstrap)
    for interactive use."""
    v = df[(df.city == "victoria") & (df.opted_in == 0)]
    ent = v[v.room_type == "entire_home"]
    truth = _exempt_truth() if source == "synthetic" else None
    did_terms = {"ent_antic": "anticipation", "ent_p1": "post_phase1", "ent_p2": "post_phase2"}
    never = ent[~((ent.covered == 0) & ent.pr_exempt_until.notna())]
    variants = [
        ("S2a", "Victoria entire homes: PR-covered vs exempt areas", ent, "y", False),
        ("S2a-never", "Victoria: PR-covered vs never-covered areas only", never, "y", False),
        ("S2a-reviewed", "Victoria covered vs exempt, reviewed-in-180d outcome", ent, "y_reviewed", False),
        ("S2a-ppml", "Victoria covered vs exempt, PPML (counts)", ent, "n_active", True),
    ]
    out = []
    for spec, label, sample, outcome, poisson in variants:
        d = _did_cols(sample, "covered")
        est = pf.fepois if poisson else pf.feols
        fit = est(f"{outcome} ~ {' + '.join(DID_TERMS)} | unit_id + ym", data=d, vcov={"CRV1": "nbhd_cl"})
        ctrl = sorted(d.loc[d.covered == 0, "neighbourhood"].unique())
        extra: dict = {"controls": ctrl}
        if inference and spec in ("S2a", "S2a-never"):
            extra["wild_bootstrap_p"] = {t: _wild_p(fit, t) for t in ["ent_p1", "ent_p2"]}
            extra["randomization_inference"] = _placebo_p(d, "covered", did_terms)
        out.append(_record(
            fit, spec, label, source, "unit_id + month", DID_TERMS, truth,
            notes=f"Coefficients named ent_* for comparability; treatment is 'PR-covered "
                  f"neighbourhood'. Controls: {', '.join(ctrl)} ({len(ctrl)} clusters). With this "
                  f"few controls the CRV1 p-values overstate precision; read the "
                  f"randomization-inference p-values.",
            extra=extra))
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
                             "exempt-area trend. Private rooms are themselves partly treated, so this "
                             "nets part of the effect out and is imprecise."))
    return out


# =========================================================================== S3 / S4
def _bin(event_time: pd.Series, freq: str, window: tuple[int, int]) -> tuple[pd.Series, int]:
    lo, hi = window
    if freq == "M":
        return event_time.clip(lo, hi).astype(int), cfg.EVENT_REF
    # Quarterly (live snapshots): one bin per snapshot quarter. Leads are never pooled into
    # an endpoint bin, so every pre-announcement snapshot is its own pre-trend coefficient.
    q = np.round(event_time / 3).astype(int)
    return q.clip(upper=int(np.floor(hi / 3))), int(np.round(cfg.EVENT_REF / 3))


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


ES_LABEL = {"roomtype": "entire vs private, BC", "exempt": "Victoria covered vs exempt areas"}
ES_SPEC = {"roomtype": "S3", "exempt": "S2-ES", "cross": "S4"}


def event_study(df: pd.DataFrame, source: str, design: str = "roomtype",
                window: tuple[int, int] = (cfg.EVENT_MIN, cfg.EVENT_MAX),
                controls: list[str] | None = None, inference: bool = True) -> ModelResult:
    """design='roomtype': entire vs private within BC (PR-covered areas), city x month FE.
       design='exempt':   Victoria entire homes, PR-covered vs exempt areas, month FE
                          (plus a randomization-inference pre-trend test if ``inference``).
       design='cross':    BC vs control-city entire homes, month FE."""
    freq = "M" if source == "synthetic" else "Q"
    if not window[0] < cfg.EVENT_REF < window[1]:
        raise ValueError(f"window {window} must strictly contain the reference period t={cfg.EVENT_REF} (Sep 2023)")
    if design == "roomtype":
        d = df[df.city.isin(cfg.BC_MARKETS) & (df.covered == 1)].copy()
        treat, fe = "ent", "unit_id + city_month"
    elif design == "exempt":
        d = df[(df.city == "victoria") & (df.room_type == "entire_home") & (df.opted_in == 0)].copy()
        treat, fe = "covered", "unit_id + ym"
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
    extra_ri = {}
    if inference and design == "exempt":
        # Few control clusters: CRV1 Wald tests over-reject, so add a placebo-in-space test.
        for k in ks:
            d["_per_" + _name(k)] = (d["k"] == k).astype(float)
        extra_ri["randomization_inference"] = _placebo_p(
            d, treat, {n: "_per_" + n for n in names}, joint=pre_names)
    truth = None
    if source == "synthetic" and design in ("roomtype", "exempt"):
        p = syn.load_params()
        truth = {}
        months_ = pd.date_range(cfg.PANEL_START.isoformat(), cfg.PANEL_END.isoformat(), freq="MS")
        ref_m = pd.Timestamp(cfg.PHASE1_MONTH) + pd.DateOffset(months=cfg.EVENT_REF)
        if design == "roomtype":
            nb = {c: sorted(d.loc[d.city == c, "neighbourhood"].unique()) for c in cfg.BC_MARKETS}

            def gap(mm):
                return float(np.mean([syn.true_effect(p, c, n, "entire_home", mm)
                                      - syn.true_effect(p, c, n, "private_room", mm)
                                      for c in cfg.BC_MARKETS for n in nb[c]]))
        else:
            cov = sorted(d.loc[d.covered == 1, "neighbourhood"].unique())
            exm = sorted(d.loc[d.covered == 0, "neighbourhood"].unique())

            def gap(mm):
                still = [n for n in exm if syn.effect_segment("victoria", n, mm).endswith("_exempt")]
                return float(np.mean([syn.true_effect(p, "victoria", n, "entire_home", mm) for n in cov])
                             - np.mean([syn.true_effect(p, "victoria", n, "entire_home", mm) for n in still]))
        g_ref = gap(ref_m)
        for mm in months_:
            k = (mm.year - cfg.PHASE1_MONTH.year) * 12 + mm.month - cfg.PHASE1_MONTH.month
            if window[0] < k < window[1] and k != ref:
                truth[_name(k)] = gap(mm) - g_ref
    bins = ("monthly; endpoints binned" if freq == "M" else
            "one bin per snapshot quarter (k = round(t/3)); leads not pooled")
    label = ES_LABEL.get(design) or "BC vs " + "+".join(controls or ["ottawa", "seattle"])
    rec = _record(fit, ES_SPEC[design], f"Event study ({label})", source, fe, names, truth,
                  notes=f"Reference {'t=' + str(ref) if freq == 'M' else 'quarter bin ' + str(ref)} "
                        f"(last pre-announcement snapshot, Aug-Sep 2023); {bins}.",
                  extra={"freq": freq, "ref": ref, "window": list(window), "pretrend_test": _joint_wald(fit, pre_names),
                         "pre_terms": pre_names, **extra_ri})
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
    out: dict = {"note": "Three CMAs, two of them treated. Driscoll-Kraay SEs need many cross-sections "
                         "or a long panel, so these p-values are not credible in either direction: the "
                         "rent models are descriptive."}
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
                       "enters the long-term market at once. Units removed are PR-covered areas only; "
                       "renter households are approximate 2021 Census totals for the City of "
                       "Vancouver and the whole CRD (including exempt areas).",
    }
    return out


def _records(df: pd.DataFrame) -> list[dict]:
    return json.loads(df.to_json(orient="records", date_format="iso"))


def descriptives() -> dict:
    """Descriptive figures the README and brief cite, computed from the live panel."""
    if not _has_live():
        return {}
    ann = cfg.ANNOUNCE_MONTH.isoformat()
    # Last pre-announcement and last clean snapshot per city, by room type (PR-covered areas).
    city = db.query(f"""
        WITH o AS (SELECT * FROM str_rent_panel
                   WHERE data_source = 'live' AND is_observed AND NOT scrape_incomplete
                     AND city IN ('vancouver', 'victoria')),
        b0 AS (SELECT city, max(year_month) FILTER (WHERE year_month < DATE '{ann}') AS pre_month,
                      max(year_month) AS post_month FROM o GROUP BY city),
        -- Same calendar month before the announcement: review counts are seasonal.
        b AS (SELECT b0.*, (SELECT max(o2.year_month) FROM o o2
                            WHERE o2.city = b0.city AND o2.year_month < DATE '{ann}'
                              AND month(o2.year_month) = month(b0.post_month)) AS same_season_pre_month
              FROM b0)
        SELECT o.city, o.room_type, b.pre_month, b.post_month, b.same_season_pre_month,
               max(o.n_active_pr_covered) FILTER (WHERE o.year_month = b.pre_month)  AS active_pre,
               max(o.n_active_pr_covered) FILTER (WHERE o.year_month = b.post_month) AS active_post,
               max(o.n_active_pr_covered) FILTER (WHERE o.year_month = b.same_season_pre_month) AS active_same_season_pre,
               max(o.n_reviewed_180d) FILTER (WHERE o.year_month = b.pre_month)      AS reviewed_pre,
               max(o.n_reviewed_180d) FILTER (WHERE o.year_month = b.post_month)     AS reviewed_post,
               max(o.n_reviewed_180d) FILTER (WHERE o.year_month = b.same_season_pre_month) AS reviewed_same_season_pre,
               max(o.share_commercial_host) FILTER (WHERE o.year_month = b.pre_month)  AS mlh_share_pre,
               max(o.share_commercial_host) FILTER (WHERE o.year_month = b.post_month) AS mlh_share_post,
               max(o.share_provincial_registration) FILTER (WHERE o.year_month = b.post_month) AS prov_registered_post,
               max(o.share_provincial_exempt_claim) FILTER (WHERE o.year_month = b.post_month) AS prov_exempt_claim_post
        FROM o JOIN b USING (city) GROUP BY ALL ORDER BY ALL""")
    # Victoria entire homes by principal-residence geography.
    geo = db.query(f"""
        WITH g AS (
            SELECT CASE WHEN NOT pr_exempt THEN 'covered'
                        WHEN pr_exempt_until IS NULL THEN 'never_covered'
                        ELSE 'opted_in_' || strftime(pr_exempt_until, '%Y-%m') END AS geography,
                   neighbourhood, year_month, n_active
            FROM str_nbhd_panel
            WHERE data_source = 'live' AND city = 'victoria' AND room_type = 'entire_home'
              AND is_observed AND NOT scrape_incomplete),
        areas AS (SELECT geography, string_agg(DISTINCT neighbourhood, ', ' ORDER BY neighbourhood) AS areas,
                         count(DISTINCT neighbourhood) AS n_areas
                  FROM g GROUP BY geography),
        a AS (SELECT geography, year_month, sum(n_active) AS n FROM g GROUP BY geography, year_month)
        SELECT a.geography, any_value(areas.n_areas) AS n_areas, any_value(areas.areas) AS areas,
               arg_max(a.n, a.year_month) FILTER (WHERE a.year_month < DATE '{ann}') AS active_pre,
               arg_max(a.n, a.year_month) AS active_post
        FROM a JOIN areas USING (geography) GROUP BY a.geography ORDER BY a.geography""")
    geo["pct_change"] = 100 * (geo["active_post"] / geo["active_pre"] - 1)
    vintage = db.query("""
        SELECT city, snapshot_date, n_total, round(completeness_ratio, 3) AS completeness_ratio,
               scrape_incomplete, round(share_new_listings, 3) AS share_new_listings
        FROM snapshot_months WHERE data_source = 'live' ORDER BY city, snapshot_date""")
    cpi = db.query("""
        SELECT city,
               100 * (max(cpi_rent) FILTER (WHERE year_month = DATE '2026-06-01')
                      / max(cpi_rent) FILTER (WHERE year_month = DATE '2023-09-01') - 1) AS pct_sep2023_jun2026,
               100 * (max(cpi_rent) FILTER (WHERE year_month = DATE '2026-06-01')
                      / max(cpi_rent) FILTER (WHERE year_month = DATE '2023-06-01') - 1) AS pct_jun2023_jun2026
        FROM cpi_monthly WHERE city IN ('vancouver', 'victoria', 'ottawa') GROUP BY city ORDER BY city""")
    return {"city_room": _records(city), "victoria_geography": _records(geo),
            "vintages": _records(vintage), "cpi_rent_change": _records(cpi)}


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
        results.append(event_study(df, source, "exempt"))
        results.append(event_study(df, source, "roomtype"))
        diagnostics[f"pretrend_slope_{source}"] = pretrend_slope(df, source)

        # A control market is eligible only with enough pre-announcement snapshots inside the
        # event window (>= 3 monthly synthetic, >= 2 quarterly live); a market observed only
        # post-treatment would just add noise to the month FE (live Seattle starts in 2025).
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
        "descriptives": descriptives(),
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
        if r["spec"] in ("S3", "S4", "S2-ES"):
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
    for r in out["results"]:
        ri = r["extra"].get("randomization_inference")
        if ri:
            ps = {k: round(v, 3) for k, v in ri["p"].items()} if r["spec"] != "S2-ES" else {}
            print(f"[{r['data_source']:9s}] {r['spec']:10s} RI p={ps} joint pre-trend p={ri.get('joint_p')} "
                  f"({ri['n_placebos']} placebos, {ri['n_controls']} controls) "
                  f"wild p={r['extra'].get('wild_bootstrap_p')}")
    print(json.dumps(out["rent"].get("mechanical_bound", {}), indent=1, default=str))
    print(json.dumps(out["descriptives"], indent=1, default=str))
    print(json.dumps(out["diagnostics"], indent=1, default=str))


if __name__ == "__main__":
    main()

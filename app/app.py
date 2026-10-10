"""Streamlit dashboard: BC Bill 35 short-term-rental evaluation.

    streamlit run app/app.py     (or `make app`)

The app never builds data itself. It reads the full local database when `make all`
has produced one, and otherwise the small committed bundle in data/app/ (refreshed
with `make app-data`). That is what a Streamlit Community Cloud deployment uses.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import config as cfg  # noqa: E402
from src import database as db  # noqa: E402
from src import models  # noqa: E402

BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
CITY_COLOR = {"vancouver": BLUE, "victoria": ORANGE, "ottawa": AQUA, "seattle": YELLOW}
ROOM_DASH = {"entire_home": "solid", "private_room": "dot"}
POLICY = [(cfg.ANNOUNCE_MONTH, "Announced"), (cfg.PHASE1_MONTH, "Enforced"), (cfg.PHASE2_MONTH, "Registry")]

st.set_page_config(page_title="BC Bill 35 - STR evaluation", layout="wide")

# --------------------------------------------------------------------------- data location
# Prefer a full local build; fall back to the committed bundle (the only option on a
# fresh clone or a Streamlit Community Cloud deployment, since the full database is
# gitignored). src.database resolves C.DB_PATH at query time, so repointing it here
# routes every query - including those made inside src.models - to the chosen file.
if not (cfg.DB_PATH.exists() and cfg.RESULTS_PATH.exists()):
    cfg.DB_PATH, cfg.RESULTS_PATH = cfg.APP_DB_PATH, cfg.APP_RESULTS_PATH
if not (cfg.DB_PATH.exists() and cfg.RESULTS_PATH.exists()):
    st.error("No data found. Run `make all` (or `python run.py all`) to build it.")
    st.stop()


@st.cache_data(show_spinner=False)
def city_panel() -> pd.DataFrame:
    df = db.query("SELECT * FROM str_rent_panel")
    df["year_month"] = pd.to_datetime(df["year_month"])
    return df


@st.cache_data(show_spinner=False)
def nbhd_panel(source: str) -> pd.DataFrame:
    return models.load_nbhd_panel(source)


@st.cache_data(show_spinner=False)
def saved_results() -> dict:
    return json.loads(cfg.RESULTS_PATH.read_text()) if cfg.RESULTS_PATH.exists() else {}


def coef_table(r: models.ModelResult) -> pd.DataFrame:
    t = pd.DataFrame(r.coefs)[["term", "estimate", "se", "p", "ci_low", "ci_high"] +
                              (["truth"] if any(c.get("truth") is not None for c in r.coefs) else [])]
    t["% effect"] = 100 * (pd.Series(t["estimate"]).apply(lambda b: pow(2.718281828, b)) - 1)
    return t


def add_policy(fig, row=None, col=None):
    for d, lab in POLICY:
        kw = {} if row is None else {"row": row, "col": col}
        fig.add_vline(x=pd.Timestamp(d), line_dash="dash", line_color="#52514e", line_width=1, **kw)
        fig.add_annotation(x=pd.Timestamp(d), y=1.02, yref="paper", text=lab, showarrow=False,
                           font=dict(size=10, color="#52514e"), xanchor="left")


# --------------------------------------------------------------------------- sidebar
panel = city_panel()
sources = sorted(panel.loc[panel.is_observed, "data_source"].unique())
st.sidebar.title("Bill 35 evaluation")
source = st.sidebar.radio("Data source", sources, index=0,
                          help="live = real Inside Airbnb snapshots (~quarterly). synthetic = calibrated "
                               "panel with known truth (pipeline validation, not evidence).")
if source == "synthetic":
    st.sidebar.warning("Synthetic data: estimates recover the simulated truth; they are not findings.")
cities = st.sidebar.multiselect("Cities", list(cfg.MARKETS), default=list(cfg.MARKETS),
                                format_func=lambda k: cfg.MARKETS[k].label)
rooms = st.sidebar.multiselect("Room types", ["entire_home", "private_room"], default=["entire_home", "private_room"])
window = st.sidebar.slider("Event-study window (months vs May 2024)", -28, 25, (cfg.EVENT_MIN, cfg.EVENT_MAX),
                           help="Must include the reference month t=-8 (Sep 2023). Endpoints are binned.")
drop_bad = st.sidebar.checkbox("Exclude truncated scrapes", value=True)

st.title("British Columbia's Short-Term Rental Accommodations Act (Bill 35)")
st.caption("Phase 1: principal-residence requirement (May 2024). Phase 2: provincial registry and platform "
           "de-listing (May-Jun 2025). Treated: entire homes in BC; controls: BC private rooms, BC exempt areas, "
           "Ottawa, Seattle.")

tab_trend, tab_reg, tab_rent, tab_data = st.tabs(["Listings vs rents", "Live regressions", "Rent transmission", "Data provenance"])

# --------------------------------------------------------------------------- trends
with tab_trend:
    sub = panel[(panel.data_source == source) & panel.city.isin(cities) & panel.room_type.isin(rooms) & panel.is_observed]
    if drop_bad:
        sub = sub[~sub.scrape_incomplete]
    index_mode = st.toggle("Index to last pre-announcement observation = 100", value=True)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.62, 0.38], vertical_spacing=0.08,
                        subplot_titles=("Active STR listings", "StatCan CPI rented accommodation (index, Sep 2023 = 100)"))
    for (c, rt), g in sub.groupby(["city", "room_type"]):
        g = g.sort_values("year_month")
        y = g["n_active"].astype(float)
        if index_mode:
            pre = g[g.year_month < pd.Timestamp(cfg.ANNOUNCE_MONTH)]
            if pre.empty:
                continue
            y = 100 * y / float(pre["n_active"].iloc[-1])
        fig.add_trace(go.Scatter(x=g.year_month, y=y, name=f"{cfg.MARKETS[c].label} - {rt.replace('_', ' ')}",
                                 mode="lines+markers", line=dict(color=CITY_COLOR[c], dash=ROOM_DASH[rt], width=2),
                                 marker=dict(size=6 if source == "live" else 3)), row=1, col=1)
    cpi = panel[(panel.data_source == source) & (panel.room_type == "entire_home") & panel.city.isin(cities)
                & panel.cpi_rent.notna()]
    for c, g in cpi.groupby("city"):
        base = g.loc[g.year_month == pd.Timestamp("2023-09-01"), "cpi_rent"]
        if base.empty:
            continue
        fig.add_trace(go.Scatter(x=g.year_month, y=100 * g.cpi_rent / float(base.iloc[0]),
                                 name=f"{cfg.MARKETS[c].label} CPI rent", line=dict(color=CITY_COLOR[c], width=2),
                                 showlegend=True), row=2, col=1)
    add_policy(fig)
    fig.update_layout(height=640, hovermode="x unified", legend=dict(orientation="h", y=-0.12),
                      margin=dict(t=60, l=40, r=20))
    st.plotly_chart(fig, width="stretch")

# --------------------------------------------------------------------------- regressions
with tab_reg:
    df = models.load_nbhd_panel(source, drop_incomplete=drop_bad)
    bc_sel = [c for c in cities if c in cfg.BC_MARKETS]
    ctrl_sel = [c for c in cities if c not in cfg.BC_MARKETS]
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Within-BC room-type DiD")
        if bc_sel:
            r = models.did_bc_roomtype(df, source, cities=bc_sel)
            st.dataframe(coef_table(r).style.format(precision=3), hide_index=True, width="stretch")
            st.caption(f"N = {r.nobs:,} | R² = {r.r2:.3f} | within R² = {r.r2_within:.3f} | clusters = {r.n_clusters} "
                       f"| FE: {r.fe}. ent_p2 is incremental to ent_p1.")
        else:
            st.info("Select Vancouver and/or Victoria.")
    with c2:
        st.subheader("Victoria: covered vs exempt areas")
        if "victoria" in cities:
            r2 = models.did_victoria_exempt(df, source)[0]
            st.dataframe(coef_table(r2).style.format(precision=3), hide_index=True, width="stretch")
            wb = r2.extra.get("wild_bootstrap_p", {})
            st.caption(f"N = {r2.nobs:,} | R² = {r2.r2:.3f} | clusters = {r2.n_clusters} | wild-bootstrap p: "
                       + ", ".join(f"{k}={v:.3f}" for k, v in wb.items() if v is not None))
    st.subheader("Event study")
    design = st.radio("Design", ["roomtype", "cross"], horizontal=True,
                      format_func=lambda d: "Entire vs private (BC)" if d == "roomtype" else "BC vs control cities")
    try:
        es = models.event_study(df[df.city.isin(cities)], source, design, window=tuple(window),
                                controls=ctrl_sel or None)
        c = pd.DataFrame(es.coefs).sort_values("event_time")
        ref_t = es.extra["ref"] * (3 if es.extra["freq"] == "Q" else 1)
        c = pd.concat([c, pd.DataFrame([{"event_time": ref_t, "estimate": 0, "ci_low": 0, "ci_high": 0}])]).sort_values("event_time")
        f = go.Figure()
        f.add_trace(go.Scatter(x=list(c.event_time) + list(c.event_time[::-1]), y=list(c.ci_high) + list(c.ci_low[::-1]),
                               fill="toself", fillcolor="rgba(42,120,214,0.15)", line=dict(width=0), name="95% CI"))
        f.add_trace(go.Scatter(x=c.event_time, y=c.estimate, mode="lines+markers", line=dict(color=BLUE), name="Estimate"))
        if "truth" in c and c["truth"].notna().any():
            t = c.dropna(subset=["truth"])
            f.add_trace(go.Scatter(x=t.event_time, y=t.truth, line=dict(color="#0b0b0b", dash="dot"), name="True DGP"))
        for x, lab in [(-7, "Announced"), (0, "Enforced"), (12, "Registry")]:
            f.add_vline(x=x, line_dash="dash", line_color="#52514e", annotation_text=lab)
        f.add_hline(y=0, line_color="#8a8984")
        f.update_layout(height=420, xaxis_title="Months relative to May 2024", yaxis_title="Log points",
                        hovermode="x unified", margin=dict(t=30))
        st.plotly_chart(f, width="stretch")
        pt = es.extra["pretrend_test"]
        st.caption(f"Pre-announcement joint Wald test: F = {pt['F'] if pt['F'] is None else round(pt['F'], 2)}, "
                   f"p = {pt['p'] if pt['p'] is None else round(pt['p'], 3)} | N = {es.nobs:,} | "
                   f"R² = {es.r2:.3f} | {es.notes}")
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Event study not estimable for this selection: {exc}")

# --------------------------------------------------------------------------- rent
with tab_rent:
    res = saved_results().get("rent", {})
    for key in ["rent_level_did", "rent_reduced_form", "rent_reduced_form_real", "rent_macro", "rent_on_str_live"]:
        if key in res:
            st.subheader(res[key]["label"])
            st.dataframe(pd.DataFrame(res[key]["coefs"]).style.format(precision=3), hide_index=True)
            st.caption(f"N = {res[key]['nobs']} | R² = {res[key]['r2']:.3f} | SE: {res[key]['se_type']}")
    if "mechanical_bound" in res:
        st.subheader("Mechanical upper bound on rent effects")
        st.dataframe(pd.DataFrame(res["mechanical_bound"]["rows"]), hide_index=True)
        st.caption(res["mechanical_bound"]["assumptions"])

# --------------------------------------------------------------------------- provenance
with tab_data:
    man = saved_results().get("manifest", {})
    st.json(man.get("insideairbnb", {}).get("coverage", {}))
    st.write({k: v.get("status") for k, v in man.items() if isinstance(v, dict) and "status" in v})
    snaps = db.query("""SELECT data_source, city, snapshot_date, n_total, round(completeness_ratio, 2) AS completeness,
                               scrape_incomplete FROM snapshot_months WHERE data_source = 'live' ORDER BY city, snapshot_date""")
    st.dataframe(snaps, hide_index=True, width="stretch")

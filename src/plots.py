"""Publication figures (matplotlib) -> assets/.

Conventions: one y-axis per panel (series of different scale are indexed to a common
pre-announcement base instead of using twin axes); fixed categorical colour order;
direct labels + legend; policy dates as dashed verticals; every figure states its
data source, and synthetic panels are labelled as such in the title.
"""
from __future__ import annotations

import json
import logging

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src import config as cfg  # noqa: E402
from src import database as db  # noqa: E402

log = logging.getLogger("plots")

# Reference categorical palette (validated, light mode), fixed order.
BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
INK, INK2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#8a8984", "#e6e5e0", "#fcfcfb"
ROOM_COLOR = {"entire_home": BLUE, "private_room": ORANGE}
ROOM_LABEL = {"entire_home": "Entire home/apt (treated)", "private_room": "Private room (control)"}
POLICY_LINES = [(cfg.ANNOUNCE_MONTH, "Announced\nOct 2023"), (cfg.PHASE1_MONTH, "Enforced\nMay 2024"),
                (cfg.PHASE2_MONTH, "Registry\nMay 2025")]

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": MUTED, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "font.size": 10, "axes.titlesize": 11, "axes.titleweight": "bold",
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": GRID,
    "grid.linewidth": 0.8, "lines.linewidth": 2.0, "legend.frameon": False,
})


def _policy_lines(ax, labels: bool = True, y: float = 0.99) -> None:
    # Stagger label heights: Announced and Enforced are only seven months apart.
    for (d, lab), dy in zip(POLICY_LINES, (0.0, -0.09, 0.0)):
        x = pd.Timestamp(d)
        ax.axvline(x, color=INK2, linestyle="--", linewidth=1.0, zorder=1)
        if labels:
            ax.text(x, y + dy, " " + lab, transform=ax.get_xaxis_transform(), va="top", ha="left",
                    fontsize=7.5, color=INK2,
                    bbox=dict(boxstyle="square,pad=0.1", facecolor=SURFACE, edgecolor="none", alpha=0.85))


def _date_axis(ax) -> None:
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 7]))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b\n%Y"))
    ax.set_xlim(pd.Timestamp(cfg.PANEL_START), pd.Timestamp(cfg.PANEL_END) + pd.Timedelta(days=20))


def _source_for_plots() -> str:
    live = db.query("SELECT count(*) n FROM str_rent_panel WHERE data_source='live' AND is_observed")["n"][0]
    return "live" if live > 0 else "synthetic"


def _synthetic_tag(src: str) -> str:
    return "  [SYNTHETIC DATA - NOT EVIDENCE]" if src == "synthetic" else ""


def _footer(fig, text: str) -> None:
    fig.text(0.01, 0.005, text, fontsize=7.5, color=MUTED, ha="left", va="bottom")


# =========================================================================== fig 1
def fig1_supply_trajectories() -> str:
    src = _source_for_plots()
    df = db.query(f"""
        SELECT city, room_type, year_month, n_active_pr_covered AS n, scrape_incomplete
        FROM str_rent_panel WHERE data_source = '{src}' AND is_observed
          AND city IN ('vancouver', 'victoria') ORDER BY year_month""")
    df["year_month"] = pd.to_datetime(df["year_month"])
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6), sharey=True)
    for ax, city in zip(axes, ["vancouver", "victoria"]):
        sub = df[df.city == city]
        for rt in ["entire_home", "private_room"]:
            s = sub[sub.room_type == rt].set_index("year_month").sort_index()
            ok = s[~s.scrape_incomplete.astype(bool)]
            base_rows = ok[ok.index < pd.Timestamp(cfg.ANNOUNCE_MONTH)]
            base = base_rows["n"].iloc[-1]
            idx = 100 * ok["n"] / base
            ax.plot(idx.index, idx.values, color=ROOM_COLOR[rt], marker="o" if src == "live" else None,
                    markersize=5, label=ROOM_LABEL[rt], zorder=3,
                    markeredgecolor=SURFACE, markeredgewidth=1.5)
            bad = s[s.scrape_incomplete.astype(bool)]
            if len(bad):
                ax.scatter(bad.index, 100 * bad["n"] / base, facecolors="none", edgecolors=ROOM_COLOR[rt],
                           s=40, zorder=3, label=None)
            ax.annotate(f"{idx.iloc[-1]:.0f}", (idx.index[-1], idx.iloc[-1]), xytext=(4, 0),
                        textcoords="offset points", fontsize=8.5, color=INK, va="center")
        ax.axhline(100, color=MUTED, linewidth=0.8)
        _policy_lines(ax)
        _date_axis(ax)
        ttl = cfg.MARKETS[city].label + (" - principal-residence-covered areas" if city == "victoria" else "")
        ax.set_title(ttl, loc="left")
    axes[0].set_ylabel("Active listings\n(index, last pre-announcement snapshot = 100)", fontsize=9)
    axes[0].legend(loc="lower left", fontsize=8.5)
    tag = ("Inside Airbnb listing snapshots (markers); hollow = truncated scrape, excluded"
           if src == "live" else "SYNTHETIC calibrated panel - pipeline illustration, not empirical data")
    fig.suptitle("Short-term rental supply in BC: entire homes vs private rooms" + _synthetic_tag(src), x=0.01, ha="left",
                 fontsize=13, fontweight="bold")
    _footer(fig, f"Source: {tag}. Active = scraped and (reviewed within 180 days or bookable).")
    fig.tight_layout(rect=(0, 0.05, 1, 0.97))
    path = cfg.ASSETS / "fig1_supply_trajectories.png"
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return str(path)


# =========================================================================== fig 2
def _es(results: dict, source: str, spec: str = "S3") -> dict | None:
    return next((r for r in results["results"] if r["spec"] == spec and r["data_source"] == source), None)


def fig2_event_study() -> str:
    res = json.loads(cfg.RESULTS_PATH.read_text())
    panels = [(s, _es(res, s)) for s in ["live", "synthetic"] if _es(res, s)]
    fig, axes = plt.subplots(1, len(panels), figsize=(6.4 * len(panels), 5.6), squeeze=False)
    for ax, (src, r) in zip(axes[0], panels):
        c = pd.DataFrame(r["coefs"]).sort_values("event_time")
        ref_t = r["extra"]["ref"] * (3 if r["extra"]["freq"] == "Q" else 1)
        c = pd.concat([c, pd.DataFrame([{"event_time": ref_t, "estimate": 0.0, "ci_low": 0.0, "ci_high": 0.0}])]
                      ).sort_values("event_time")
        pre = c.event_time < -7
        ax.axhline(0, color=MUTED, linewidth=1)
        for x, lab in [(-7, "Announced"), (0, "Enforced"), (12, "Registry")]:
            ax.axvline(x, color=INK2, linestyle="--", linewidth=1)
            ax.text(x, 0.98, " " + lab, transform=ax.get_xaxis_transform(), fontsize=7.5, color=INK2, va="top")
        ax.fill_between(c.event_time, c.ci_low, c.ci_high, color=BLUE, alpha=0.15, linewidth=0, step=None)
        ax.plot(c.event_time, c.estimate, color=BLUE, marker="o", markersize=5 if src == "live" else 3.5,
                markeredgecolor=SURFACE, markeredgewidth=1.2, label="Estimate, 95% CI (clustered by neighbourhood)")
        ref_lab = ("Reference: Sep 2023 (t=-8)" if r["extra"]["freq"] == "M"
                   else "Reference: quarter bin containing Aug-Sep 2023")
        ax.scatter([ref_t], [0], s=50, facecolors=SURFACE, edgecolors=INK, zorder=5, label=ref_lab)
        if src == "synthetic" and any(x.get("truth") is not None for x in r["coefs"]):
            t = pd.DataFrame(r["coefs"]).dropna(subset=["truth"]).sort_values("event_time")
            ax.plot(t.event_time, t.truth, color=INK, linestyle=":", linewidth=1.6, label="True DGP effect")
        pt = r["extra"]["pretrend_test"]
        ptxt = f"Pre-announcement joint test: F={pt['F']:.2f}, p={pt['p']:.2f}" if pt["F"] is not None else ""
        ax.text(0.0, -0.30, ptxt, transform=ax.transAxes, fontsize=8, color=INK2)
        ax.set_xlabel("Months relative to May 2024" + (" (quarterly bins)" if r["extra"]["freq"] == "Q" else ""))
        ax.set_ylabel("Log-point difference, entire vs private")
        ax.set_xlim(cfg.EVENT_MIN - 1.5, cfg.EVENT_MAX + 1.5)
        ax.set_title("Inside Airbnb snapshots (empirical)" if src == "live"
                     else "SYNTHETIC panel: estimator recovers known truth", loc="left")
        ax.legend(loc="upper left", fontsize=7.5, bbox_to_anchor=(0, -0.33), ncol=2)
        _ = pre
    fig.suptitle("Dynamic DiD: BC entire-home vs private-room listings (PR-covered areas)", x=0.01, ha="left",
                 fontsize=13, fontweight="bold")
    _footer(fig, "Unit and city x month fixed effects; endpoints binned at t=-12 and t=+24. "
                 "Positive pre-period drift would indicate non-parallel trends.")
    fig.tight_layout(rect=(0, 0.03, 1, 0.95))
    fig.subplots_adjust(bottom=0.30)
    path = cfg.ASSETS / "fig2_event_study.png"
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return str(path)


# =========================================================================== fig 3
def fig3_rent_transmission() -> str:
    src = _source_for_plots()
    str_df = db.query(f"""
        SELECT city, year_month, n_active_pr_covered AS n FROM str_rent_panel
        WHERE data_source = '{src}' AND room_type = 'entire_home' AND is_observed AND NOT scrape_incomplete""")
    cpi = db.query("SELECT city, year_month, cpi_rent, cpi_all_items FROM cpi_monthly WHERE year_month >= DATE '2022-01-01'")
    macro = db.query(f"""
        SELECT DISTINCT city, year_month, policy_rate, cmhc_vacancy_rate FROM str_rent_panel
        WHERE data_source = '{src}' AND room_type = 'entire_home' AND city IN ('vancouver','victoria','ottawa')""")
    for d in (str_df, cpi, macro):
        d["year_month"] = pd.to_datetime(d["year_month"])
    base_m = pd.Timestamp("2023-09-01")
    fig = plt.figure(figsize=(13, 7.2))
    gs = fig.add_gridspec(2, 3, height_ratios=[2.2, 1], hspace=0.35, wspace=0.12)
    top = [fig.add_subplot(gs[0, i]) for i in range(3)]
    for ax, city in zip(top, ["vancouver", "victoria", "ottawa"]):
        s = str_df[str_df.city == city].set_index("year_month").sort_index()["n"]
        if len(s):
            pre = s[s.index < pd.Timestamp(cfg.ANNOUNCE_MONTH)]
            b = pre.iloc[-1] if len(pre) else s.iloc[0]
            ax.plot(s.index, 100 * s / b, color=BLUE, marker="o" if src == "live" else None, markersize=4,
                    markeredgecolor=SURFACE, label="STR entire homes, active (PR-covered)")
        c = cpi[cpi.city == city].set_index("year_month").sort_index()
        cb = c.loc[base_m, "cpi_rent"]
        ax.plot(c.index, 100 * c["cpi_rent"] / cb, color=AQUA, label="CPI: Rented accommodation")
        ax.plot(c.index, 100 * (c["cpi_rent"] / c["cpi_all_items"]) / (cb / c.loc[base_m, "cpi_all_items"]),
                color=AQUA, linestyle="--", linewidth=1.5, label="Rented accommodation / All-items (real)")
        ax.axhline(100, color=MUTED, linewidth=0.8)
        _policy_lines(ax, labels=(city == "vancouver"))
        _date_axis(ax)
        ax.set_title(cfg.MARKETS[city].label + (" (control)" if city == "ottawa" else ""), loc="left")
        if city != "vancouver":
            ax.tick_params(labelleft=True)
    top[0].set_ylabel("Index, Sep 2023 = 100")
    top[0].legend(loc="lower left", fontsize=7.5)
    lo = min(a.get_ylim()[0] for a in top)
    hi = max(a.get_ylim()[1] for a in top)
    for a in top:
        a.set_ylim(lo, hi)
    ax_r = fig.add_subplot(gs[1, :2])
    pr = macro.drop_duplicates("year_month").sort_values("year_month")
    ax_r.step(pr.year_month, pr.policy_rate, where="post", color=INK, linewidth=1.8)
    ax_r.set_title("Bank of Canada policy rate (%)", loc="left")
    _policy_lines(ax_r, labels=False)
    _date_axis(ax_r)
    ax_v = fig.add_subplot(gs[1, 2])
    cm = db.query("SELECT * FROM ref_cmhc ORDER BY city, survey_year")
    for city, col in [("vancouver", BLUE), ("victoria", ORANGE), ("ottawa", AQUA)]:
        s = cm[cm.city == city]
        ax_v.plot(s.survey_year, s.vacancy_rate, color=col, marker="o", markersize=5, markeredgecolor=SURFACE)
        ax_v.annotate(cfg.MARKETS[city].label.split(" ")[0], (s.survey_year.iloc[-1], s.vacancy_rate.iloc[-1]),
                      xytext=(4, 0), textcoords="offset points", fontsize=8, va="center")
    ax_v.set_xticks([2022, 2023, 2024, 2025])
    ax_v.set_xlim(2021.7, 2025.8)
    ax_v.set_title("CMHC purpose-built vacancy (%, Oct)", loc="left")
    fig.suptitle("STR contraction vs rents: CPI rent keeps rising everywhere, including the Ottawa control"
                 + _synthetic_tag(src),
                 x=0.01, ha="left", fontsize=13, fontweight="bold")
    _footer(fig, f"Sources: StatCan Table 18-10-0004-01 (CPI, real); Bank of Canada V39079 (real); CMHC RMS "
                 f"(curated, see fixture provenance); STR = {'Inside Airbnb snapshots' if src == 'live' else 'SYNTHETIC panel'}. "
                 "CPI rent measures sitting-tenant rents under provincial increase caps.")
    fig.subplots_adjust(left=0.05, right=0.98, top=0.9, bottom=0.08)
    path = cfg.ASSETS / "fig3_rent_transmission.png"
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return str(path)


# =========================================================================== fig 4
def fig4_victoria_exempt() -> str:
    src = _source_for_plots()
    df = db.query(f"""
        SELECT pr_exempt, year_month, sum(n_active) n FROM str_nbhd_panel
        WHERE data_source = '{src}' AND city = 'victoria' AND room_type = 'entire_home'
          AND is_observed AND NOT scrape_incomplete
        GROUP BY ALL ORDER BY year_month""")
    df["year_month"] = pd.to_datetime(df["year_month"])
    fig, ax = plt.subplots(figsize=(8, 4.4))
    for ex, col, lab in [(False, BLUE, "PR-covered (Victoria, Saanich, Langford, ...)"),
                         (True, AQUA, "Exempt (Juan de Fuca, Gulf Islands, Metchosin, Highlands)")]:
        s = df[df.pr_exempt == ex].set_index("year_month")["n"]
        b = s[s.index < pd.Timestamp(cfg.ANNOUNCE_MONTH)].iloc[-1]
        ax.plot(s.index, 100 * s / b, color=col, marker="o" if src == "live" else None, markersize=5,
                markeredgecolor=SURFACE, label=lab)
        ax.annotate(f"{100 * s.iloc[-1] / b:.0f}", (s.index[-1], 100 * s.iloc[-1] / b), xytext=(4, 0),
                    textcoords="offset points", fontsize=8.5, va="center")
    ax.axhline(100, color=MUTED, linewidth=0.8)
    _policy_lines(ax)
    _date_axis(ax)
    ax.set_ylabel("Active entire homes, index (Aug 2023 = 100)")
    ax.legend(loc="lower left", fontsize=8)
    ax.set_title("Victoria CRD: covered vs exempt areas (within-province placebo)" + _synthetic_tag(src), loc="left")
    _footer(fig, "Source: " + ("Inside Airbnb snapshots" if src == "live" else "SYNTHETIC panel")
            + "; truncated scrapes excluded.")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    path = cfg.ASSETS / "fig4_victoria_exempt_placebo.png"
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return str(path)


def make_all() -> list[str]:
    cfg.ASSETS.mkdir(parents=True, exist_ok=True)
    return [fig1_supply_trajectories(), fig2_event_study(), fig3_rent_transmission(), fig4_victoria_exempt()]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for p in make_all():
        print(p)
    _ = np

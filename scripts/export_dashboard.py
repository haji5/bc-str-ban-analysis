"""Export the static dashboard's data (docs/) from the repo's committed bundle (data/app/).

    python scripts/export_dashboard.py [REPO_ROOT] [SITE_DIR]      # or: make site

Defaults: this repo and its docs/ folder (served by GitHub Pages). Writes the 12 datasets the
page reads to SITE_DIR/data/ and their provenance to SITE_DIR/datasets.json. Reads only
data/app/str_app.duckdb and data/app/model_results.json, so it works on a fresh clone.
Re-run after `make all && make app-data` to refresh the dashboard's numbers.
"""
import json
import math
import sys
from pathlib import Path

import duckdb

REPO = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
SITE = Path(sys.argv[2]) if len(sys.argv) > 2 else REPO / "docs"
OUT = SITE / "data"
OUT.mkdir(parents=True, exist_ok=True)
res = json.loads((REPO / "data/app/model_results.json").read_text())
con = duckdb.connect(str(REPO / "data/app/str_app.duckdb"), read_only=True)


def q(sql):
    return json.loads(con.execute(sql).df().to_json(orient="records", date_format="iso"))


def r4(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), 4)


def day(s):
    return None if s is None else str(s)[:10]


def write(name, rows):
    (OUT / f"{name}.json").write_text(json.dumps(rows, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{name:15s} {len(rows):4d} rows")


PHASE = {"antic": "anticipation", "p1": "phase1", "p2": "phase2"}
ES_SPECS = {"S3", "S4", "S2-ES"}

# 1. estimates ---------------------------------------------------------------
est = []
for r in res["results"]:
    if r["spec"] in ES_SPECS:
        continue
    ex = r.get("extra", {})
    wild = ex.get("wild_bootstrap_p") or {}
    ri = (ex.get("randomization_inference") or {}).get("p", {})
    suffix = ("exemptareas" if r["spec"] == "S2a" else
              r["label"].split("BC vs ")[-1] if r["spec"] == "S4b" else "")
    for c in r["coefs"]:
        ph = PHASE[c["term"].split("_")[-1]]
        est.append({
            "id": f"{r['data_source']}|{r['spec']}|{suffix}|{ph}", "spec": r["spec"], "label": r["label"],
            "data_source": r["data_source"], "phase": ph, "term": c["term"],
            "estimate": r4(c["estimate"]), "se": r4(c["se"]), "p": r4(c["p"]),
            "ci_low": r4(c["ci_low"]), "ci_high": r4(c["ci_high"]), "truth": r4(c.get("truth")),
            "wild_p": r4(wild.get(c["term"])), "ri_p": r4(ri.get(c["term"])),
            "nobs": r["nobs"], "n_clusters": r["n_clusters"], "fe": r["fe"],
        })
write("estimates", est)

# 2. event_study + 7. pretrend -----------------------------------------------
es, pt = [], []
for r in res["results"]:
    if r["spec"] not in ES_SPECS:
        continue
    ex = r["extra"]
    scale = 3 if ex["freq"] == "Q" else 1
    ref_t = ex["ref"] * scale
    rows = [{"id": f"{r['data_source']}|{r['spec']}|{c['event_time']}", "spec": r["spec"], "label": r["label"],
             "data_source": r["data_source"], "term": c["term"], "event_time": c["event_time"],
             "estimate": r4(c["estimate"]), "se": r4(c["se"]), "ci_low": r4(c["ci_low"]),
             "ci_high": r4(c["ci_high"]), "truth": r4(c.get("truth"))} for c in r["coefs"]]
    rows.append({"id": f"{r['data_source']}|{r['spec']}|{ref_t}", "spec": r["spec"], "label": r["label"],
                 "data_source": r["data_source"], "term": "reference", "event_time": ref_t, "estimate": 0.0,
                 "se": 0.0, "ci_low": 0.0, "ci_high": 0.0,
                 "truth": 0.0 if r["data_source"] == "synthetic" and r["spec"] != "S4" else None})
    es += sorted(rows, key=lambda x: x["event_time"])
    t = ex["pretrend_test"]
    ri = ex.get("randomization_inference") or {}
    pt.append({"id": f"{r['data_source']}|{r['spec']}", "spec": r["spec"], "label": r["label"],
               "data_source": r["data_source"], "F": r4(t["F"]), "p": r4(t["p"]), "df": t["df"],
               "ri_p": r4(ri.get("joint_p")), "freq": "quarterly" if ex["freq"] == "Q" else "monthly",
               "nobs": r["nobs"], "n_clusters": r["n_clusters"], "notes": r["notes"]})
sl = res["diagnostics"]["pretrend_slope_live"]
pt.append({"id": "live|slope", "spec": "slope", "label": "Differential linear pre-trend (per year)",
           "data_source": "live", "F": None, "p": r4(sl["p"]), "df": None, "ri_p": None, "freq": None,
           "nobs": None, "n_clusters": None,
           "notes": f"estimate {sl['estimate_per_year']:+.4f}/yr, se {sl['se']:.4f}"})
write("event_study", es)
write("pretrend", pt)

# 3. headline ------------------------------------------------------------------
geo = {g["geography"]: g for g in res["descriptives"]["victoria_geography"]}
cr = {(x["city"], x["room_type"]): x for x in res["descriptives"]["city_room"]}
cpi = {x["city"]: x for x in res["descriptives"]["cpi_rent_change"]}


def hl(key, label, pre_m, post_m, pre, post, unit):
    ch = (100 * (post / pre - 1)) if unit == "count" else (post - pre)
    return {"key": key, "label": label, "pre_month": pre_m, "post_month": post_m, "pre": r4(pre),
            "post": r4(post), "change": round(ch, 1), "unit": unit}


vic, van = cr[("victoria", "entire_home")], cr[("vancouver", "entire_home")]
reg = q("""SELECT sum(share_provincial_registration * n_active) / sum(n_active) AS reg,
                  sum(share_provincial_exempt_claim * n_active) / sum(n_active) AS ex
           FROM str_rent_panel WHERE data_source = 'live' AND room_type = 'entire_home'
             AND city IN ('vancouver', 'victoria') AND year_month = DATE '2026-06-01'""")[0]
headline = [
    hl("vic_covered", "Victoria CRD entire homes, covered areas", "2023-08-01", "2026-06-01",
       geo["covered"]["active_pre"], geo["covered"]["active_post"], "count"),
    hl("vic_exempt", "Victoria CRD entire homes, never-covered areas (Juan de Fuca, Southern Gulf Islands)",
       "2023-08-01", "2026-06-01", geo["never_covered"]["active_pre"], geo["never_covered"]["active_post"], "count"),
    hl("vic_saltspring", "Salt Spring Island entire homes (exempt until its Nov 2025 opt-in)", "2023-08-01",
       "2026-06-01", geo["opted_in_2025-11"]["active_pre"], geo["opted_in_2025-11"]["active_post"], "count"),
    hl("vic_private_covered", "Victoria CRD private rooms, covered areas", "2023-08-01", "2026-06-01",
       cr[("victoria", "private_room")]["active_pre"], cr[("victoria", "private_room")]["active_post"], "count"),
    hl("van_entire", "Vancouver entire homes", "2023-09-01", "2026-06-01", van["active_pre"], van["active_post"], "count"),
    hl("van_entire_same_season", "Vancouver entire homes, same season (Jun 2023 vs Jun 2026)", "2023-06-01",
       "2026-06-01", van["active_same_season_pre"], van["active_post"], "count"),
    hl("van_private", "Vancouver private rooms", "2023-09-01", "2026-06-01",
       cr[("vancouver", "private_room")]["active_pre"], cr[("vancouver", "private_room")]["active_post"], "count"),
    hl("vic_multi_host", "Multi-listing-host share, Victoria entire homes", "2023-08-01", "2026-06-01",
       100 * vic["mlh_share_pre"], 100 * vic["mlh_share_post"], "pp"),
    hl("van_multi_host", "Multi-listing-host share, Vancouver entire homes", "2023-09-01", "2026-06-01",
       100 * van["mlh_share_pre"], 100 * van["mlh_share_post"], "pp"),
    hl("bc_registration", "BC entire homes showing a provincial registration number", "2023-09-01",
       "2026-06-01", 0.0, 100 * reg["reg"], "pp"),
    hl("bc_exempt_claim", "BC entire homes showing 'Provincial registration number: Exempt'", "2023-09-01",
       "2026-06-01", 0.0, 100 * reg["ex"], "pp"),
]
for c in ["victoria", "vancouver", "ottawa"]:
    headline.append(hl(f"cpi_{c}", f"CPI rented accommodation, {c.title()} (Sep 2023 = 100)", "2023-09-01",
                       "2026-06-01", 100.0, 100 + cpi[c]["pct_sep2023_jun2026"], "index"))
write("headline", headline)

# 4. macro -------------------------------------------------------------------
write("macro", [{**r, "month": day(r["month"])} for r in q("""
    SELECT city, year_month AS month, cpi_rent, cpi_all_items, policy_rate,
           cmhc_vacancy_rate AS vacancy_rate, cmhc_avg_rent_2br AS avg_rent_2br
    FROM str_rent_panel WHERE data_source = 'live' AND room_type = 'entire_home'
      AND city IN ('victoria', 'vancouver', 'ottawa') ORDER BY city, year_month""")])

# 5. nbhd_change / 6. nbhd_series --------------------------------------------
cov = """CASE WHEN NOT pr_exempt THEN 'covered' WHEN pr_exempt_until IS NULL THEN 'exempt'
              ELSE 'exempt until ' || strftime(pr_exempt_until, '%b %Y') END"""
nc = q(f"""
    WITH o AS (SELECT * FROM str_nbhd_panel WHERE data_source = 'live' AND is_observed AND NOT scrape_incomplete
                 AND room_type = 'entire_home' AND city IN ('victoria', 'vancouver')),
    b AS (SELECT city, max(year_month) FILTER (WHERE year_month < DATE '2023-10-01') AS pre, max(year_month) AS post
          FROM o GROUP BY city)
    SELECT o.city, o.neighbourhood, any_value({cov}) AS coverage, any_value(b.pre) AS pre_month,
           max(n_active) FILTER (WHERE year_month = b.pre) AS n_pre,
           max(n_active) FILTER (WHERE year_month = b.post) AS n_post,
           max(share_commercial_host) FILTER (WHERE year_month = b.pre) AS multi_host_pre,
           max(share_commercial_host) FILTER (WHERE year_month = b.post) AS multi_host_post,
           max(share_licensed) FILTER (WHERE year_month = b.post) AS licensed_post
    FROM o JOIN b USING (city) GROUP BY o.city, o.neighbourhood ORDER BY o.city, o.neighbourhood""")
for r in nc:
    r["pre_month"] = day(r["pre_month"])
    r["change_pct"] = round(100 * (r["n_post"] / r["n_pre"] - 1), 1) if r["n_pre"] else None
    for k in ("multi_host_pre", "multi_host_post", "licensed_post"):
        r[k] = None if r[k] is None else round(r[k], 3)
write("nbhd_change", [{k: r[k] for k in ["city", "neighbourhood", "coverage", "pre_month", "n_pre", "n_post",
                                          "change_pct", "multi_host_pre", "multi_host_post", "licensed_post"]}
                      for r in nc])
write("nbhd_series", [{**r, "month": day(r["month"])} for r in q("""
    SELECT city, neighbourhood, year_month AS month, n_active FROM str_nbhd_panel
    WHERE data_source = 'live' AND is_observed AND NOT scrape_incomplete AND room_type = 'entire_home'
      AND city IN ('victoria', 'vancouver') ORDER BY city, neighbourhood, year_month""")])

# 8. rent_bound / 9. rent_models ---------------------------------------------
write("rent_bound", [{"city": b["city"], "pre_month": b["pre_month"], "post_month": b["post_month"],
                      "active_pre": b["active_pre"], "active_post": b["active_post"],
                      "units_removed": int(b["units_removed"]), "renter_households": b["renter_households"],
                      "supply_shock_pct": round(b["supply_shock_pct"], 2),
                      "rent_effect_low": round(b["rent_effect_pct_range"][0], 2),
                      "rent_effect_high": round(b["rent_effect_pct_range"][1], 2)}
                     for b in sorted(res["rent"]["mechanical_bound"]["rows"], key=lambda x: x["city"])])
rm = []
for model in ["rent_level_did", "rent_reduced_form", "rent_reduced_form_real", "rent_macro", "rent_on_str_live"]:
    m = res["rent"][model]
    for c in m["coefs"]:
        rm.append({"id": f"{model}|{c['term']}", "model": model, "label": m["label"], "term": c["term"],
                   "estimate": r4(c["estimate"]), "se": r4(c["se"]), "p": r4(c["p"]), "ci_low": r4(c["ci_low"]),
                   "ci_high": r4(c["ci_high"]), "nobs": m["nobs"], "r2": r4(m["r2"]), "se_type": m["se_type"]})
write("rent_models", rm)

# 10. snapshots / 11. supply / 12. victoria_split ----------------------------
write("snapshots", [{**r, "snapshot_date": day(r["snapshot_date"]), "month": day(r["month"]),
                     "completeness": r4(r["completeness"]), "new_ids": r4(r["new_ids"])} for r in q("""
    SELECT city, snapshot_date, year_month AS month, n_total, completeness_ratio AS completeness,
           scrape_incomplete AS incomplete, share_new_listings AS new_ids
    FROM snapshot_months WHERE data_source = 'live' ORDER BY city, snapshot_date""")])
write("supply", [{**r, "month": day(r["month"]), "snapshot_date": day(r["snapshot_date"]),
                  "multi_host_share": r4(r["multi_host_share"]), "registration_share": r4(r["registration_share"]),
                  "exempt_claim_share": r4(r["exempt_claim_share"])} for r in q("""
    SELECT city, room_type, year_month AS month, snapshot_date, scrape_incomplete AS incomplete, n_active,
           n_active_pr_covered AS n_active_covered, share_commercial_host AS multi_host_share,
           coalesce(share_provincial_registration, 0) AS registration_share,
           coalesce(share_provincial_exempt_claim, 0) AS exempt_claim_share
    FROM str_rent_panel WHERE data_source = 'live' AND is_observed ORDER BY city, room_type, year_month""")])
write("victoria_split", [{**r, "month": day(r["month"])} for r in q("""
    SELECT year_month AS month, room_type,
           CASE WHEN NOT pr_exempt THEN 'covered' WHEN pr_exempt_until IS NULL THEN 'exempt' ELSE 'salt_spring' END AS coverage,
           bool_or(scrape_incomplete) AS incomplete, sum(n_active)::INT AS n_active
    FROM str_nbhd_panel WHERE data_source = 'live' AND city = 'victoria' AND is_observed
    GROUP BY ALL ORDER BY month, room_type, coverage""")])

# Provenance: what the page's "Sources" popover shows for each dataset ----------
DATASETS = {
    "estimates": ("DiD estimates", "Difference-in-differences coefficients for every specification (real and synthetic data), with clustered SEs, CIs, randomization-inference p (preferred design), wild-bootstrap p and simulated truth. From model_results.json."),
    "event_study": ("Event-study coefficients", "Event-study coefficients by months relative to May 2024 for the exempt-area, room-type and cross-market designs, plus the reference point (0). From model_results.json."),
    "headline": ("Headline KPIs", "Before/after figures for the headline metrics (covered, never-covered and Salt Spring listings, Vancouver incl. same-season, multi-host share, registry numbers and 'Exempt' claims, CPI rent), computed from the panel; Victoria baseline Aug 2023, others Sep 2023."),
    "macro": ("CPI, rates and vacancy", "Monthly StatCan CPI (rented accommodation, all items), Bank of Canada policy rate and CMHC vacancy / 2-bedroom rent (each survey from its publication) for Victoria, Vancouver and Ottawa. From str_rent_panel."),
    "nbhd_change": ("Neighbourhood change", "Per neighbourhood: active entire homes at the last pre-announcement snapshot vs Jun 2026, principal-residence coverage, multi-host and licence-number shares. From str_nbhd_panel."),
    "nbhd_series": ("Neighbourhood trends", "Active entire-home listings per neighbourhood and complete snapshot, Victoria CRD and Vancouver. From str_nbhd_panel."),
    "pretrend": ("Pre-trend tests", "Joint Wald tests on pre-announcement leads for each event study, randomization-inference p for the exempt-area design (three control areas), and the differential linear pre-trend. From model_results.json."),
    "rent_bound": ("Mechanical rent bound", "Upper bound on rent effects implied by units removed relative to renter households, by city. From model_results.json."),
    "rent_models": ("Rent regressions", "Rent models: BC vs Ottawa CPI rent DiD, reduced form, macro controls and rent on STR supply, Driscoll-Kraay SEs (descriptive: three cities). From model_results.json."),
    "snapshots": ("Snapshot coverage", "Every Inside Airbnb snapshot used: date, listing count, completeness vs neighbouring snapshots, the truncation flag and the share of never-seen listing IDs. From snapshot_months."),
    "supply": ("Listings by market", "Active Inside Airbnb listings per observed snapshot, by city and room type, with multi-listing-host share, provincial registry-number share and 'Exempt'-claim share. From str_rent_panel (live, observed months)."),
    "victoria_split": ("Victoria covered vs exempt", "Victoria CRD active listings summed over neighbourhoods covered by the principal-residence rule, never covered (Juan de Fuca, Southern Gulf Islands), or Salt Spring Island (exempt until its Nov 2025 opt-in), per snapshot and room type. From str_nbhd_panel."),
}
manifest = {k: {"title": t, "description": d, "file": f"data/{k}.json"} for k, (t, d) in DATASETS.items()}
(SITE / "datasets.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print(f"datasets.json   {len(manifest):4d} datasets")

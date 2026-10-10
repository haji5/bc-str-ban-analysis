# Did BC's short-term rental ban work? Evidence from Bill 35, 2022-2026

**Headline findings (real Inside Airbnb data, 52 snapshots, Jun 2022-Jun 2026)**

1. **Supply fell where Bill 35 changed the rules.** In the Victoria CRD, active entire-home listings in areas covered by the principal-residence requirement fell **36%**. Exempt rural areas in the same region were flat. The within-region DiD gives **−27%** at Phase 1 (May 2024) and a further **−15%** at Phase 2 (registry, May 2025); wild-bootstrap p = 0.007 and 0.04.
2. **Vancouver, which already had a 2018 bylaw, did not shrink.** Entire homes dipped 22% at the June 2025 registry deadline and were back **+5%** above their pre-announcement level by June 2026.
3. **The room-type DiD specified in the brief understates the effect.** Private rooms are partly treated: the registry covers all STRs, and 74% of private-room listings are run by multi-listing hosts. The DiD gives −13% (OLS, p = 0.07) or −16% (Poisson, p = 0.003) for Phase 1, with clean pre-trends (p = 0.25).
4. **No detectable rent relief.** CPI rented accommodation rose 19.5% in Victoria, 11.5% in Vancouver and 20.6% in Ottawa (Sep 2023 → Jun 2026). Victoria's lost STRs equal about 1.7% of renter households, which bounds any rent effect at −0.4% to −3.3%. That is below the noise floor of the CPI series.

| KPI (active listings, PR-covered areas) | Pre (Aug/Sep 2023) | Jun 2026 | Change |
|---|---:|---:|---:|
| Victoria CRD entire homes, covered areas | 3,083 | 1,988 | **−35.5%** |
| Victoria CRD entire homes, exempt areas | 808 | 829 | +2.6% |
| Victoria CRD private rooms, covered areas | 459 | 345 | −24.8% |
| Vancouver entire homes | 4,795 | 5,032 | +4.9% |
| Vancouver private rooms | 1,075 | 1,100 | +2.3% |
| Multi-listing-host share, Victoria entire homes | 46.1% | 37.6% | −8.5 pp |
| BC entire homes showing a provincial registration number | 0% | 79% | +79 pp |
| CPI rented accommodation: Victoria / Vancouver / Ottawa | 100 | 119.5 / 111.5 / 120.6 | none attributable |

| Causal estimate (live data) | Phase 1 (May 2024) | Phase 2, incremental (May 2025) | Pre-trend |
|---|---:|---:|---|
| **Victoria covered vs exempt** (preferred) | **−0.316** (0.074) | **−0.160** (0.071) | anticipation −0.109 (0.034) |
| Room-type DiD, BC, OLS log(1+n) | −0.134 (0.073) | +0.064 (0.044) | joint lead test p = 0.25 |
| Room-type DiD, BC, PPML | −0.179 (0.061) | +0.048 (0.052) | |
| Cross-market BC vs Ottawa | −0.216 (0.046) | −0.062 (0.032) | **fails** (lead +0.13, p < 0.001); do not use |

Coefficients are log points; neighbourhood-clustered standard errors are in parentheses. The full table is in `data/processed/regression_table.csv`. The briefing memo is [`memo/bc_str_policy_memo.md`](memo/bc_str_policy_memo.md).

![Supply trajectories](assets/fig1_supply_trajectories.png)

![Event study](assets/fig2_event_study.png)

Also produced: `assets/fig3_rent_transmission.png` (STR supply vs CPI rent, policy rate and CMHC vacancy) and `assets/fig4_victoria_exempt_placebo.png` (covered vs exempt areas).

---

## Reproduce

```bash
make install        # venv + dependencies (Python 3.10-3.13)
make all            # data -> sql -> model (+figures) -> test; live data with automatic fallback
make all OFFLINE=1  # never touches the network: fixtures + synthetic panel only
make app            # Streamlit dashboard
```

Without GNU make (e.g. stock Windows), `python run.py all` runs the same steps, and `python run.py all --offline` is the offline equivalent. Individual targets are `data`, `sql`, `model`, `plots`, `test` and `app`.

A full live run downloads about 135 MB from Inside Airbnb (listings files only, never calendars), StatCan and the Bank of Canada, then builds and estimates in under a minute.

## Design review: what the brief got right, and what changed

The design was reviewed against the data before any code was written. The changes below are deliberate.

| Brief | Finding when tested against data | Resolution |
|---|---|---|
| Scrape Inside Airbnb for 2022-2026 archives | The site publishes only the trailing 12 months (Dec 2025-Sep 2026), all post-treatment. That alone cannot identify anything | Older files still exist on the CDN. A bounded probe found 36 unlisted snapshots back to Jun 2022, stored in `data/fixtures/known_archive_snapshots.json` |
| City × room-type × month panel | 2 BC cities × 2 room types = **4 clusters**, too few for cluster-robust SEs | Estimation runs at neighbourhood × room type (47 BC clusters). City-level tables are kept for reporting |
| Private rooms are an untreated control | 74% of private-room listings belong to multi-listing hosts, and the Phase-2 registry covers every STR. Covered-area private rooms in Victoria fell 25% | Room-type DiD is reported as a **lower bound**. The **exempt-area design** (Juan de Fuca, Gulf Islands, Metchosin, Highlands) is added as the preferred within-BC control, plus a triple difference |
| Normalise the event study to t = −1 | t = −1 (Apr 2024) is six months after the Oct 2023 announcement, so anticipation would contaminate the baseline | Reference is **t = −8 (Sep 2023)**. A separate anticipation term enters the static DiD |
| Ottawa + Seattle as cross-market controls | Ottawa fails pre-trends (BC out-grew it in mid-2023). Seattle has no public archive before 2025 | Cross-market is reported with pre-trend diagnostics and is not relied on. Controls need ≥ 2 pre-announcement snapshots in the window |
| Monthly panel | Real snapshots are roughly quarterly. Several are truncated (all March 2026 files, Vancouver Mar 2025), and the truncation is spatially uneven, which inflated one estimate 3× | Months without a snapshot stay `is_observed = false` (never interpolated). Live event studies use quarterly bins. Snapshots below 75% of their neighbours are flagged `scrape_incomplete` and excluded |
| CPI "Rented accommodation" sub-index | Correct choice. StatCan publishes only this aggregate (no "Rent" sub-index) for CMAs. It is a sitting-tenant measure under BC's increase cap | Used as the rent proxy, with level DiD as the primary spec. In y/y growth a one-off level shift mechanically shows up as −x then +x exactly when the Phase-2 dummy switches on |
| Dual-axis rent figure | Two y-scales let the chart-maker pick the apparent correlation | Fig 3 indexes STR supply and rents to a common base (Sep 2023 = 100) on one axis, with policy rate and vacancy in their own panels |
| Synthetic fallback data | Estimates on simulated data are not findings | Synthetic data is a **separate `data_source`**: it is never mixed into live estimates and never regressed against real rents. It serves as a parameter-recovery test with known truth |

## Method

**Data layer.** `src/ingest.py` discovers published snapshots, adds the known archive list and any manual drop-ins, then downloads `listings.csv.gz` with backoff. It fetches StatCan Table 18-10-0004-01 via WDS (mapping series by the response's own coordinate) and the BoC policy rate via Valet, and loads curated CMHC RMS benchmarks. Each source falls back to a fixture on failure, and `data/raw/manifest.json` records which path each one took.

**SQL layer** (`queries/`, DuckDB, policy dates injected as session variables):

- `01_clean_listings.sql`: parse `$1,234.00` prices (winsorised to $10-$10,000); deduplicate re-scraped rows (keep the latest scrape); flag activity (scraped, and reviewed ≤ 180 days or bookable); map room types; flag commercial hosts, licences and exempt areas.
- `02_aggregate_monthly.sql`: scrape-completeness flags; neighbourhood × room × month and city × room × month aggregates (active count, median price, mean `availability_365`, commercial share), with zero-filled empty cells.
- `03_build_panel.sql`: complete Jan 2022-Jun 2026 spines (`str_rent_panel`, `str_nbhd_panel`); policy indicators; CPI (levels, y/y, real), BoC rate, and CMHC joined as-of the October survey.

**Models** (`src/models.py`, pyfixest + statsmodels). Each runs on `live` and `synthetic`:

| Spec | Model |
|---|---|
| S1 | `log(1+active) ~ Entire×{Antic, Post2024, Post2025} \| unit + city×month`, CRV1 by neighbourhood. Variants: per city, PPML, reviewed-in-180d outcome, room × calendar-month FE |
| S2a/b | Victoria covered vs exempt (unit + month FE, wild-cluster bootstrap); triple difference |
| S3 | Event study t ∈ [−12, 24], ref t = −8, binned endpoints, joint pre-announcement Wald test; quarterly bins for live data |
| S4 | Cross-market event study (trimmed to window) and DiD with leave-one-control-out and wild bootstrap |
| S5 | Rent: level and y/y DiD of CPI rented accommodation, BC CMAs vs Ottawa (Driscoll-Kraay SEs); association with observed STR counts plus policy rate; mechanical bound |

**Synthetic validation.** The synthetic generator (`src/synthetic.py`) produces listing-level microdata in Inside Airbnb's schema. It is calibrated to the real anchors and injects duplicates, missing prices, dormant listings, scrape-coverage shocks, a partly treated control and commercial-host exits. The estimators recover the known truth:

| Synthetic check | Estimate (SE) | Truth |
|---|---:|---:|
| S1 room-type, Phase 1 | −0.070 (0.022) | −0.090 |
| S1 PPML, Phase 1 | −0.080 (0.015) | −0.090 |
| S2a exempt-area, Phase 1 / Phase 2 | −0.261 (0.022) / −0.167 (0.030) | −0.260 / −0.150 |
| S4b cross-market, Phase 1 | −0.168 (0.025) | −0.160 |

`tests/test_pipeline.py` (23 tests) covers:

- an SQL unit test on hand-written edge cases;
- no NULL or duplicate primary keys in all five tables;
- complete monthly spines with no gaps;
- policy-flag consistency and CPI join coverage;
- the offline fixtures and deterministic synthetic generation;
- non-null finite coefficients with SE > 0;
- parameter recovery within 3 SE;
- event-study window shape and pre-trend.

## Limitations

- **Snapshots are quarterly**, and some 2024 quarters are missing for some cities. Monthly dynamics come only from synthetic data.
- **"Active" relies on reviews and availability.** Inside Airbnb's 2025-26 files report higher availability, so levels shift across vintages. City × month FE absorbs this when the shift is proportional across room types.
- **Prices are not comparable across vintages.** Inside Airbnb changed its price fields in 2026, so price is reported but not modelled causally.
- **Rents.** Three CMA series with ±3-5 pt quarterly noise cannot detect a 1-3% effect. Asking-rent data and conversion tracking are needed (see the memo).
- **Provenance quality.** CMHC values are curated by hand with a provenance flag per row (`data/fixtures/README.md`), and several 2022 and 2025 entries need verification. Renter-household counts in the mechanical bound are 2021 Census approximations.
- **Exempt-area status** follows the 2024 exemption list for regional-district electoral areas and municipalities under 10,000 people. Verify any later opt-ins in `src/config.py`.

## Layout

```
Makefile, run.py         task runner (make / cross-platform)
src/config.py            policy calendar, markets, exempt areas, endpoints
src/ingest.py            downloads + fallback + manifest
src/synthetic.py         calibrated synthetic panel with known truth
src/database.py          DuckDB build; executes queries/*.sql
src/models.py            S1-S5 specifications -> data/processed/model_results.json
src/plots.py             assets/fig1-fig4
queries/01-03_*.sql      pure SQL transformation layer
app/app.py               Streamlit dashboard (filters, window slider, live regressions)
tests/test_pipeline.py   pytest suite
data/fixtures/           offline fixtures (see data/fixtures/README.md for provenance)
memo/                    Deputy Minister briefing note
```

Data: Inside Airbnb (CC BY 4.0), Statistics Canada (Open Government Licence - Canada), Bank of Canada, CMHC.

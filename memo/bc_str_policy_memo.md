# BRIEFING NOTE: Deputy Minister, Ministry of Housing and Municipal Affairs

> *Independent portfolio analysis written in briefing-note format. It was not commissioned by, prepared for, or endorsed by the Government of British Columbia.*

**Subject:** Early evidence on the *Short-Term Rental Accommodations Act* (Bill 35): listing supply and rents, Jan 2022 to Jun 2026
**Classification:** For decision support. Analytical; not legal advice
**Date:** October 2026 · **Data through:** June 2026

---

## 1. Executive summary

- **Bill 35 reduced short-term-rental (STR) supply where it changed the rules, and barely moved it where rules already existed.** In the Capital Regional District, active entire-home listings in areas covered by the principal-residence requirement fell **35%** (3,133 → 2,033, Aug 2023 → Jun 2026). Listings in the never-covered areas (Juan de Fuca, Southern Gulf Islands) rose **6%**. Against the exempt areas, Phase 1 (May 2024) cut covered-area listings by **32%**. That effect is robust: randomization inference gives p = 0.011 across every alternative choice of control areas. Phase 2 (registry, May 2025) added a further 11% decline, but that increment cannot be told apart from chance (p = 0.27).
- **Vancouver, which has enforced a principal-residence bylaw since 2018, shows no lasting decline.** Entire-home listings dipped 22% around the June 2025 registry deadline. By June 2026 they were 5% above their September 2023 level, and 9% above June 2023. The June 2026 snapshot contains an unusually high share of listings never seen before (19% against 9-13%), so the size of the rebound is uncertain. Bill 35 there reads as a compliance and registration measure, not a supply shock.
- **There is no detectable rent relief in the price data.** Since September 2023, StatCan's CPI for rented accommodation rose **19.5%** in Victoria, **11.5%** in Vancouver and **20.6%** in Ottawa, which had no comparable provincial policy. From a June 2023 base the ordering changes (19.2%, 14.4%, 15.4%). The STR units removed in Victoria amount to about **1.7% of renter households**. Even if every one moved to long-term rental, the implied rent effect (−0.4% to −3.3%) is smaller than the quarter-to-quarter noise in the CMA rent index.
- **Recommendation:** Present Bill 35 as a housing-use and compliance tool that delivered a real but geographically concentrated supply response, not as an affordability lever with measurable rent effects. Invest in conversion tracking and asking-rent data before claiming rent outcomes.

## 2. How the effect is identified

Inside Airbnb's public site lists only the latest 12 months of data. We assembled **52 snapshots** for Vancouver, Victoria, Ottawa and Seattle: the 12 published ones plus 40 unlisted archives (2022-2025) recovered directly from its server. Four truncated scrapes are excluded, giving roughly quarterly coverage with five observations before the October 2023 announcement in each BC market. Three comparisons are used, each at the neighbourhood level (49 BC neighbourhoods; standard errors clustered by neighbourhood):

| Design | Treated | Control | Strength | Weakness |
|---|---|---|---|---|
| **A. Room type (as briefed)** | BC entire homes | BC private rooms, same city and month | Removes all city-wide shocks (tourism, scrape coverage) | Control is **partly treated**: the registry covers every STR, and covered-area private rooms in Victoria fell 25%. Estimates are a **lower bound** |
| **B. Exempt areas (preferred)** | Victoria CRD covered areas, including Metchosin and Highlands | Juan de Fuca, Southern Gulf Islands; Salt Spring Island until its Nov 2025 opt-in | Same region, platforms and tourist season; untreated by Phase 1; pre-trends match | Only 3 control areas → randomization inference; rural/urban differences |
| **C. Cross-market** | BC entire homes | Ottawa entire homes | Independent macro control | **Fails the pre-trend test** (BC out-grew Ottawa in mid-2023; p = 0.001). Not used for inference |

Event-study estimates use the last snapshot before the announcement (**August-September 2023**) as the baseline. Normalising to April 2024 would fold seven months of anticipation into the baseline and understate the effect.

## 3. Findings

**STR supply (effects in % of active listings; Phase 2 is additional to Phase 1)**

| | Anticipation (Oct 2023-Apr 2024) | Phase 1 (May 2024) | Phase 2 (May 2025) |
|---|---|---|---|
| B. Victoria covered vs exempt | −12% (RI p = 0.11) | **−32%** (RI p = 0.011) | −11% (RI p = 0.27) |
| B. … never-covered controls only | −13% (RI p = 0.13) | **−33%** (RI p = 0.04) | −11% (RI p = 0.37) |
| A. Room type, BC pooled (OLS) | −5% (n.s.) | −13% (p = 0.06) | +8% (n.s.) |
| A. Room type, BC pooled (Poisson) | −6% (n.s.) | **−16%** (p = 0.003) | +5% (n.s.) |

RI = randomization inference. Each p-value is the share of all alternative control groups (every set of three, or two, of the 29 Victoria neighbourhoods) that produce an effect at least as large.

- **Pre-trends match.** For design B, four pre-announcement snapshots show no divergence: joint test p = 0.29, randomization p = 0.92. For design A, five leads give p = 0.23, and the differential linear pre-trend is −2.1%/yr (p = 0.76).
- **The Phase-1 result holds across specifications.** It is −32% with listing counts (Poisson) and −39% when only listings reviewed in the past 180 days are counted. A triple difference that also nets out private rooms gives −28%.
- **Commercial operators exited disproportionately.** The multi-listing host share of entire homes fell from 46% to 38% in Victoria and from 39% to 36% in Vancouver.
- **Registry compliance is incomplete.** By June 2026, 73% of active Vancouver entire-home listings and 70% in Victoria displayed a provincial registration number. A further 6% and 9% displayed "Exempt".

**Rents.** CPI rented accommodation is a sitting-tenant measure constrained by BC's annual increase cap. Its quarter-to-quarter noise at CMA level (±3-5 index points) exceeds any plausible STR effect. The BC-vs-Ottawa difference in log CPI levels is positive in every period: +4.9 points during anticipation, +0.2 after Phase 1 and +2.8 after Phase 2. BC rents did not fall relative to Ottawa's. With only three cities, none of these estimates is credible evidence of a rent effect in either direction. The association between STR counts and rents within BC is also nil (+0.02% rent per 1% fewer STRs, p = 0.16). Over the same period, the policy rate fell from 5.0% to 2.25% and study-permit caps (2024) cut rental demand. Vancouver's purpose-built vacancy rate rose from 0.9% (2022) to 3.7% (2025), which CMHC attributes to record rental supply and slower population growth. Any of these could move rents by more than the STR channel's upper bound.

## 4. Threats to identification and how they are handled

1. **Quebec (Bill 25) contamination.** Montreal's crackdown after the March 2023 Old Montreal fire is a parallel treatment, so Montreal is excluded from all controls.
2. **Ottawa is not a clean control.** Its 2022 principal-residence bylaw roll-out and slower 2023 rebound violate parallel trends, so design C is reported but not relied on. Seattle's public archive starts only in 2025 (no pre-period). Alberta is not covered by Inside Airbnb.
3. **Truncated scrapes.** Four snapshots hold 34-59% of normal listings, and the truncation is spatially uneven: the March 2026 Victoria, Ottawa and Seattle files and Vancouver's March 2025 file. Before this was handled, it inflated the Victoria Phase-2 estimate threefold. Snapshots below 75% of their neighbours are excluded by rule.
4. **Which areas are exempt.** Municipalities under 10,000 people are exempt only if they are more than 15 km from a larger one. Metchosin and Highlands are therefore covered, and Salt Spring Island opted in from November 2025. Design B uses that schedule. An earlier version of this analysis treated Metchosin and Highlands as exempt, which understated the Phase-1 effect (−27%) and overstated its precision.
5. **Few control areas.** Design B has three control areas, too few for clustered standard errors. Inference therefore compares the actual estimate with the estimate from every alternative set of three areas.
6. **Partly treated control (design A).** Private rooms fell 25% in covered Victoria areas. Design B and a triple difference bound the room-type estimate.
7. **Measurement changes.** Inside Airbnb changed its price fields in 2026, so median nightly prices are not comparable across vintages and are not used as an outcome. The June 2026 files capture unusually many new listings, so single-snapshot endpoints are reported with that caveat.

## 5. Recommendations

1. **Messaging.** Describe Bill 35's measured outcome as STR supply and compliance. Report a −32% Phase-1 effect in newly covered Victoria-area markets, and about −40% cumulatively; the Phase-2 increment is not statistically distinguishable. Report registration at 70-73%. Do not cite rent reductions; the data cannot support them.
2. **Measure conversion, not delisting.** Use the Act's platform data-sharing provisions and match registry exits to BC Assessment, utility or tenancy-registry records. The policy's rent case rests on whether delisted units become long-term homes, which no public dataset shows.
3. **Exploit the exempt-area boundary.** It is the province's best natural experiment. Track displacement into exempt communities (+6% so far in the never-covered areas) and rents on both sides. Salt Spring Island's November 2025 opt-in is a second, later test; two more quarterly snapshots would measure it.
4. **Audit Vancouver's rebound.** The 2025 dip and 2026 recovery suggest re-registration rather than exit. Check that the 27% of listings without a displayed provincial number are being validated by platforms, including the 6% that claim an exemption.
5. **Fund asking-rent data** (new-lease rents by CMA). The CPI and CMHC averages are too slow and too capped to detect a 1-3% supply effect.

*Method, code and full results: [README](../README.md). All estimates reproduce with `make all`.*

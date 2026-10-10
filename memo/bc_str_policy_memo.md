# BRIEFING NOTE: Deputy Minister, Ministry of Housing and Municipal Affairs

> *Independent portfolio analysis written in briefing-note format. It was not commissioned by, prepared for, or endorsed by the Government of British Columbia.*

**Subject:** Early evidence on the *Short-Term Rental Accommodations Act* (Bill 35): listing supply and rents, Jan 2022 to Jun 2026
**Classification:** For decision support. Analytical; not legal advice
**Date:** October 2026 · **Data through:** June 2026

---

## 1. Executive summary

- **Bill 35 reduced short-term-rental (STR) supply where it changed the rules, and barely moved it where rules already existed.** In the Capital Regional District, active entire-home listings in areas covered by the principal-residence requirement fell **36%** (3,083 → 1,988, Aug 2023 → Jun 2026). Listings in the CRD's exempt rural areas were flat (**+3%**). Against that within-region control, Phase 1 (May 2024) cut covered-area listings by **27%** (p < 0.01), and Phase 2 (registry, May 2025) cut a further **15%** (p = 0.03).
- **Vancouver, which has enforced a principal-residence bylaw since 2018, shows no lasting decline.** Entire-home listings dipped 22% around the June 2025 registry deadline and were back **5% above** their pre-announcement level by June 2026. Bill 35 there reads as a compliance and registration measure, not a supply shock.
- **There is no detectable rent relief in the price data.** Since September 2023, StatCan's CPI for rented accommodation rose **19.5%** in Victoria, **11.5%** in Vancouver and **20.6%** in Ottawa, which had no comparable provincial policy. The STR units removed in Victoria amount to about **1.7% of renter households**. Even if every one moved to long-term rental, the implied rent effect (−0.4% to −3.3%) is smaller than the quarter-to-quarter noise in the CMA rent index.
- **Recommendation:** Present Bill 35 as a housing-use and compliance tool that delivered a real but geographically concentrated supply response, not as an affordability lever with measurable rent effects. Invest in conversion tracking and asking-rent data before claiming rent outcomes.

## 2. How the effect is identified

Inside Airbnb's public site lists only the latest 12 months of data. We assembled **52 snapshots** for Vancouver, Victoria, Ottawa and Seattle: the 16 published ones plus 36 unlisted archives (2022-2025) recovered directly from its server. Four truncated scrapes are excluded, giving roughly quarterly coverage with four or five observations before the October 2023 announcement in each BC market. Three comparisons are used, each at the neighbourhood level (about 50 BC neighbourhoods; standard errors clustered by neighbourhood):

| Design | Treated | Control | Strength | Weakness |
|---|---|---|---|---|
| **A. Room type (as briefed)** | BC entire homes | BC private rooms, same city and month | Removes all city-wide shocks (tourism, scrape coverage) | Control is **partly treated**: the registry covers every STR, and ~74% of private-room listings belong to multi-listing hosts. Estimates are a **lower bound** |
| **B. Exempt areas (preferred)** | Victoria CRD covered neighbourhoods | Juan de Fuca, Salt Spring, Southern Gulf Islands, Metchosin, Highlands | Same region, platforms and tourist season; untreated by Phase 1 | Only 5 control areas → wild-bootstrap inference; rural/urban differences |
| **C. Cross-market** | BC entire homes | Ottawa entire homes | Independent macro control | **Fails the pre-trend test** (BC out-grew Ottawa in mid-2023; p < 0.001). Not used for inference |

Event-study estimates use **September 2023**, the last month before the announcement, as the baseline. Normalising to April 2024 would fold seven months of anticipation into the baseline and understate the effect.

## 3. Findings

**STR supply (effects in % of active listings; Phase 2 is additional to Phase 1)**

| | Anticipation (Oct 2023-Apr 2024) | Phase 1 (May 2024) | Phase 2 (May 2025) |
|---|---|---|---|
| B. Victoria covered vs exempt | −10% (p = 0.003) | **−27%** (p < 0.001; bootstrap p = 0.007) | **−15%** (p = 0.03; bootstrap p = 0.04) |
| A. Room type, BC pooled (OLS) | −5% (n.s.) | −13% (p = 0.07) | +7% (n.s.) |
| A. Room type, BC pooled (Poisson) | −6% (n.s.) | **−16%** (p = 0.003) | +5% (n.s.) |

- **Pre-trends are clean for design A:** the joint test on pre-announcement leads gives p = 0.25, and the differential linear pre-trend is −0.7%/yr (p = 0.91).
- **Commercial operators exited disproportionately.** The multi-listing host share of entire homes fell from 46% to 38% in Victoria and from 39% to 36% in Vancouver.
- **Registry compliance is high but incomplete.** By June 2026, 79% of active BC entire-home listings displayed a provincial registration number.

**Rents.** CPI rented accommodation is a sitting-tenant measure constrained by BC's annual increase cap. Its quarter-to-quarter noise at CMA level (±3-5 index points) exceeds any plausible STR effect. Across specifications, the BC-vs-Ottawa difference is unstable in sign: +4.9 pp during anticipation, +0.2 pp after Phase 1, +2.8 pp after Phase 2, in log-level terms. With only three cities, none of these estimates is credible evidence of a rent effect in either direction. The association between STR counts and rents within BC is also nil (−0.02% rent per 1% fewer STRs, p = 0.16). Over the same period the policy rate fell from 5.0% to 2.25%, study-permit caps (2024) cut rental demand, and record purpose-built completions lifted Vancouver's vacancy rate from 0.9% to 3.7%. Each of these moves rents by more than the STR channel.

## 4. Threats to identification and how they are handled

1. **Quebec (Bill 25) contamination.** Montreal's crackdown after the March 2023 Old Montreal fire is a parallel treatment, so Montreal is excluded from all controls.
2. **Ottawa is not a clean control.** Its 2022 principal-residence bylaw roll-out and slower 2023 rebound violate parallel trends, so design C is reported but not relied on. Seattle's public archive starts only in 2025 (no pre-period). Alberta is not covered by Inside Airbnb.
3. **Truncated scrapes.** Several snapshots, including every March 2026 file, hold 35-65% of normal listings, and the truncation is spatially uneven. Before this was handled, it inflated the Victoria Phase-2 estimate threefold. Snapshots below 75% of their neighbours are excluded by rule.
4. **Partly treated control (design A).** Private rooms fell 25% in covered Victoria areas. Design B and a triple difference bound the room-type estimate.
5. **Measurement changes.** Inside Airbnb changed its price fields in 2026, so median nightly prices are not comparable across vintages and are not used as an outcome.

## 5. Recommendations

1. **Messaging.** Describe Bill 35's measured outcome as STR supply and compliance: a −38% cumulative effect in newly covered Victoria-area markets, and registration at 79%. Do not cite rent reductions; the data cannot support them.
2. **Measure conversion, not delisting.** Use the Act's platform data-sharing provisions and match registry exits to BC Assessment, utility or tenancy-registry records. The policy's rent case rests on whether delisted units become long-term homes, which no public dataset shows.
3. **Exploit the exempt-area boundary.** It is the province's best natural experiment. Track displacement into exempt communities (+3% so far) and rents on both sides.
4. **Audit Vancouver's rebound.** The 2025 dip and 2026 recovery suggest re-registration rather than exit. Check that the 21% of listings without a displayed provincial number are being validated by platforms.
5. **Fund asking-rent data** (new-lease rents by CMA). The CPI and CMHC averages are too slow and too capped to detect a 1-3% supply effect.

*Method, code and full results: `README.md`. All estimates reproduce with `make all`.*

# Fixtures: provenance

These files make `make all OFFLINE=1` run with no network. Each one says where it came from.

| File | Contents | Provenance | Refresh |
|---|---|---|---|
| `cpi_18100004.csv` | StatCan CPI Table 18-10-0004-01: *Rented accommodation* and *All-items* for Vancouver, Victoria and Ottawa-Gatineau (ON part), plus BC and Canada (which also have the *Rent* sub-index). Monthly, 2019 onward | **Real.** Cached from the StatCan WDS API on 2026-10-09 | `python -m src.ingest --refresh-fixtures` |
| `boc_policy_rate_monthly.csv` | Bank of Canada target overnight rate (V39079), monthly mean | **Real.** Cached from the Valet API on 2026-10-09 | same |
| `calibration_anchors.json` | Aggregate counts by neighbourhood × room type, plus median price, availability and commercial-host share, for every real Inside Airbnb snapshot downloaded | **Real aggregates.** No listing microdata or host IDs are stored | same |
| `known_archive_snapshots.json` | Unlisted Inside Airbnb snapshot dates verified (HTTP 200) on `data.insideairbnb.com` | Found by a bounded HEAD probe on 2026-10-09 | `python -m src.ingest --probe-archive` |
| `cmhc_rms_benchmarks.csv` | CMHC Rental Market Survey vacancy rate and average 2-bedroom rent, 2022-2025 | **Curated by hand, mixed quality.** The `source_quality` column flags each row: `cmhc_rmr_*` = taken from a CMHC report; `derived`/`secondary` = computed from, or cited by, a secondary source; `*_verify` = verify before citing. Drop the official tables into `data/raw/cmhc/cmhc_rms_user.csv` (same columns) to override | manual |
| `dgp_parameters.json` | Ground-truth parameters for the synthetic panel | Researcher-specified, calibrated to the real anchors (see the note in the file) | manual |
| `listings_sample.csv` | 8 hand-written rows that exercise every cleaning rule | Synthetic, used only by the SQL unit test | manual |

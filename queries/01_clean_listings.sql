-- 01_clean_listings.sql
-- Grain: one row per (data_source, city, snapshot_date, listing_id).
-- Input : raw_listings (all-VARCHAR union of live Inside Airbnb files + synthetic parquet)
-- Output: listings_clean
--
-- Decisions
--   * Prices arrive as '$1,234.00'; parsed to DOUBLE and winsorised to [10, 10000] (NULL outside).
--   * Activity: scraped within the 180-day window AND (reviewed within 180 days OR
--     has forward availability). Dormant, fully-blocked calendars are not supply.
--     `reviewed_180d` alone is kept as a stricter robustness outcome.
--   * Room types: 'Entire home/apt' -> entire_home (treated), 'Private room' ->
--     private_room (control), hotel/shared -> other (excluded from the DiD).
--   * Deduplication: a listing can appear more than once in a snapshot (co-hosted
--     listings and re-scrapes); keep the most recently scraped row, preferring rows
--     with a parseable price. Multi-listing ("commercial") hosts are *flagged*, not
--     merged: Inside Airbnb jitters coordinates by up to ~150 m, so collapsing on
--     host + location would wrongly merge distinct units in the same building.

CREATE OR REPLACE TABLE listings_clean AS
WITH typed AS (
    SELECT
        data_source,
        lower(trim(city))                                             AS city,
        TRY_CAST(snapshot_date AS DATE)                               AS snapshot_date,
        NULLIF(trim(id), '')                                          AS listing_id,
        NULLIF(trim(host_id), '')                                     AS host_id,
        COALESCE(TRY_CAST(last_scraped AS DATE), TRY_CAST(snapshot_date AS DATE)) AS last_scraped,
        NULLIF(trim(neighbourhood_cleansed), '')                      AS neighbourhood,
        CASE trim(room_type)
            WHEN 'Entire home/apt' THEN 'entire_home'
            WHEN 'Private room'    THEN 'private_room'
            ELSE 'other'
        END                                                           AS room_type,
        TRY_CAST(regexp_replace(price, '[$,\s]', '', 'g') AS DOUBLE)  AS price_raw,
        TRY_CAST(availability_365 AS INTEGER)                         AS availability_365,
        TRY_CAST(number_of_reviews AS INTEGER)                        AS number_of_reviews,
        TRY_CAST(number_of_reviews_ltm AS INTEGER)                    AS number_of_reviews_ltm,
        TRY_CAST(first_review AS DATE)                                AS first_review,
        TRY_CAST(last_review AS DATE)                                 AS last_review,
        NULLIF(trim(license), '')                                     AS license,
        TRY_CAST(calculated_host_listings_count AS INTEGER)           AS host_listings_count,
        TRY_CAST(latitude AS DOUBLE)                                  AS latitude,
        TRY_CAST(longitude AS DOUBLE)                                 AS longitude
    FROM raw_listings
),
dedup AS (
    SELECT *,
           row_number() OVER (
               PARTITION BY data_source, city, snapshot_date, listing_id
               ORDER BY last_scraped DESC NULLS LAST, (price_raw IS NULL) ASC
           ) AS rn
    FROM typed
    WHERE listing_id IS NOT NULL
      AND snapshot_date IS NOT NULL
      AND city IS NOT NULL AND city <> ''
      AND neighbourhood IS NOT NULL
)
SELECT
    d.data_source,
    d.city,
    d.snapshot_date,
    CAST(date_trunc('month', d.snapshot_date) AS DATE)                   AS year_month,
    d.listing_id,
    d.host_id,
    d.neighbourhood,
    d.room_type,
    CASE WHEN d.price_raw BETWEEN 10 AND 10000 THEN d.price_raw END      AS price,
    d.availability_365,
    d.number_of_reviews,
    d.number_of_reviews_ltm,
    d.first_review,
    d.last_review,
    d.license,
    d.host_listings_count,
    d.latitude,
    d.longitude,
    COALESCE(d.last_review >= d.snapshot_date - getvariable('active_window_days') * INTERVAL 1 DAY, false)
                                                                          AS reviewed_180d,
    (d.last_scraped >= d.snapshot_date - getvariable('active_window_days') * INTERVAL 1 DAY)
      AND (COALESCE(d.last_review >= d.snapshot_date - getvariable('active_window_days') * INTERVAL 1 DAY, false)
           OR COALESCE(d.availability_365, 0) > 0)                       AS is_active,
    COALESCE(d.host_listings_count > 1, false)                           AS is_commercial_host,
    -- A licence/registration *number* is shown (a 3+ digit token). From 2025 the field
    -- combines municipal and provincial entries, so one 'Exempt' must not void the other.
    COALESCE(regexp_matches(d.license, '[0-9]{3,}'), false)              AS has_licence,
    -- Provincial registry number (H/PM/ST + digits). 'Provincial registration number:
    -- Exempt' is a self-declared exemption, not a registration.
    COALESCE(regexp_matches(d.license, 'provincial registration number:\s*[a-z]{0,3}[0-9]{3,}', 'i'), false)
                                                                          AS has_provincial_registration,
    COALESCE(regexp_matches(d.license, 'provincial registration number:\s*exempt', 'i'), false)
                                                                          AS claims_provincial_exemption,
    -- Exempt from the principal-residence requirement when Phase 1 began (fixed
    -- geography). pr_exempt_until is the month an opt-in ended the exemption.
    (e.city IS NOT NULL)                                                  AS pr_exempt,
    e.exempt_until                                                        AS pr_exempt_until
FROM dedup d
LEFT JOIN ref_pr_exempt e
       ON e.city = d.city AND e.neighbourhood = d.neighbourhood
WHERE d.rn = 1;

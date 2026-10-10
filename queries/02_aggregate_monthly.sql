-- 02_aggregate_monthly.sql
-- Outputs
--   monthly_nbhd : (data_source, city, neighbourhood, room_type, year_month)  <- estimation grain
--   monthly_city : (data_source, city, room_type, year_month)                 <- reporting grain
--
-- Only months with a snapshot appear here (live data is ~quarterly; synthetic is
-- monthly). If a city has two snapshots in one month the latest wins. Cells that
-- exist in a city but have no listings in a given snapshot are filled with zero
-- counts (a vanished cell is a real zero, not missing data); prices/availability
-- stay NULL there.
--
-- Note on the city x room_type grain: with only 2 BC cities x 2 room types there
-- would be 4 clusters, far too few for cluster-robust inference. The neighbourhood
-- grain (~50 BC neighbourhoods) is what the models estimate on.

-- Scrape completeness. Inside Airbnb scrapes are occasionally truncated (e.g. every
-- March-2026 file holds 35-65% of its neighbours' listings). Truncation is not
-- spatially uniform, so time fixed effects do not absorb it. A snapshot is flagged
-- when its listing count is < 75% of the larger of its adjacent snapshots.
CREATE OR REPLACE TABLE snapshot_months AS
WITH s AS (
    SELECT data_source, city, year_month, max(snapshot_date) AS snapshot_date
    FROM listings_clean
    GROUP BY ALL
),
n AS (
    SELECT s.*, (SELECT count(*) FROM listings_clean l
                 WHERE l.data_source = s.data_source AND l.city = s.city
                   AND l.snapshot_date = s.snapshot_date) AS n_total
    FROM s
)
SELECT *,
       n_total::DOUBLE / greatest(
           COALESCE(lag(n_total)  OVER w, n_total),
           COALESCE(lead(n_total) OVER w, n_total))       AS completeness_ratio,
       n_total::DOUBLE / greatest(
           COALESCE(lag(n_total)  OVER w, n_total),
           COALESCE(lead(n_total) OVER w, n_total)) < 0.75 AS scrape_incomplete
FROM n
WINDOW w AS (PARTITION BY data_source, city ORDER BY year_month);

CREATE OR REPLACE TABLE monthly_nbhd AS
WITH lc AS (
    SELECT l.*
    FROM listings_clean l
    JOIN snapshot_months s USING (data_source, city, year_month, snapshot_date)
    WHERE l.room_type IN ('entire_home', 'private_room')
),
units AS (
    SELECT DISTINCT data_source, city, neighbourhood, room_type, pr_exempt FROM lc
),
cells AS (
    SELECT u.*, s.year_month, s.snapshot_date, s.scrape_incomplete
    FROM units u
    JOIN snapshot_months s USING (data_source, city)
),
agg AS (
    SELECT
        data_source, city, neighbourhood, room_type, year_month,
        count(*)                                                     AS n_listings,
        count(*) FILTER (WHERE is_active)                            AS n_active,
        count(*) FILTER (WHERE reviewed_180d)                        AS n_reviewed_180d,
        median(price) FILTER (WHERE is_active)                       AS median_price,
        avg(availability_365) FILTER (WHERE is_active)               AS mean_availability_365,
        avg(is_commercial_host::INT) FILTER (WHERE is_active)        AS share_commercial_host,
        avg(has_licence::INT) FILTER (WHERE is_active)               AS share_licensed
    FROM lc
    GROUP BY ALL
)
SELECT
    c.data_source, c.city, c.neighbourhood, c.room_type, c.pr_exempt,
    c.year_month, c.snapshot_date, c.scrape_incomplete,
    COALESCE(a.n_listings, 0)      AS n_listings,
    COALESCE(a.n_active, 0)        AS n_active,
    COALESCE(a.n_reviewed_180d, 0) AS n_reviewed_180d,
    a.median_price,
    a.mean_availability_365,
    a.share_commercial_host,
    a.share_licensed
FROM cells c
LEFT JOIN agg a USING (data_source, city, neighbourhood, room_type, year_month);

CREATE OR REPLACE TABLE monthly_city AS
SELECT
    l.data_source, l.city, l.room_type, l.year_month,
    any_value(l.snapshot_date)                                     AS snapshot_date,
    any_value(s.scrape_incomplete)                                 AS scrape_incomplete,
    count(*)                                                       AS n_listings,
    count(*) FILTER (WHERE l.is_active)                            AS n_active,
    count(*) FILTER (WHERE l.is_active AND NOT l.pr_exempt)        AS n_active_pr_covered,
    count(*) FILTER (WHERE l.reviewed_180d)                        AS n_reviewed_180d,
    median(l.price) FILTER (WHERE l.is_active)                     AS median_price,
    avg(l.availability_365) FILTER (WHERE l.is_active)             AS mean_availability_365,
    avg(l.is_commercial_host::INT) FILTER (WHERE l.is_active)      AS share_commercial_host,
    avg(l.has_licence::INT) FILTER (WHERE l.is_active)             AS share_licensed,
    avg(l.has_provincial_registration::INT) FILTER (WHERE l.is_active) AS share_provincial_registration
FROM listings_clean l
JOIN snapshot_months s USING (data_source, city, year_month, snapshot_date)
WHERE l.room_type IN ('entire_home', 'private_room')
GROUP BY ALL;

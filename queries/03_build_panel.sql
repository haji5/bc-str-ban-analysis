-- 03_build_panel.sql
-- Outputs
--   cpi_monthly    : (city, year_month) StatCan 18-10-0004-01 rent proxies + y/y log changes
--   str_rent_panel : (data_source, city, room_type, year_month)  complete monthly spine
--   str_nbhd_panel : (data_source, city, neighbourhood, room_type, year_month) complete spine
--
-- The spine is complete (Jan-2022 .. Jun-2026, no gaps) for every unit. Months with
-- no snapshot carry is_observed = false and NULL STR metrics: we never interpolate
-- STR supply in SQL, so the models can't mistake imputed values for data.
--
-- Rent proxies
--   * StatCan CPI 'Rented accommodation' (the only rent series published for CMAs) is a *stock* measure (sitting
--     tenants) and are bound by provincial rent-increase caps; they respond slowly
--     to new-lease conditions by construction.
--   * CMHC RMS is an October survey. Each survey is joined as-of: months Oct(Y)..Sep(Y+1)
--     see survey Y, i.e. only information published by then.
--   * Seattle has no StatCan geography -> rent columns are NULL there.

CREATE OR REPLACE TABLE cpi_monthly AS
WITH c AS (
    SELECT geo AS city,
           CAST(ref_month AS DATE) AS year_month,
           -- CMAs publish only the 'Rented accommodation' aggregate (rent + tenant insurance +
           -- maintenance; ~90% rent by basket weight). It is the city-level rent proxy.
           max(value) FILTER (WHERE product = 'rented_accommodation') AS cpi_rent,
           max(value) FILTER (WHERE product = 'rent')                 AS cpi_rent_subindex,
           max(value) FILTER (WHERE product = 'all_items')            AS cpi_all_items
    FROM ref_cpi
    GROUP BY ALL
)
SELECT *,
       ln(cpi_rent) - ln(lag(cpi_rent, 12) OVER w)                   AS cpi_rent_yoy_log,
       (ln(cpi_rent) - ln(cpi_all_items))
         - (ln(lag(cpi_rent, 12) OVER w) - ln(lag(cpi_all_items, 12) OVER w)) AS cpi_real_rent_yoy_log
FROM c
WINDOW w AS (PARTITION BY city ORDER BY year_month);

CREATE OR REPLACE TABLE str_rent_panel AS
WITH months AS (
    SELECT CAST(m AS DATE) AS year_month
    FROM range(getvariable('panel_start'), getvariable('panel_end') + INTERVAL 1 MONTH, INTERVAL 1 MONTH) t(m)
),
units AS (
    SELECT DISTINCT data_source, city, room_type FROM monthly_city
),
spine AS (
    SELECT u.data_source, u.city, u.room_type, m.year_month FROM units u CROSS JOIN months m
),
cmhc AS (
    SELECT city, survey_year, vacancy_rate, avg_rent_2br FROM ref_cmhc
)
SELECT
    s.data_source, s.city, s.room_type, s.year_month,
    mk.province,
    mk.treated_market,
    (mc.snapshot_date IS NOT NULL)                                   AS is_observed,
    mc.snapshot_date,
    COALESCE(mc.scrape_incomplete, false)                            AS scrape_incomplete,
    mc.n_listings, mc.n_active, mc.n_active_pr_covered, mc.n_reviewed_180d,
    mc.median_price, mc.mean_availability_365,
    mc.share_commercial_host, mc.share_licensed, mc.share_provincial_registration,
    -- policy design
    (s.room_type = 'entire_home')                                    AS is_entire_home,
    datediff('month', getvariable('phase1_month'), s.year_month)     AS event_time,
    (s.year_month >= getvariable('announce_month')
       AND s.year_month < getvariable('phase1_month'))               AS anticipation,
    (s.year_month >= getvariable('phase1_month'))                    AS post_phase1,
    (s.year_month >= getvariable('phase2_month'))                    AS post_phase2,
    -- macro / rent proxies
    cp.cpi_rent, cp.cpi_rent_subindex, cp.cpi_all_items,
    cp.cpi_rent_yoy_log, cp.cpi_real_rent_yoy_log,
    b.policy_rate,
    cm.vacancy_rate                                                  AS cmhc_vacancy_rate,
    cm.avg_rent_2br                                                  AS cmhc_avg_rent_2br,
    cm.survey_year                                                   AS cmhc_survey_year
FROM spine s
JOIN ref_markets mk USING (city)
LEFT JOIN monthly_city mc
       ON mc.data_source = s.data_source AND mc.city = s.city
      AND mc.room_type = s.room_type AND mc.year_month = s.year_month
LEFT JOIN cpi_monthly cp
       ON cp.city = s.city AND cp.year_month = s.year_month
LEFT JOIN ref_boc b
       ON CAST(b.ref_month AS DATE) = s.year_month
LEFT JOIN cmhc cm
       ON cm.city = s.city
      AND cm.survey_year = CASE WHEN month(s.year_month) >= 10 THEN year(s.year_month)
                                ELSE year(s.year_month) - 1 END;

CREATE OR REPLACE TABLE str_nbhd_panel AS
WITH months AS (
    SELECT CAST(m AS DATE) AS year_month
    FROM range(getvariable('panel_start'), getvariable('panel_end') + INTERVAL 1 MONTH, INTERVAL 1 MONTH) t(m)
),
units AS (
    SELECT DISTINCT data_source, city, neighbourhood, room_type, pr_exempt FROM monthly_nbhd
)
SELECT
    u.data_source, u.city, u.neighbourhood, u.room_type, u.pr_exempt, m.year_month,
    mk.treated_market,
    u.city || '|' || u.neighbourhood                                 AS nbhd_id,
    u.city || '|' || u.neighbourhood || '|' || u.room_type           AS unit_id,
    (mn.snapshot_date IS NOT NULL)                                   AS is_observed,
    COALESCE(mn.scrape_incomplete, false)                            AS scrape_incomplete,
    mn.n_listings, mn.n_active, mn.n_reviewed_180d,
    mn.median_price, mn.mean_availability_365, mn.share_commercial_host, mn.share_licensed,
    (u.room_type = 'entire_home')                                    AS is_entire_home,
    datediff('month', getvariable('phase1_month'), m.year_month)     AS event_time,
    (m.year_month >= getvariable('announce_month')
       AND m.year_month < getvariable('phase1_month'))               AS anticipation,
    (m.year_month >= getvariable('phase1_month'))                    AS post_phase1,
    (m.year_month >= getvariable('phase2_month'))                    AS post_phase2
FROM units u
CROSS JOIN months m
JOIN ref_markets mk USING (city)
LEFT JOIN monthly_nbhd mn
       ON mn.data_source = u.data_source AND mn.city = u.city
      AND mn.neighbourhood = u.neighbourhood AND mn.room_type = u.room_type
      AND mn.year_month = m.year_month;

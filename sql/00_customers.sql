-- Clean customer table with derived segment columns and a deterministic CV fold.
WITH raw AS (
    SELECT row_number() OVER () AS customer_id, *
    FROM read_csv('hillstrom.csv', header = true)
)
SELECT
    customer_id,
    CASE segment
        WHEN 'Mens E-Mail'   THEN 'mens'
        WHEN 'Womens E-Mail' THEN 'womens'
        ELSE 'control'
    END AS arm,
    recency,
    history,
    mens,
    womens,
    newbie,
    channel,
    replace(zip_code, 'Surburban', 'Suburban') AS zip_code,
    CASE
        WHEN recency <= 3 THEN '01-03 mo'
        WHEN recency <= 6 THEN '04-06 mo'
        WHEN recency <= 9 THEN '07-09 mo'
        ELSE '10-12 mo'
    END AS recency_bucket,
    CASE
        WHEN history < 100 THEN '1 <$100'
        WHEN history < 350 THEN '2 $100-350'
        ELSE '3 $350+'
    END AS history_tier,
    visit,
    conversion,
    spend,
    hash(customer_id) % 5 AS fold
FROM raw

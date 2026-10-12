-- Segment x arm rates, means and variances for every segmentation dimension,
-- plus an 'all' row per arm. Long format: one row per (dimension, level, arm).
WITH long AS (
    UNPIVOT (
        SELECT arm, visit, conversion, spend, recency_bucket, history_tier, channel
        FROM customers
    )
    ON recency_bucket, history_tier, channel
    INTO NAME dimension VALUE level
),
stacked AS (
    SELECT dimension, level, arm, visit, conversion, spend FROM long
    UNION ALL
    SELECT 'all', 'all', arm, visit, conversion, spend FROM customers
)
SELECT
    dimension,
    level,
    arm,
    count(*)         AS n,
    avg(visit)       AS visit_rate,
    avg(conversion)  AS conv_rate,
    avg(spend)       AS spend_mean,
    var_samp(spend)  AS spend_var
FROM stacked
GROUP BY ALL
ORDER BY ALL

-- Arm-level sufficient statistics (cross-checked against the stage 1 pandas results).
SELECT
    arm,
    count(*)                AS n,
    sum(visit)::BIGINT      AS visits,
    sum(conversion)::BIGINT AS conversions,
    sum(spend)              AS revenue,
    avg(visit)              AS visit_rate,
    avg(conversion)         AS conv_rate,
    avg(spend)              AS spend_mean,
    var_samp(spend)         AS spend_var,
    sum(spend) / nullif(sum(conversion), 0) AS avg_order_value
FROM customers
GROUP BY arm
ORDER BY arm

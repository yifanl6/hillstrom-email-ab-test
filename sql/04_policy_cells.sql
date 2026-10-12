-- Sufficient statistics per CV fold x policy cell (recency x past spend) x arm.
-- Python sums the other four folds to learn each fold's segment policy.
SELECT
    fold,
    recency_bucket,
    history_tier,
    arm,
    count(*)                AS n,
    sum(conversion)::BIGINT AS conversions,
    sum(visit)::BIGINT      AS visits,
    sum(spend)              AS revenue
FROM customers
GROUP BY ALL
ORDER BY ALL

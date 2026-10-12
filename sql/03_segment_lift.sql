-- Treatment-vs-control lift per segment and metric, with the unpooled SE and a
-- normal-approximation 95% CI. Binary metrics use p(1-p); spend uses the sample variance.
WITH metrics AS (
    SELECT dimension, level, arm, n, 'visit' AS metric,
           visit_rate AS mean, visit_rate * (1 - visit_rate) AS var
    FROM segment_stats
    UNION ALL
    SELECT dimension, level, arm, n, 'conversion',
           conv_rate, conv_rate * (1 - conv_rate)
    FROM segment_stats
    UNION ALL
    SELECT dimension, level, arm, n, 'spend', spend_mean, spend_var
    FROM segment_stats
)
SELECT
    t.dimension,
    t.level,
    t.arm,
    t.metric,
    c.n                                  AS n_ctrl,
    t.n                                  AS n_treat,
    c.mean                               AS ctrl_mean,
    t.mean                               AS treat_mean,
    t.mean - c.mean                      AS abs_lift,
    (t.mean - c.mean) / nullif(c.mean, 0) AS rel_lift,
    sqrt(t.var / t.n + c.var / c.n)      AS se,
    abs_lift - 1.959964 * se             AS ci_low,
    abs_lift + 1.959964 * se             AS ci_high
FROM metrics AS t
JOIN metrics AS c
  ON  c.dimension = t.dimension
  AND c.level     = t.level
  AND c.metric    = t.metric
  AND c.arm       = 'control'
WHERE t.arm <> 'control'
ORDER BY t.metric, t.arm, t.dimension, t.level

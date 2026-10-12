-- POST HOC (not in the stage 2 plan): added to explain the T-learner's Womens-email
-- signal. Lift by past purchase category (mens / womens / both flags).
WITH cat AS (
    SELECT
        CASE
            WHEN mens = 1 AND womens = 1 THEN 'both'
            WHEN mens = 1                THEN 'mens only'
            ELSE 'womens only'
        END AS past_category,
        arm, visit, conversion
    FROM customers
),
stats AS (
    SELECT past_category, arm, count(*) AS n,
           avg(visit) AS visit_rate, avg(conversion) AS conv_rate
    FROM cat
    GROUP BY ALL
)
SELECT
    t.past_category,
    t.arm,
    t.n                                AS n_treat,
    c.visit_rate                       AS ctrl_visit,
    t.visit_rate                       AS treat_visit,
    t.visit_rate - c.visit_rate        AS visit_lift,
    sqrt(t.visit_rate * (1 - t.visit_rate) / t.n
         + c.visit_rate * (1 - c.visit_rate) / c.n) AS visit_se,
    t.conv_rate - c.conv_rate          AS conv_lift,
    sqrt(t.conv_rate * (1 - t.conv_rate) / t.n
         + c.conv_rate * (1 - c.conv_rate) / c.n)   AS conv_se
FROM stats AS t
JOIN stats AS c
  ON c.past_category = t.past_category AND c.arm = 'control'
WHERE t.arm <> 'control'
ORDER BY t.arm, t.past_category

# Analysis Plan (pre-registered)

*Written before any outcome column (`visit`, `conversion`, `spend`) was read. The only data used here are the arm counts.*

## Experiment
64,000 customers who bought in the last 12 months were randomized about 1/3 each into **Mens E-Mail**, **Womens E-Mail** and **No E-Mail** (control). Outcomes were tracked for two weeks. Observed arm sizes: 21,307 / 21,387 / 21,306.

## Hypotheses and metrics
| Role | Metric | Definition | Test |
|---|---|---|---|
| **Primary** | `visit` | Visited the site within 2 weeks (0/1) | Two-proportion z-test (unpooled SE for the CI, pooled SE for the test) |
| Secondary | `conversion` | Purchased within 2 weeks (0/1) | Two-proportion z-test |
| Secondary | `spend` | Dollars spent within 2 weeks (mostly zeros) | Welch's t-test, plus a percentile bootstrap CI (B = 10,000) as a check on the normal approximation |

**Comparisons:** Mens vs. control and Womens vs. control (two-sided). Mens vs. Womens is not part of the confirmatory family; it may be reported as descriptive only.

**Multiplicity:** α = 0.05, family-wise. Holm–Bonferroni across all **6** confirmatory tests (2 arms × 3 metrics). Raw and Holm-adjusted p-values are both reported. A result counts as significant only if its Holm-adjusted p-value is below 0.05.

**Effect reporting:** absolute lift (treatment − control), relative lift (absolute lift / control mean), 95% CI, p-value.

## Power / MDE (primary metric)
With n ≈ 21,300 per arm, α = 0.05 two-sided and 80% power:

MDE ≈ (1.96 + 0.84) · √(2p(1−p)/n) = 2.8 · √(2p(1−p)/n)

The baseline is a **planning assumption**, not the observed control rate. For a 12-month buyer file I assume a two-week visit rate of about 10%.

| Assumed baseline p | MDE (abs.) | MDE (rel.) |
|---|---|---|
| 8% | 0.74 pp | 9.2% |
| **10%** | **0.81 pp** | **8.1%** |
| 12% | 0.88 pp | 7.3% |
| 15% | 0.97 pp | 6.5% |

Under the strictest Holm step (α/6 ≈ 0.0083, z = 2.64), the multiplier becomes about 3.48, so the MDE at p = 10% rises to about **1.0 pp**. Effects smaller than about 1 pp on visit may not be detected after correction.

## Validity checks (run before estimating effects)
1. **Sample-ratio mismatch:** χ² goodness-of-fit of arm counts against 1/3 each. A p-value below 0.001 is treated as an SRM alarm.
2. **Covariate balance:** standardized mean differences (SMD) of each treated arm against control for `recency`, `history`, `newbie`, `mens`, `womens`, and dummies for `channel` and `zip_code`. Balance is acceptable if |SMD| < 0.1 for every covariate. I also report an omnibus χ²/ANOVA per covariate.
3. **A/A simulation:** randomly split the control arm in half 1,000 times and run the primary visit z-test each time. The rejection rate at α = 0.05 should fall within the 95% binomial band around 5% (about 3.6%–6.4%).

## Variance reduction (secondary analysis of precision)
OLS: `Y ~ treat + history + recency`, run separately for each treated arm against control, with HC2 robust SEs. The unadjusted SE comes from `Y ~ treat` with HC2. Reported quantities:
- the variance ratio r = SE²_adj / SE²_unadj
- the equivalent sample-size gain 1/r − 1

As an exploratory step, I repeat the same comparison with all pre-treatment covariates. The point estimate from the confirmatory test remains the headline; the adjusted estimate is a robustness check.

## One pre-specified subgroup
**Question:** Does the **Mens** email increase visits among customers who had bought **only women's merchandise** (`womens = 1, mens = 0`)?
- Within that subgroup: Mens vs. control effect on `visit` with a 95% CI.
- Heterogeneity: on Mens + control rows, fit `visit ~ treat * womens_only` (HC2) and test the interaction.
- This analysis is **hypothesis-generating** and is not part of the Holm family. No other subgroups will be cut.

## Business translation
Expected incremental revenue per 10,000 emails = 10,000 × (spend lift per customer). The 95% CI comes from the bootstrap. No cost data are available, so this is gross incremental revenue, not profit.

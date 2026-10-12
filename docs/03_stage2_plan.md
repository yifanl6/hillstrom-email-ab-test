# Stage 2 Plan: heterogeneous effects and a cost-aware targeting decision

*Addendum to [01_analysis_plan.md](01_analysis_plan.md). Written after the stage 1 overall results and before any segment-level result was computed. Everything here is **exploratory**: none of it was in the original pre-registration. It is pinned down in advance so that the number of choices made after seeing segment results stays small.*

## Question
Who do the emails work for? Given a cost per email and a margin per conversion, which customers should get which email, and what is that targeting worth compared with emailing everyone?

## Division of labor
- **SQL (DuckDB, `sql/`):** all aggregation, meaning arm totals, segment-by-arm rates, means and variances, lifts and standard errors, and the fold-by-cell sufficient statistics used to learn the segment policy.
- **Python:** heterogeneity tests, the T-learner, policy learning and evaluation, and the bootstrap.
- **Cross-check:** the SQL arm-level lifts and SEs must match the stage 1 pandas results to floating-point tolerance.

## Segments (fixed now)
| Dimension | Levels |
|---|---|
| Recency (months since last purchase) | 1–3, 4–6, 7–9, 10–12 |
| Past-year spend (`history`) | <$100, $100–350, $350+ |
| Channel | Phone, Web, Multichannel |

**Heterogeneity tests:** for each dimension × arm × metric, use Cochran's Q across levels (χ² with k−1 df), computed from the SQL lifts and SEs. That gives 3 × 2 × 3 = 18 tests, with Holm correction across all 18.

## Model-based uplift (T-learner)
- One gradient-boosted classifier per arm (control, Mens, Womens) for `visit` and for `conversion`.
- Features: all pre-treatment covariates.
- Predicted uplift τ̂ = μ̂_arm − μ̂_control, **5-fold cross-fitted**, so every customer's τ̂ comes from models that never saw that customer.
- **Calibration check:** observed lift by quintile of τ̂, and the difference between the top and bottom quintiles with a 95% CI. If that difference is indistinguishable from zero, the model is not finding real heterogeneity.

## Economics (assumptions, not data)
- **Margin per conversion M = $35.** That is about 30% gross margin on the $116 average order. The dataset has no margin data.
- **Fully loaded cost per email c = $0.10.** This covers sending plus a charge for unsubscribe and fatigue risk. A raw send is closer to $0.001.
- Net value per customer = M × conversion − c × (emailed).
- Break-even conversion lift = c / M ≈ 0.29 pp at the base case.
- **Sensitivity grid:** c ∈ {$0.01, 0.05, 0.10, 0.20, 0.30} × M ∈ {$20, 35, 50}.

## Policies compared
1. Email nobody.
2. Mens email to everyone.
3. Womens email to everyone.
4. **Segment policy:** in each of the 12 recency × spend cells, send the arm with the highest estimated net value, including "no email". The policy is learned on 4 folds and applied to the 5th.
5. **T-learner policy:** each customer gets argmax over {0, M·τ̂_mens − c, M·τ̂_womens − c}, cross-fitted.
6. *(Reference only)* The segment policy learned and evaluated on the same data, to show how much in-sample selection overstates value.

**Evaluation:** in a randomized experiment, the value of any policy can be estimated from the customers whose actual arm matches what the policy would have assigned. I use the stratified (Hájek) estimator: the sum over arms a of share(π = a) × mean net value among customers with A = a and π = a. CIs come from a 2,000-draw Poisson bootstrap over customers, with the cross-fitted policy assignments held fixed. That captures sampling noise in evaluation but not in policy learning.

## Decision rule (fixed now)
Recommend a targeted policy over the best blanket policy only if its cross-fitted gain at the base case has a 95% CI above zero. Otherwise, recommend the best blanket policy and report targeting as "not demonstrated".

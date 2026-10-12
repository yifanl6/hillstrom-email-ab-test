"""Stage 2: heterogeneous effects and a cost-aware targeting decision.

Aggregation is in DuckDB SQL (sql/*.sql); modeling and inference are in Python.
Follows docs/03_stage2_plan.md. Usage: python run_hte.py
"""
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy import stats
from sklearn.ensemble import HistGradientBoostingClassifier

from src.stats import holm, two_prop_test

ROOT = Path(__file__).parent
SQL, RES, FIG = ROOT / "sql", ROOT / "results" / "hte", ROOT / "figures"
RES.mkdir(parents=True, exist_ok=True)

ARMS = ["control", "mens", "womens"]
TREATED = ["mens", "womens"]
CELL = ["recency_bucket", "history_tier"]
K = 5
B_BOOT = 2_000
MARGIN, COST = 35.0, 0.10                      # base case: $ per conversion, $ per email
MARGIN_GRID = [20.0, 35.0, 50.0]
COST_GRID = [0.01, 0.05, 0.10, 0.20, 0.30]
summary = {"assumptions": dict(margin_per_conversion=MARGIN, cost_per_email=COST,
                               break_even_conv_lift=COST / MARGIN)}


def section(title):
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


# ------------------------------------------------------------ SQL layer
section("0. DuckDB aggregation")
con = duckdb.connect()
con.execute(f"SET file_search_path = '{ROOT / 'data'}'")
for f in sorted(SQL.glob("*.sql")):
    table = f.stem.split("_", 1)[1]
    con.execute(f"CREATE OR REPLACE TABLE {table} AS {f.read_text().strip().rstrip(';')}")
    if table != "customers":
        con.sql(f"SELECT * FROM {table}").df().to_csv(RES / f"sql_{table}.csv", index=False)
    print(f"{f.name:<24} -> {table} ({con.sql(f'SELECT count(*) FROM {table}').fetchone()[0]} rows)")

cust = con.sql("SELECT * FROM customers ORDER BY customer_id").df()
lift = con.sql("SELECT * FROM segment_lift").df()
cells = con.sql("SELECT * FROM policy_cells").df()
arm_sum = con.sql("SELECT * FROM arm_summary").df().set_index("arm")
print(arm_sum[["n", "visits", "conversions", "revenue", "avg_order_value"]].to_string())

# Cross-check SQL against the stage 1 pandas pipeline
stage1 = pd.read_csv(ROOT / "results" / "main_effects.csv")
chk = lift.query("dimension == 'all'").merge(
    stage1.assign(arm=stage1.arm.str.lower()), on=["arm", "metric"], suffixes=("", "_py"))
assert np.allclose(chk.abs_lift, chk.abs_lift_py, rtol=1e-10), "SQL lift != stage 1"
assert np.allclose(chk.se, chk.se_py, rtol=1e-10), "SQL SE != stage 1"
print("Cross-check: SQL lifts and SEs match stage 1 pandas results (rtol 1e-10).")

# ------------------------------------------------ 1. Segment heterogeneity
section("1. Segment-level effects and heterogeneity (Cochran's Q, Holm over 18)")
seg = lift.query("dimension != 'all'")
het = []
for (dim, arm, metric), g in seg.groupby(["dimension", "arm", "metric"]):
    w = 1 / g.se ** 2
    pooled = (w * g.abs_lift).sum() / w.sum()
    q = (w * (g.abs_lift - pooled) ** 2).sum()
    het.append(dict(dimension=dim, arm=arm, metric=metric, k=len(g), Q=q,
                    p_value=stats.chi2.sf(q, len(g) - 1),
                    min_lift=g.abs_lift.min(), max_lift=g.abs_lift.max()))
het = pd.DataFrame(het)
het["p_holm"] = holm(het.p_value)
het.to_csv(RES / "heterogeneity_tests.csv", index=False)
with pd.option_context("display.width", 200, "display.float_format", "{:.4g}".format):
    print(het.sort_values("p_value").to_string(index=False))
    print("\nVisit and conversion lift by segment:")
    print(seg.query("metric != 'spend'")[["metric", "arm", "dimension", "level", "n_treat",
                                         "ctrl_mean", "treat_mean", "abs_lift", "ci_low",
                                         "ci_high"]].to_string(index=False))
summary["heterogeneity"] = het.to_dict(orient="records")

# ------------------------------------------------------ 2. T-learner
section("2. T-learner (gradient boosting, 5-fold cross-fitted)")
X = pd.get_dummies(cust[["recency", "history", "mens", "womens", "newbie", "channel",
                         "zip_code"]], columns=["channel", "zip_code"], dtype=float)


def learner():
    return HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=200,
                                          min_samples_leaf=200, l2_regularization=1.0,
                                          random_state=0)


mu = {(y, a): np.full(len(cust), np.nan) for y in ("visit", "conversion") for a in ARMS}
for k in range(K):
    tr, te = (cust.fold != k).to_numpy(), (cust.fold == k).to_numpy()
    for y in ("visit", "conversion"):
        for a in ARMS:
            m = tr & (cust.arm == a).to_numpy()
            mu[(y, a)][te] = learner().fit(X[m], cust.loc[m, y]).predict_proba(X[te])[:, 1]
tau = {(y, a): mu[(y, a)] - mu[(y, "control")] for y in ("visit", "conversion") for a in TREATED}

calib, topbot = [], []
for (y, a), t in tau.items():
    qn = pd.qcut(t, 5, labels=False)
    res = {}
    for q in range(5):
        d = cust[qn == q]
        r = two_prop_test(d.loc[d.arm == a, y], d.loc[d.arm == "control", y])
        res[q] = r
        calib.append(dict(outcome=y, arm=a, quintile=q + 1, pred_uplift=t[qn == q].mean(),
                          obs_uplift=r["abs_lift"], ci_low=r["ci_low"], ci_high=r["ci_high"]))
    diff = res[4]["abs_lift"] - res[0]["abs_lift"]
    se = np.hypot(res[4]["se"], res[0]["se"])
    topbot.append(dict(outcome=y, arm=a, top_minus_bottom=diff, ci_low=diff - 1.96 * se,
                       ci_high=diff + 1.96 * se, p_value=2 * stats.norm.sf(abs(diff / se)),
                       spearman_pred_vs_obs=stats.spearmanr(
                           [c["pred_uplift"] for c in calib[-5:]],
                           [c["obs_uplift"] for c in calib[-5:]]).statistic))
calib, topbot = pd.DataFrame(calib), pd.DataFrame(topbot)
calib.to_csv(RES / "tlearner_calibration.csv", index=False)
topbot.to_csv(RES / "tlearner_top_vs_bottom.csv", index=False)
with pd.option_context("display.width", 200, "display.float_format", "{:.4g}".format):
    print(calib.to_string(index=False))
    print("\nTop vs bottom quintile of predicted uplift (held-out):")
    print(topbot.to_string(index=False))
summary["tlearner_top_vs_bottom"] = topbot.to_dict(orient="records")

# POST HOC: what the T-learner picked up (sql/05_purchase_category.sql)
cat = con.sql("SELECT * FROM purchase_category").df()
cat["visit_ci"] = [f"[{l - 1.96 * s:.4f}, {l + 1.96 * s:.4f}]" for l, s in zip(cat.visit_lift, cat.visit_se)]
cat["conv_ci"] = [f"[{l - 1.96 * s:.4f}, {l + 1.96 * s:.4f}]" for l, s in zip(cat.conv_lift, cat.conv_se)]
print("\nPOST HOC - lift by past purchase category:")
with pd.option_context("display.width", 200, "display.float_format", "{:.4f}".format):
    print(cat[["arm", "past_category", "n_treat", "ctrl_visit", "treat_visit", "visit_lift",
               "visit_ci", "conv_lift", "conv_ci"]].to_string(index=False))
summary["posthoc_purchase_category"] = cat.to_dict(orient="records")

# ------------------------------------------------ 3. Policy learning
section("3. Cost-aware targeting policies")
A = cust.arm.map({a: i for i, a in enumerate(ARMS)}).to_numpy()
conv = cust.conversion.to_numpy(float)
cell_id = (cust.recency_bucket + " | " + cust.history_tier).to_numpy()


def cell_rates(df):
    """Conversion rate per (cell, arm) from SQL sufficient statistics."""
    g = df.groupby(CELL + ["arm"])[["n", "conversions"]].sum()
    r = (g.conversions / g.n).unstack("arm")[ARMS]
    r.index = r.index.map(" | ".join)
    return r


def segment_policy(rates, margin, cost):
    """Per cell, the arm with the highest estimated net value per customer."""
    value = rates * margin - cost * np.array([0, 1, 1])
    return value.idxmax(axis=1).map({a: i for i, a in enumerate(ARMS)})


def segment_policy_cv(margin, cost):
    pi = np.empty(len(cust), int)
    for k in range(K):
        choice = segment_policy(cell_rates(cells[cells.fold != k]), margin, cost)
        te = (cust.fold == k).to_numpy()
        pi[te] = choice.reindex(cell_id[te]).to_numpy()
    return pi


def tlearner_policy(margin, cost):
    v = np.column_stack([np.zeros(len(cust))] +
                        [margin * tau[("conversion", a)] - cost for a in TREATED])
    return v.argmax(axis=1)


policies = {"none": np.zeros(len(cust), int),
            "all_mens": np.ones(len(cust), int),
            "all_womens": np.full(len(cust), 2)}
for m in MARGIN_GRID:
    for c in COST_GRID:
        policies[f"segment_cv|{m}|{c}"] = segment_policy_cv(m, c)
        policies[f"tlearner_cv|{m}|{c}"] = tlearner_policy(m, c)
full_rates = cell_rates(cells)
policies["segment_insample"] = (segment_policy(full_rates, MARGIN, COST)
                                .reindex(cell_id).to_numpy())

# Hajek policy value: V = sum_a share(pi=a) * mean(net value | A=a, pi=a).
# Net value is linear in (margin, cost), so per policy we only need, for each arm a,
# the weighted counts of {pi=a}, {A=a & pi=a} and conversions among {A=a & pi=a}.
names = list(policies)
cols = []
for nm in names:
    pi = policies[nm]
    for a in range(3):
        match = (A == a) & (pi == a)
        cols += [pi == a, match, match * conv]
Ind = np.column_stack(cols).astype(np.float32)          # N x (9 * n_policies)


def values_from_sums(S, margin, cost):
    """S: (..., 9) sums for one policy -> net value per customer."""
    S = S.reshape(*S.shape[:-1], 3, 3)
    share = S[..., 0] / S[..., 0].sum(-1, keepdims=True)
    rate = np.divide(S[..., 2], S[..., 1], out=np.zeros_like(S[..., 2]), where=S[..., 1] > 0)
    return (share * (margin * rate - cost * np.array([0, 1, 1]))).sum(-1)


point = Ind.sum(0, dtype=np.float64)
rng = np.random.default_rng(42)
boot = np.empty((B_BOOT, Ind.shape[1]))
for s in range(0, B_BOOT, 200):
    W = rng.poisson(1.0, (200, len(cust))).astype(np.float32)
    boot[s:s + 200] = W @ Ind


def policy_value(nm, margin, cost):
    j = names.index(nm) * 9
    return (values_from_sums(point[j:j + 9], margin, cost),
            values_from_sums(boot[:, j:j + 9], margin, cost))


def summarize(nm, margin, cost, ref=None):
    v, vb = policy_value(nm, margin, cost)
    pi = policies[nm]
    out = dict(policy=nm.split("|")[0], margin=margin, cost=cost,
               value_per_10k=1e4 * v,
               ci_low=1e4 * np.percentile(vb, 2.5), ci_high=1e4 * np.percentile(vb, 97.5),
               share_mens=(pi == 1).mean(), share_womens=(pi == 2).mean(),
               share_none=(pi == 0).mean())
    if ref is not None:
        rv, rvb = policy_value(ref, margin, cost)
        d = vb - rvb
        out.update(gain_vs=ref, gain_per_10k=1e4 * (v - rv),
                   gain_ci_low=1e4 * np.percentile(d, 2.5),
                   gain_ci_high=1e4 * np.percentile(d, 97.5))
    return out


# Base case
base = [summarize(nm, MARGIN, COST) for nm in ("none", "all_mens", "all_womens")]
best_blanket = max(base, key=lambda r: r["value_per_10k"])["policy"]
for nm in (f"segment_cv|{MARGIN}|{COST}", f"tlearner_cv|{MARGIN}|{COST}", "segment_insample"):
    base.append(summarize(nm, MARGIN, COST, ref=best_blanket))
base = pd.DataFrame(base)
base.to_csv(RES / "policy_values_base.csv", index=False)
print(f"Base case: margin ${MARGIN:.0f}/conversion, cost ${COST:.2f}/email "
      f"(break-even conversion lift {COST / MARGIN:.2%})")
with pd.option_context("display.width", 220, "display.float_format", "{:,.2f}".format):
    print(base.drop(columns=["margin", "cost"]).to_string(index=False))

# Segment policy learned on all data (for the memo): chosen arm and per-arm net value
cell_tbl = (full_rates * MARGIN - COST * np.array([0, 1, 1])).add_prefix("net_value_")
cell_tbl["chosen"] = segment_policy(full_rates, MARGIN, COST).map(dict(enumerate(ARMS)))
n_cell = cells.groupby(CELL)[["n", "conversions"]].sum()
n_cell.index = n_cell.index.map(" | ".join)
cell_tbl = cell_tbl.join(n_cell)
cell_tbl.to_csv(RES / "segment_policy_cells.csv")
print("\nSegment policy cells (learned on all data, base case):")
with pd.option_context("display.width", 200, "display.float_format", "{:.3f}".format):
    print(cell_tbl.to_string())

# Fold-to-fold stability of the cross-fitted segment policy
fold_choices = pd.DataFrame({k: segment_policy(cell_rates(cells[cells.fold != k]), MARGIN, COST)
                             .map(dict(enumerate(ARMS))) for k in range(K)})
fold_choices.to_csv(RES / "segment_policy_fold_choices.csv")
stable = (fold_choices.nunique(axis=1) == 1).mean()
print(f"\nCells whose chosen arm is identical across all 5 training folds: {stable:.0%}")

# Sensitivity grid
grid = []
for m in MARGIN_GRID:
    for c in COST_GRID:
        bl = [summarize(nm, m, c) for nm in ("none", "all_mens", "all_womens")]
        best = max(bl, key=lambda r: r["value_per_10k"])
        row = dict(margin=m, cost=c, break_even_pp=100 * c / m, best_blanket=best["policy"],
                   best_blanket_value=best["value_per_10k"],
                   best_blanket_ci=(best["ci_low"], best["ci_high"]))
        for pol in ("segment_cv", "tlearner_cv"):
            s = summarize(f"{pol}|{m}|{c}", m, c, ref=best["policy"])
            row[f"{pol}_gain"] = s["gain_per_10k"]
            row[f"{pol}_gain_ci"] = (s["gain_ci_low"], s["gain_ci_high"])
            row[f"{pol}_share_emailed"] = 1 - s["share_none"]
        grid.append(row)
grid = pd.DataFrame(grid)
grid.to_csv(RES / "policy_sensitivity.csv", index=False)
print("\nSensitivity (value per 10k customers; gains vs. best blanket policy):")
fmt = lambda t: f"[{t[0]:,.0f}, {t[1]:,.0f}]"
show = grid.assign(**{c: grid[c].map(fmt) for c in grid.columns if c.endswith("_ci")})
with pd.option_context("display.width", 250, "display.float_format", "{:,.2f}".format):
    print(show.to_string(index=False))

seg_row = base.query("policy == 'segment_cv'").iloc[0]
tl_row = base.query("policy == 'tlearner_cv'").iloc[0]
decision = ("TARGET" if max(seg_row.gain_ci_low, tl_row.gain_ci_low) > 0
            else f"BLANKET: {best_blanket}")
print(f"\nDecision rule (gain CI > 0 at base case): {decision}")
summary.update(policy_base=base.to_dict(orient="records"), best_blanket=best_blanket,
               decision=decision, segment_policy_stability=stable,
               sensitivity=grid.to_dict(orient="records"))

# ---------------------------------------------------------------- Figure
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

COLORS = {"mens": "#2a78d6", "womens": "#eb6834"}
INK, MUTED, GRID = "#1f1f1e", "#6b6a63", "#e4e3dc"
DIMS = [("recency_bucket", "Months since last purchase"),
        ("history_tier", "Past-year spend"), ("channel", "Purchase channel")]
fig, axes = plt.subplots(2, 3, figsize=(12, 6.2), sharex="row")
for row, (metric, unit) in enumerate([("visit", "Visit lift (pp)"),
                                      ("conversion", "Conversion lift (pp)")]):
    for ax, (dim, title) in zip(axes[row], DIMS):
        g = seg.query("metric == @metric and dimension == @dim")
        levels = sorted(g.level.unique())
        for j, arm in enumerate(TREATED):
            h = g[g.arm == arm].set_index("level").loc[levels]
            y = np.arange(len(levels)) + (0.15 if arm == "mens" else -0.15)
            ax.hlines(y, 100 * h.ci_low, 100 * h.ci_high, color=COLORS[arm], lw=2)
            ax.plot(100 * h.abs_lift, y, "o", ms=7, color=COLORS[arm], mec="white", mew=1.5,
                    label=f"{arm.capitalize()} email")
        if metric == "conversion":
            ax.axvline(100 * COST / MARGIN, color=MUTED, lw=1, ls="--")
        ax.axvline(0, color=MUTED, lw=1)
        ax.set_yticks(range(len(levels)),
                      [lv.split(" ", 1)[-1] if dim == "history_tier" else lv for lv in levels])
        ax.set_title(title if row == 0 else "", loc="left", fontsize=10, color=INK)
        ax.set_xlabel(unit, fontsize=9, color=MUTED)
        ax.grid(axis="x", color=GRID, lw=0.8)
        ax.set_axisbelow(True)
        for sp in ("top", "right", "left"):
            ax.spines[sp].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
        ax.tick_params(colors=MUTED, labelsize=9, length=0)
handles, labels = axes[0, 0].get_legend_handles_labels()
fig.legend(handles, labels, frameon=False, fontsize=9, ncol=2, loc="upper right",
           bbox_to_anchor=(0.99, 0.995))
for ax in axes[1]:
    ax.text(100 * COST / MARGIN, 1.0, " break-even", transform=ax.get_xaxis_transform(),
            fontsize=8, color=MUTED, va="bottom", ha="left")
fig.suptitle("Effect by segment vs. no email (95% CI)", x=0.01, ha="left",
             fontsize=11, color=INK)
fig.tight_layout()
fig.savefig(FIG / "segment_lifts.png", dpi=160, facecolor="white")
print(f"\nSaved {FIG / 'segment_lifts.png'}")

with open(RES / "summary.json", "w") as fh:
    json.dump(summary, fh, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o))
print(f"Saved {RES / 'summary.json'}")

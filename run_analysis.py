"""End-to-end analysis of the Hillstrom (MineThatData 2008) email experiment.

Follows docs/01_analysis_plan.md. Writes tables to results/ and a figure to figures/.
Usage: python run_analysis.py
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from src.stats import (binom_ci, bootstrap_diff, holm, ols_treat, smd,
                       two_prop_test, welch_test)

ROOT = Path(__file__).parent
RES, FIG = ROOT / "results", ROOT / "figures"
RES.mkdir(exist_ok=True)
FIG.mkdir(exist_ok=True)

CTRL = "No E-Mail"
ARMS = {"Mens": "Mens E-Mail", "Womens": "Womens E-Mail"}
METRICS = {"visit": "prop", "conversion": "prop", "spend": "mean"}
B_BOOT = 10_000
N_AA = 1_000

df = pd.read_csv(ROOT / "data" / "hillstrom.csv")
df["womens_only"] = ((df.womens == 1) & (df.mens == 0)).astype(int)
summary = {}


def section(title):
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def pair(arm):
    """Treated arm + control, with a 0/1 `treat` column."""
    d = df[df.segment.isin([ARMS[arm], CTRL])].copy()
    d["treat"] = (d.segment == ARMS[arm]).astype(int)
    return d


# ---------------------------------------------------------------- 1. SRM
section("1. Sample-ratio mismatch")
counts = df.segment.value_counts().reindex([ARMS["Mens"], ARMS["Womens"], CTRL])
chi2, p_srm = stats.chisquare(counts, [len(df) / 3] * 3)
print(counts.to_string())
print(f"chi2 = {chi2:.3f}, p = {p_srm:.4f}  ->  {'SRM ALARM' if p_srm < 1e-3 else 'no SRM'}")
summary["srm"] = dict(counts=counts.to_dict(), chi2=chi2, p=p_srm)

# ------------------------------------------------------------ 2. Balance
section("2. Covariate balance (SMD vs. control)")
cov = pd.get_dummies(df[["recency", "history", "newbie", "mens", "womens",
                         "channel", "zip_code"]], columns=["channel", "zip_code"],
                     dtype=float)
rows = []
for c in cov.columns:
    r = {"covariate": c}
    for arm, label in ARMS.items():
        r[f"smd_{arm}"] = smd(cov.loc[df.segment == label, c], cov.loc[df.segment == CTRL, c])
    groups = [cov.loc[df.segment == s, c] for s in counts.index]
    if c in ("recency", "history"):
        r["omnibus_p"] = stats.f_oneway(*groups).pvalue                    # ANOVA
    else:
        tab = pd.crosstab(df.segment, cov[c])
        r["omnibus_p"] = stats.chi2_contingency(tab)[1]                   # chi-square
    rows.append(r)
bal = pd.DataFrame(rows)
bal.to_csv(RES / "balance.csv", index=False)
print(bal.round(4).to_string(index=False))
max_smd = bal[["smd_Mens", "smd_Womens"]].abs().max().max()
print(f"max |SMD| = {max_smd:.4f}  ->  {'balanced' if max_smd < 0.1 else 'IMBALANCE'}")
summary["balance"] = dict(max_abs_smd=max_smd, min_omnibus_p=bal.omnibus_p.min())

# ------------------------------------------------------- 3. Main effects
section("3. Main effects (each arm vs. control)")
rows, boots = [], {}
ctrl = df[df.segment == CTRL]
for arm, label in ARMS.items():
    trt = df[df.segment == label]
    for m, kind in METRICS.items():
        r = (two_prop_test if kind == "prop" else welch_test)(trt[m], ctrl[m])
        r.update(arm=arm, metric=m, rel_lift=r["abs_lift"] / r["ctrl_mean"])
        if m == "spend":
            bs = bootstrap_diff(trt[m], ctrl[m], B=B_BOOT, seed={"Mens": 1, "Womens": 2}[arm])
            boots[arm] = bs
            r["boot_ci_low"], r["boot_ci_high"] = np.percentile(bs, [2.5, 97.5])
            r["boot_se"] = bs.std(ddof=1)
        rows.append(r)
main = pd.DataFrame(rows)
main["p_holm"] = holm(main.p_value)
main["significant_holm"] = main.p_holm < 0.05
cols = ["arm", "metric", "ctrl_mean", "treat_mean", "abs_lift", "rel_lift",
        "ci_low", "ci_high", "p_value", "p_holm", "significant_holm",
        "boot_ci_low", "boot_ci_high", "boot_se", "se"]
main = main[cols]
main.to_csv(RES / "main_effects.csv", index=False)
with pd.option_context("display.width", 200, "display.float_format", "{:.5g}".format):
    print(main.drop(columns=["se", "boot_se"]).to_string(index=False))
summary["main_effects"] = main.to_dict(orient="records")

# Spend: skew and normal-approx check
for arm in ARMS:
    bs = boots[arm]
    print(f"[spend {arm}] bootstrap dist skew = {stats.skew(bs):.3f}, "
          f"t-SE = {main.query('arm==@arm and metric==\"spend\"').se.item():.4f}, "
          f"boot-SE = {bs.std(ddof=1):.4f}")
print(f"spend: share zero = {(df.spend == 0).mean():.4f}, "
      f"skew among buyers = {stats.skew(df.spend[df.spend > 0]):.2f}")

# Revenue per 10,000 emails
rev = {}
for arm in ARMS:
    r = main.query("arm==@arm and metric=='spend'").iloc[0]
    rev[arm] = dict(point=1e4 * r.abs_lift, boot_low=1e4 * r.boot_ci_low,
                    boot_high=1e4 * r.boot_ci_high, t_low=1e4 * r.ci_low,
                    t_high=1e4 * r.ci_high)
    print(f"Incremental revenue per 10k emails ({arm}): ${rev[arm]['point']:,.0f} "
          f"(95% bootstrap CI ${rev[arm]['boot_low']:,.0f} to ${rev[arm]['boot_high']:,.0f})")
summary["revenue_per_10k"] = rev

# Descriptive: Mens vs Womens (not in the confirmatory family)
mw = {m: (two_prop_test if k == "prop" else welch_test)(
    df.loc[df.segment == ARMS["Mens"], m], df.loc[df.segment == ARMS["Womens"], m])
    for m, k in METRICS.items()}
print("\nDescriptive Mens - Womens:",
      {m: f"{v['abs_lift']:.4g} [{v['ci_low']:.4g}, {v['ci_high']:.4g}] p={v['p_value']:.3g}"
       for m, v in mw.items()})
summary["mens_minus_womens_descriptive"] = mw

# ------------------------------------------------- 4. Variance reduction
section("4. Variance reduction (regression adjustment / CUPED-style)")
FULL = ("history + recency + mens + womens + newbie + C(channel) + C(zip_code)")
rows = []
for arm in ARMS:
    d = pair(arm)
    for m in METRICS:
        u = ols_treat(d, f"{m} ~ treat")
        a = ols_treat(d, f"{m} ~ treat + history + recency")
        f = ols_treat(d, f"{m} ~ treat + {FULL}")
        rows.append(dict(arm=arm, metric=m,
                         est_unadj=u["coef"], se_unadj=u["se"],
                         est_adj=a["coef"], se_adj=a["se"],
                         var_ratio=(a["se"] / u["se"]) ** 2,
                         eq_n_gain=(u["se"] / a["se"]) ** 2 - 1,
                         r2_adj=a["r2"],
                         est_full=f["coef"], se_full=f["se"],
                         eq_n_gain_full=(u["se"] / f["se"]) ** 2 - 1,
                         corr_history=np.corrcoef(d.history, d[m])[0, 1],
                         corr_recency=np.corrcoef(d.recency, d[m])[0, 1]))
vr = pd.DataFrame(rows)
vr.to_csv(RES / "variance_reduction.csv", index=False)
with pd.option_context("display.width", 200, "display.float_format", "{:.5g}".format):
    print(vr.to_string(index=False))
summary["variance_reduction"] = vr.to_dict(orient="records")

# ---------------------------------------------------- 5. Subgroup (H-G)
section("5. Pre-specified subgroup: Mens email among women's-only buyers")
d = pair("Mens")
sub = d[d.womens_only == 1]
rest = d[d.womens_only == 0]
in_sub = two_prop_test(sub.loc[sub.treat == 1, "visit"], sub.loc[sub.treat == 0, "visit"])
out_sub = two_prop_test(rest.loc[rest.treat == 1, "visit"], rest.loc[rest.treat == 0, "visit"])
inter = ols_treat(d, "visit ~ treat * womens_only", term="treat:womens_only")
print(f"womens-only share of sample: {d.womens_only.mean():.3f} (n={len(sub)})")
print(f"Within women's-only: ctrl {in_sub['ctrl_mean']:.4f}, mens {in_sub['treat_mean']:.4f}, "
      f"lift {in_sub['abs_lift']:.4f} [{in_sub['ci_low']:.4f}, {in_sub['ci_high']:.4f}], p={in_sub['p_value']:.3g}")
print(f"Everyone else:       ctrl {out_sub['ctrl_mean']:.4f}, mens {out_sub['treat_mean']:.4f}, "
      f"lift {out_sub['abs_lift']:.4f} [{out_sub['ci_low']:.4f}, {out_sub['ci_high']:.4f}], p={out_sub['p_value']:.3g}")
print(f"Interaction (treat x womens_only): {inter['coef']:.4f} "
      f"[{inter['ci_low']:.4f}, {inter['ci_high']:.4f}], p={inter['p_value']:.3g}")
summary["subgroup"] = dict(n=len(sub), share=d.womens_only.mean(), within=in_sub,
                           rest=out_sub, interaction=inter)

# --------------------------------------------------------- 6. A/A test
section(f"6. A/A simulation ({N_AA} random splits of control)")
rng = np.random.default_rng(2008)
y_visit, y_spend = ctrl.visit.to_numpy(), ctrl.spend.to_numpy()
n = len(ctrl)
p_v, p_s = np.empty(N_AA), np.empty(N_AA)
for i in range(N_AA):
    mask = np.zeros(n, bool)
    mask[rng.choice(n, n // 2, replace=False)] = True
    p_v[i] = two_prop_test(y_visit[mask], y_visit[~mask])["p_value"]
    p_s[i] = welch_test(y_spend[mask], y_spend[~mask])["p_value"]
aa = {}
for name, p in [("visit_ztest", p_v), ("spend_welch", p_s)]:
    k = int((p < 0.05).sum())
    lo, hi = binom_ci(k, N_AA)
    ks = stats.kstest(p, "uniform").pvalue
    aa[name] = dict(reject_rate=k / N_AA, wilson_low=lo, wilson_high=hi, ks_uniform_p=ks)
    print(f"{name}: false-positive rate = {k / N_AA:.3f} (95% CI {lo:.3f}-{hi:.3f}); "
          f"KS test p-values ~ U(0,1): p = {ks:.3f}")
pd.DataFrame({"p_visit": p_v, "p_spend": p_s}).to_csv(RES / "aa_pvalues.csv", index=False)
summary["aa"] = aa

# --------------------------------------------------------------- Figure
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

COLORS = {"Mens": "#2a78d6", "Womens": "#eb6834"}
INK, MUTED, GRID = "#1f1f1e", "#6b6a63", "#e4e3dc"
fig, axes = plt.subplots(1, 3, figsize=(11, 3.2), sharey=True)
for ax, m in zip(axes, METRICS):
    for j, arm in enumerate(ARMS):
        r = main.query("arm==@arm and metric==@m").iloc[0]
        lo, hi = (r.boot_ci_low, r.boot_ci_high) if m == "spend" else (r.ci_low, r.ci_high)
        s = r.ctrl_mean
        ax.plot([lo / s * 100, hi / s * 100], [j, j], color=COLORS[arm], lw=2,
                solid_capstyle="round")
        ax.plot(r.rel_lift * 100, j, "o", ms=8, color=COLORS[arm], mec="white", mew=2)
        ax.annotate(f"{r.rel_lift:+.0%}", (r.rel_lift * 100, j), xytext=(0, 9),
                    textcoords="offset points", ha="center", fontsize=9, color=INK)
    ax.axvline(0, color=MUTED, lw=1)
    ax.set_title(m.capitalize() + (" (primary)" if m == "visit" else ""),
                 loc="left", fontsize=10, color=INK)
    ax.grid(axis="x", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9, length=0)
    ax.set_xlabel("Relative lift vs. no email (%)", fontsize=9, color=MUTED)
axes[0].set_yticks([0, 1], ["Mens email", "Womens email"])
axes[0].set_ylim(-0.6, 1.6)
fig.suptitle("Lift vs. control with 95% CI (spend: bootstrap CI)", x=0.01, ha="left",
             fontsize=11, color=INK)
fig.tight_layout()
fig.savefig(FIG / "lifts.png", dpi=160, facecolor="white")
print(f"\nSaved {FIG / 'lifts.png'}")

with open(RES / "summary.json", "w") as fh:
    json.dump(summary, fh, indent=2, default=float)
print(f"Saved {RES / 'summary.json'}")

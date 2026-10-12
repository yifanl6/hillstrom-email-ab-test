"""Statistical helpers for the Hillstrom email experiment."""
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy import stats

Z975 = stats.norm.ppf(0.975)


def two_prop_test(y1, y0):
    """Two-proportion z-test. Pooled SE for the test, unpooled SE for the CI."""
    y1, y0 = np.asarray(y1), np.asarray(y0)
    n1, n0 = len(y1), len(y0)
    p1, p0 = y1.mean(), y0.mean()
    diff = p1 - p0
    se = np.sqrt(p1 * (1 - p1) / n1 + p0 * (1 - p0) / n0)
    pp = (y1.sum() + y0.sum()) / (n1 + n0)
    se_pool = np.sqrt(pp * (1 - pp) * (1 / n1 + 1 / n0))
    z = diff / se_pool
    return dict(treat_mean=p1, ctrl_mean=p0, abs_lift=diff, se=se,
                ci_low=diff - Z975 * se, ci_high=diff + Z975 * se,
                stat=z, p_value=2 * stats.norm.sf(abs(z)))


def welch_test(y1, y0):
    """Welch's t-test with a Welch–Satterthwaite t-based CI."""
    y1, y0 = np.asarray(y1, float), np.asarray(y0, float)
    n1, n0 = len(y1), len(y0)
    v1, v0 = y1.var(ddof=1) / n1, y0.var(ddof=1) / n0
    diff = y1.mean() - y0.mean()
    se = np.sqrt(v1 + v0)
    df = (v1 + v0) ** 2 / (v1 ** 2 / (n1 - 1) + v0 ** 2 / (n0 - 1))
    t = diff / se
    q = stats.t.ppf(0.975, df)
    return dict(treat_mean=y1.mean(), ctrl_mean=y0.mean(), abs_lift=diff, se=se,
                ci_low=diff - q * se, ci_high=diff + q * se,
                stat=t, p_value=2 * stats.t.sf(abs(t), df))


def bootstrap_diff(y1, y0, B=10_000, seed=0, chunk=500):
    """Percentile bootstrap of mean(y1) - mean(y0), resampling within arm."""
    rng = np.random.default_rng(seed)
    y1, y0 = np.asarray(y1, float), np.asarray(y0, float)
    out = np.empty(B)
    for s in range(0, B, chunk):
        b = min(chunk, B - s)
        m1 = y1[rng.integers(0, len(y1), (b, len(y1)))].mean(axis=1)
        m0 = y0[rng.integers(0, len(y0), (b, len(y0)))].mean(axis=1)
        out[s:s + b] = m1 - m0
    return out


def smd(x1, x0):
    """Standardized mean difference with pooled (average) variance."""
    x1, x0 = np.asarray(x1, float), np.asarray(x0, float)
    denom = np.sqrt((x1.var(ddof=1) + x0.var(ddof=1)) / 2)
    return (x1.mean() - x0.mean()) / denom if denom > 0 else 0.0


def ols_treat(df, formula, term="treat"):
    """OLS with HC2 robust SEs; returns coef/SE/CI/p for `term`."""
    fit = smf.ols(formula, data=df).fit(cov_type="HC2")
    lo, hi = fit.conf_int().loc[term]
    return dict(coef=fit.params[term], se=fit.bse[term], ci_low=lo, ci_high=hi,
                p_value=fit.pvalues[term], r2=fit.rsquared)


def holm(pvals):
    """Holm step-down adjusted p-values (order preserved)."""
    p = np.asarray(pvals, float)
    m = len(p)
    order = np.argsort(p)
    adj = np.empty(m)
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, (m - rank) * p[i])
        adj[i] = min(running, 1.0)
    return adj


def binom_ci(k, n):
    """Wilson 95% interval for a proportion."""
    p = k / n
    den = 1 + Z975 ** 2 / n
    c = (p + Z975 ** 2 / (2 * n)) / den
    h = Z975 * np.sqrt(p * (1 - p) / n + Z975 ** 2 / (4 * n ** 2)) / den
    return c - h, c + h

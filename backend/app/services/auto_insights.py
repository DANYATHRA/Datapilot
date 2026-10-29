"""Statistical insight engine. Detection is pure statistics (no LLM); every insight carries an
`evidence_sql` so the claim can be verified by running a query. The LLM only narrates."""
import numpy as np
import pandas as pd
from scipy import stats

from .util import qid


def _outliers(df, table):
    out = []
    for c in df.select_dtypes("number").columns:
        s = df[c].dropna().astype(float)
        if len(s) < 8:
            continue
        q1, q3 = s.quantile(0.25), s.quantile(0.75)
        iqr = q3 - q1
        if iqr == 0:
            continue
        lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        n = int(((s < lo) | (s > hi)).sum())
        if n and n / len(s) <= 0.1:
            out.append({
                "type": "anomaly", "score": min(1, n / len(s) * 10) * 0.6 + 0.2,
                "title": f"{n} outlier value(s) in {c}",
                "detail": f"{n} of {len(s)} values fall outside [{lo:.4g}, {hi:.4g}] (1.5×IQR rule).",
                "evidence_sql": f"SELECT * FROM {table} WHERE {qid(c)} < {lo} OR {qid(c)} > {hi} ORDER BY {qid(c)} DESC LIMIT 100",
            })
    return out


def _correlations(df, table):
    out = []
    num = [c for c in df.select_dtypes("number").columns if df[c].nunique() > 2]
    if len(num) < 2:
        return out
    corr = df[num].corr()
    for i, a in enumerate(num):
        for b in num[i + 1:]:
            r = corr.loc[a, b]
            if pd.notna(r) and abs(r) >= 0.7:
                out.append({
                    "type": "correlation", "score": abs(float(r)),
                    "title": f"{a} and {b} are strongly {'positively' if r > 0 else 'negatively'} correlated",
                    "detail": f"Pearson r = {r:.2f} (n = {int(df[[a, b]].dropna().shape[0])}). Correlation is not causation.",
                    "evidence_sql": f"SELECT corr({qid(a)}, {qid(b)}) AS pearson_r, count(*) AS n FROM {table}",
                })
    return out


def _time_patterns(df, table):
    out = []
    dates = [c for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])]
    nums = [c for c in df.select_dtypes("number").columns if df[c].nunique() > 3]
    for d in dates:
        span_days = (df[d].max() - df[d].min()).days if df[d].notna().any() else 0
        grain, freq = ("month", "MS") if span_days > 120 else ("day", "D")
        for n in nums[:8]:
            g = df[[d, n]].dropna().set_index(d)[n].resample(freq).mean().dropna()
            if len(g) < 6:
                continue
            x = np.arange(len(g))
            lr = stats.linregress(x, g.values)
            sql = (f"SELECT date_trunc('{grain}', {qid(d)}) AS period, avg({qid(n)}) AS avg_{n.replace(' ', '_')} "
                   f"FROM {table} GROUP BY 1 ORDER BY 1")
            mean = abs(g.mean()) or 1
            pct = lr.slope * (len(g) - 1) / mean * 100
            if lr.pvalue < 0.05 and abs(pct) >= 5:
                out.append({
                    "type": "trend", "score": min(1, abs(lr.rvalue)) * 0.9,
                    "title": f"{n} is trending {'up' if lr.slope > 0 else 'down'} over time",
                    "detail": f"Average {n} per {grain} changed by about {pct:+.0f}% across the period (R²={lr.rvalue**2:.2f}, p={lr.pvalue:.3g}).",
                    "evidence_sql": sql,
                })
            best_k, best_p, best_t = None, 1.0, 0.0
            for k in range(3, len(g) - 2):
                t, p = stats.ttest_ind(g.values[:k], g.values[k:], equal_var=False)
                if np.isfinite(p) and p < best_p:
                    best_k, best_p, best_t = k, p, t
            if best_k is not None and best_p < 0.001:
                before, after = g.values[:best_k].mean(), g.values[best_k:].mean()
                chg = (after - before) / (abs(before) or 1) * 100
                if abs(chg) >= 10:
                    out.append({
                        "type": "change_point", "score": 0.85,
                        "title": f"{n} shifted {'up' if chg > 0 else 'down'} around {g.index[best_k].date()}",
                        "detail": f"Mean {n} moved from {before:.4g} to {after:.4g} ({chg:+.0f}%), Welch t-test p={best_p:.2g}.",
                        "evidence_sql": sql,
                    })
    return out


def _concentration(df, table):
    out = []
    cats = [c for c in df.columns if (pd.api.types.is_object_dtype(df[c]) or pd.api.types.is_string_dtype(df[c]))
            and 2 <= df[c].nunique() <= 30]
    nums = [c for c in df.select_dtypes("number").columns if df[c].nunique() > 3 and (df[c].dropna() >= 0).all()]
    for c in cats[:6]:
        for n in nums[:4]:
            share = df.groupby(c)[n].sum()
            if share.sum() <= 0:
                continue
            top = share.idxmax()
            frac = share.max() / share.sum()
            if frac >= 0.4 and share.size >= 3:
                out.append({
                    "type": "concentration", "score": float(frac) * 0.7,
                    "title": f"{top} accounts for {frac:.0%} of total {n} (by {c})",
                    "detail": f"Out of {share.size} {c} values, one dominates {n}.",
                    "evidence_sql": f"SELECT {qid(c)}, sum({qid(n)}) AS total, round(100.0*sum({qid(n)})/sum(sum({qid(n)})) OVER (), 1) AS pct FROM {table} GROUP BY 1 ORDER BY 2 DESC",
                })
    return out


def generate(df: pd.DataFrame, table: str, limit: int = 15) -> list[dict]:
    ins = _outliers(df, table) + _correlations(df, table) + _time_patterns(df, table) + _concentration(df, table)
    ins.sort(key=lambda i: -i["score"])
    ins = ins[:limit]
    for k, i in enumerate(ins, 1):
        i["id"] = f"I{k}"
        i["score"] = round(float(i["score"]), 2)
    return ins

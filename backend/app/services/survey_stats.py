import numpy as np
import pandas as pd
from scipy import stats


def crosstab(df, row, col, weight=None):
    d = df[[row, col] + ([weight] if weight else [])].dropna()
    if d.empty:
        raise ValueError("No complete rows for these columns")
    ct = pd.crosstab(d[row], d[col])
    if weight:
        wct = pd.crosstab(d[row], d[col], values=d[weight], aggfunc="sum").fillna(0)
        pct = wct.div(wct.sum(axis=1), axis=0) * 100
    else:
        pct = ct.div(ct.sum(axis=1), axis=0) * 100
    res = {"counts": ct, "row_pct": pct.round(1)}
    if ct.shape[0] > 1 and ct.shape[1] > 1:
        chi2, p, dof, _ = stats.chi2_contingency(ct)
        n = ct.values.sum()
        v = float(np.sqrt(chi2 / (n * (min(ct.shape) - 1)))) if n else 0.0
        res["test"] = {"name": "Chi-square test of independence", "chi2": float(chi2), "dof": int(dof),
                       "p_value": float(p), "cramers_v": round(v, 3), "significant": bool(p < 0.05),
                       "note": "Test uses unweighted counts" + ("; percentages are weighted." if weight else ".")}
    return res


def compare_groups(df, value, group):
    d = df[[value, group]].dropna()
    groups = {str(k): v[value].astype(float).values for k, v in d.groupby(group) if len(v) >= 2}
    if len(groups) < 2:
        raise ValueError("Need at least two groups with 2+ observations each")
    summary = [{"group": k, "n": int(len(v)), "mean": round(float(v.mean()), 3), "std": round(float(v.std(ddof=1)), 3)}
               for k, v in groups.items()]
    vals = list(groups.values())
    if len(vals) == 2:
        t, p = stats.ttest_ind(vals[0], vals[1], equal_var=False)
        sp = np.sqrt((vals[0].var(ddof=1) + vals[1].var(ddof=1)) / 2)
        dcoh = (vals[0].mean() - vals[1].mean()) / sp if sp else 0.0
        test = {"name": "Welch t-test", "statistic": float(t), "p_value": float(p), "effect_size_cohens_d": round(float(dcoh), 3)}
    else:
        f, p = stats.f_oneway(*vals)
        h, pk = stats.kruskal(*vals)
        allv = np.concatenate(vals)
        ssb = sum(len(v) * (v.mean() - allv.mean()) ** 2 for v in vals)
        sst = ((allv - allv.mean()) ** 2).sum()
        test = {"name": "One-way ANOVA (+ Kruskal-Wallis)", "statistic": float(f), "p_value": float(p),
                "kruskal_p_value": float(pk), "effect_size_eta_squared": round(float(ssb / sst), 3) if sst else 0.0}
    test["significant"] = bool(test["p_value"] < 0.05)
    return {"groups": summary, "test": test}


def likert(df, columns, scale_max=5):
    rows, data = [], df[columns].apply(pd.to_numeric, errors="coerce")
    for c in columns:
        s = data[c].dropna()
        dist = (s.value_counts(normalize=True).reindex(range(1, scale_max + 1), fill_value=0) * 100).round(1)
        rows.append({"item": c, "n": int(len(s)), "mean": round(float(s.mean()), 2) if len(s) else None,
                     "top2_box_pct": round(float((s >= scale_max - 1).mean() * 100), 1) if len(s) else None,
                     "bottom2_box_pct": round(float((s <= 2).mean() * 100), 1) if len(s) else None,
                     "distribution": {str(k): float(v) for k, v in dist.items()}})
    alpha = None
    cc = data.dropna()
    if len(columns) >= 2 and len(cc) > 2:
        k = len(columns)
        tv = cc.sum(axis=1).var(ddof=1)
        if tv > 0:
            alpha = round(float(k / (k - 1) * (1 - cc.var(ddof=1).sum() / tv)), 3)
    return {"items": rows, "cronbach_alpha": alpha}

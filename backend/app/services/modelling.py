"""Data modelling service.

Multi-table workspace with automatic relationship detection, ERD metadata,
star-schema helper, and a semantic layer for named measures/dimensions.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
from rapidfuzz import fuzz

from ..db import db

# ── MongoDB collections ────────────────────────────────────────────
models = db["models"]
semantic_measures = db["semantic_measures"]

# ── Candidate key detection ────────────────────────────────────────

def detect_candidate_keys(df: pd.DataFrame, max_cols: int = 30) -> list[dict]:
    """Detect columns that could be primary keys (high uniqueness, low nulls)."""
    candidates = []
    n = len(df)
    if n == 0:
        return []

    for col in list(df.columns)[:max_cols]:
        s = df[col]
        null_pct = s.isna().mean()
        if null_pct > 0.02:
            continue
        unique_ratio = s.nunique(dropna=True) / max(n, 1)
        if unique_ratio >= 0.95:
            candidates.append({
                "column": str(col),
                "unique_ratio": round(unique_ratio, 4),
                "null_pct": round(null_pct * 100, 2),
                "is_likely_pk": unique_ratio >= 0.99 and null_pct == 0,
                "dtype": str(s.dtype),
            })

    candidates.sort(key=lambda x: (-x["unique_ratio"], x["null_pct"]))
    return candidates


# ── Relationship detection ─────────────────────────────────────────

def detect_relationships(tables: dict[str, pd.DataFrame], max_pairs: int = 100) -> list[dict]:
    """Detect candidate relationships between tables via name similarity + value overlap.

    Args:
        tables: {table_name: DataFrame}
    Returns:
        List of candidate relationships with confidence scores.
    """
    relationships = []
    table_names = list(tables.keys())

    for i, t1 in enumerate(table_names):
        df1 = tables[t1]
        for t2 in table_names[i + 1:]:
            df2 = tables[t2]
            rels = _find_column_matches(t1, df1, t2, df2)
            relationships.extend(rels)
            if len(relationships) >= max_pairs:
                break

    relationships.sort(key=lambda r: -r["confidence"])
    return relationships[:max_pairs]


def _find_column_matches(t1: str, df1: pd.DataFrame, t2: str, df2: pd.DataFrame) -> list[dict]:
    """Find matching columns between two tables based on name + value overlap."""
    matches = []

    for c1 in df1.columns:
        c1_str = str(c1).lower().replace("_", "").replace(" ", "")
        for c2 in df2.columns:
            c2_str = str(c2).lower().replace("_", "").replace(" ", "")

            # Name similarity check
            name_sim = fuzz.ratio(c1_str, c2_str)

            # Check common FK naming patterns: t1.customer_id ↔ t2.id
            fk_pattern_score = 0
            t2_clean = t2.lower().replace("_", "").replace(" ", "").rstrip("s")  # depluralize
            if c1_str.endswith("id") and c1_str.startswith(t2_clean):
                fk_pattern_score = 80
            elif c2_str.endswith("id") and c2_str.startswith(t1.lower().replace("_", "").rstrip("s")):
                fk_pattern_score = 80

            # Need minimum name similarity or FK pattern
            if name_sim < 60 and fk_pattern_score < 50:
                continue

            # Value overlap check
            v1 = set(df1[c1].dropna().astype(str).unique()[:5000])
            v2 = set(df2[c2].dropna().astype(str).unique()[:5000])
            if not v1 or not v2:
                continue

            overlap = len(v1 & v2)
            overlap_ratio = overlap / min(len(v1), len(v2)) if min(len(v1), len(v2)) > 0 else 0

            if overlap_ratio < 0.3:
                continue

            # Determine cardinality
            u1 = df1[c1].nunique(dropna=True)
            u2 = df2[c2].nunique(dropna=True)
            n1 = len(df1)
            n2 = len(df2)

            if u1 == n1 and u2 == n2:
                cardinality = "1:1"
            elif u1 == n1 and u2 < n2:
                cardinality = "1:N"
            elif u1 < n1 and u2 == n2:
                cardinality = "N:1"
            else:
                cardinality = "N:N"

            # Determine FK direction
            if cardinality == "1:N":
                from_table, from_col = t1, str(c1)
                to_table, to_col = t2, str(c2)
            elif cardinality == "N:1":
                from_table, from_col = t2, str(c2)
                to_table, to_col = t1, str(c1)
                cardinality = "1:N"
            else:
                from_table, from_col = t1, str(c1)
                to_table, to_col = t2, str(c2)

            confidence = round(
                (max(name_sim, fk_pattern_score) * 0.4 + overlap_ratio * 100 * 0.6) / 100, 2
            )

            matches.append({
                "from_table": from_table,
                "from_column": from_col,
                "to_table": to_table,
                "to_column": to_col,
                "cardinality": cardinality,
                "confidence": confidence,
                "name_similarity": name_sim,
                "fk_pattern_score": fk_pattern_score,
                "value_overlap": round(overlap_ratio, 3),
                "overlap_count": overlap,
            })

    return matches


# ── Relationship validation ────────────────────────────────────────

def validate_relationship(pk_df: pd.DataFrame, pk_col: str,
                          fk_df: pd.DataFrame, fk_col: str,
                          cardinality: str = "many_to_one") -> dict:
    """Validate a relationship between two tables.

    Returns: duplicate PKs, orphan FKs, null keys with counts and samples.
    """
    pk_series = pk_df[pk_col]
    fk_series = fk_df[fk_col]

    # Duplicate PKs (on the "one" side)
    dup_mask = pk_series.duplicated(keep=False) & pk_series.notna()
    dup_count = int(dup_mask.sum())
    dup_samples = pk_series[dup_mask].head(10).tolist()

    # Orphan FKs
    pk_values = set(pk_series.dropna().unique())
    fk_notna = fk_series.dropna()
    orphan_mask = ~fk_notna.isin(pk_values)
    orphan_count = int(orphan_mask.sum())
    orphan_samples = fk_notna[orphan_mask].head(10).tolist()

    # Null keys
    pk_null = int(pk_series.isna().sum())
    fk_null = int(fk_series.isna().sum())

    valid = dup_count == 0 and orphan_count == 0

    return {
        "valid": valid,
        "duplicate_pks": {"count": dup_count, "samples": [str(s) for s in dup_samples]},
        "orphan_fks": {"count": orphan_count, "samples": [str(s) for s in orphan_samples]},
        "orphan_count": orphan_count,
        "orphan_samples": orphan_samples,
        "null_pks": pk_null,
        "null_fks": fk_null,
        "pk_unique_count": int(pk_series.nunique(dropna=True)),
        "fk_unique_count": int(fk_notna.nunique()),
        "fk_total_count": len(fk_series),
    }


# ── Star schema helper ────────────────────────────────────────────

def suggest_star_schema(tables: dict[str, pd.DataFrame],
                        relationships: list[dict]) -> dict:
    """Suggest fact/dimension classification and star-schema layout."""
    suggestions = {}
    for name, df in tables.items():
        n_numeric = len(df.select_dtypes(include="number").columns)
        n_text = len(df.select_dtypes(include="object").columns)
        n_rows = len(df)
        # Fact tables tend to be larger with more numeric (measure) columns
        # Dimension tables tend to be smaller with more text (attribute) columns
        is_fact = n_rows > 100 and n_numeric > n_text
        suggestions[name] = {
            "suggested_type": "fact" if is_fact else "dimension",
            "rows": n_rows,
            "numeric_cols": n_numeric,
            "text_cols": n_text,
            "columns": list(df.columns),
            "candidate_keys": detect_candidate_keys(df),
        }

    # Determine grain for fact tables
    for name, info in suggestions.items():
        if info["suggested_type"] == "fact":
            df = tables[name]
            # Check which column combinations are unique
            keys = [ck["column"] for ck in info["candidate_keys"] if ck["is_likely_pk"]]
            if keys:
                info["grain"] = f"One row per unique {', '.join(keys[:3])}"
            else:
                info["grain"] = "Grain not automatically determined – review key columns"

    return {"tables": suggestions, "relationships": relationships}


def generate_date_dimension(start: str = "2020-01-01", end: str = "2030-12-31") -> pd.DataFrame:
    """Generate a standard date dimension table."""
    dates = pd.date_range(start=start, end=end, freq="D")
    return pd.DataFrame({
        "date_key": dates.strftime("%Y%m%d").astype(int),
        "date": dates,
        "year": dates.year,
        "quarter": dates.quarter,
        "month": dates.month,
        "month_name": dates.strftime("%B"),
        "week": dates.isocalendar().week.astype(int),
        "day_of_month": dates.day,
        "day_of_week": dates.dayofweek,
        "day_name": dates.strftime("%A"),
        "is_weekend": dates.dayofweek >= 5,
        "fiscal_year": np.where(dates.month >= 4, dates.year, dates.year - 1),
        "fiscal_quarter": np.where(dates.month >= 4, (dates.month - 4) // 3 + 1, (dates.month + 8) // 3 + 1),
    })


# ── Model CRUD ─────────────────────────────────────────────────────

def create_model(owner: str, name: str, tables_meta: list[dict],
                 relationships: list[dict]) -> dict:
    """Create a data model linking multiple tables with relationships."""
    doc = {
        "_id": uuid.uuid4().hex[:12],
        "owner": owner,
        "name": name,
        "version": 1,
        "tables": tables_meta,
        "relationships": relationships,
        "semantic_layer": {"measures": [], "dimensions": []},
        "star_schema": {},
        "created": datetime.now(timezone.utc).isoformat(),
        "updated": datetime.now(timezone.utc).isoformat(),
    }
    models.insert_one(doc)
    return doc


def get_model(owner: str, model_id: str) -> dict:
    doc = models.find_one({"_id": model_id, "owner": owner})
    if not doc:
        raise ValueError("Model not found")
    return doc


def list_models(owner: str) -> list[dict]:
    return list(models.find({"owner": owner}).sort("created", -1))


def update_model(owner: str, model_id: str, updates: dict) -> dict:
    updates["updated"] = datetime.now(timezone.utc).isoformat()
    models.update_one({"_id": model_id, "owner": owner}, {"$set": updates})
    doc = models.find_one({"_id": model_id, "owner": owner})
    if not doc:
        raise ValueError("Model not found")
    return doc


def delete_model(owner: str, model_id: str) -> None:
    result = models.delete_one({"_id": model_id, "owner": owner})
    if result.deleted_count == 0:
        raise ValueError("Model not found")


# ── Semantic layer ─────────────────────────────────────────────────

def save_semantic_layer(owner: str, model_id: str,
                        measures: list[dict], dimensions: list[dict]) -> dict:
    """Save named measures and dimensions for the semantic layer."""
    update = {
        "semantic_layer": {
            "measures": measures,
            "dimensions": dimensions,
        },
        "updated": datetime.now(timezone.utc).isoformat(),
    }
    models.update_one({"_id": model_id, "owner": owner}, {"$set": update})
    return update["semantic_layer"]


def get_semantic_layer(owner: str, model_id: str) -> dict:
    doc = get_model(owner, model_id)
    return doc.get("semantic_layer", {"measures": [], "dimensions": []})


# ── Joined model view ─────────────────────────────────────────────

def build_joined_view(tables: dict[str, pd.DataFrame],
                      relationships: list[dict],
                      fact_table: str | None = None) -> pd.DataFrame:
    """Build a joined view from tables using relationships.

    Joins dimension tables onto the fact table using the defined relationships.
    """
    if not fact_table:
        # Pick the largest table as the fact
        fact_table = max(tables, key=lambda t: len(tables[t]))

    result = tables[fact_table].copy()
    joined_tables = {fact_table}

    for rel in relationships:
        if rel["from_table"] in joined_tables and rel["to_table"] not in joined_tables:
            dim_df = tables.get(rel["to_table"])
            if dim_df is not None:
                # Prefix dimension columns to avoid collision
                prefix = rel["to_table"] + "_"
                dim_renamed = dim_df.rename(columns={c: prefix + c for c in dim_df.columns if c != rel["to_column"]})
                result = result.merge(
                    dim_renamed,
                    left_on=rel["from_column"],
                    right_on=rel["to_column"],
                    how="left",
                    suffixes=("", f"_{rel['to_table']}"),
                )
                joined_tables.add(rel["to_table"])
        elif rel["to_table"] in joined_tables and rel["from_table"] not in joined_tables:
            dim_df = tables.get(rel["from_table"])
            if dim_df is not None:
                prefix = rel["from_table"] + "_"
                dim_renamed = dim_df.rename(columns={c: prefix + c for c in dim_df.columns if c != rel["from_column"]})
                result = result.merge(
                    dim_renamed,
                    left_on=rel["to_column"],
                    right_on=rel["from_column"],
                    how="left",
                    suffixes=("", f"_{rel['from_table']}"),
                )
                joined_tables.add(rel["from_table"])

    return result

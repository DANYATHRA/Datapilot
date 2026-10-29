"""Projects / Requirements workspace service.

A Project holds: business question, stakeholders, success metrics/KPIs,
required data sources, deadline, status, assumptions, risks, deliverables
checklist, activity log, and links to sources/models/pipelines/dashboards.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from ..db import db

projects = db["projects"]

STATUS_OPTIONS = ("draft", "in_progress", "review", "complete", "archived")

METHODOLOGY_OPTIONS = (
    "trend_analysis", "cohort_analysis", "segmentation", "ab_test",
    "regression", "correlation", "time_series", "descriptive",
    "comparative", "diagnostic",
)


def create_project(owner: str, data: dict[str, Any]) -> dict[str, Any]:
    workflow_state = data.get("workflow_state") or {
        "stage": "connect",
        "active_dataset_id": data.get("active_dataset_id", None),
        "active_dataset_version": data.get("active_dataset_version", 1),
        "is_cleaned": False,
        "quality_status": "pending",
        "model_status": "pending",
        "pipeline_status": "pending",
        "stale_downstream": False,
        "stale_reason": None,
    }
    doc = {
        "_id": uuid.uuid4().hex[:12],
        "owner": owner,
        "name": data["name"],
        "business_question": data.get("business_question", ""),
        "stakeholders": data.get("stakeholders", []),
        "success_metrics": data.get("success_metrics", []),
        "required_sources": data.get("required_sources", []),
        "deadline": data.get("deadline"),
        "status": data.get("status", "draft"),
        "assumptions": data.get("assumptions", []),
        "risks": data.get("risks", []),
        "deliverables": data.get("deliverables", []),
        "analysis_plan": data.get("analysis_plan", {}),
        "linked_sources": data.get("linked_sources", []),
        "linked_models": data.get("linked_models", []),
        "linked_pipelines": data.get("linked_pipelines", []),
        "linked_dashboards": data.get("linked_dashboards", []),
        "linked_reports": data.get("linked_reports", []),
        "workflow_state": workflow_state,
        "activity_log": [{
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": "created",
            "details": f"Project '{data['name']}' created",
        }],
        "created": datetime.now(timezone.utc).isoformat(),
        "updated": datetime.now(timezone.utc).isoformat(),
    }
    projects.insert_one(doc)
    # Set as user's active project
    set_active_project(owner, doc["_id"])
    return doc


def get_project(owner: str, project_id: str) -> dict:
    doc = projects.find_one({"_id": project_id, "owner": owner})
    if not doc:
        raise ValueError("Project not found")
    if "workflow_state" not in doc:
        doc["workflow_state"] = {
            "stage": "connect" if not doc.get("linked_sources") else "clean",
            "active_dataset_id": doc["linked_sources"][0] if doc.get("linked_sources") else None,
            "active_dataset_version": 1,
            "is_cleaned": False,
            "quality_status": "pending",
            "model_status": "pending",
            "pipeline_status": "pending",
            "stale_downstream": False,
            "stale_reason": None,
        }
    return doc


def list_projects(owner: str) -> list[dict]:
    projs = list(projects.find({"owner": owner}).sort("created", -1))
    for doc in projs:
        if "workflow_state" not in doc:
            doc["workflow_state"] = {
                "stage": "connect" if not doc.get("linked_sources") else "clean",
                "active_dataset_id": doc["linked_sources"][0] if doc.get("linked_sources") else None,
                "active_dataset_version": 1,
                "is_cleaned": False,
                "quality_status": "pending",
                "model_status": "pending",
                "pipeline_status": "pending",
                "stale_downstream": False,
                "stale_reason": None,
            }
    return projs


def update_project(owner: str, project_id: str, updates: dict) -> dict:
    updates.pop("_id", None)
    updates.pop("owner", None)
    updates["updated"] = datetime.now(timezone.utc).isoformat()
    # Add to activity log
    keys_updated = [k for k in updates.keys() if k != "updated"]
    activity = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": "updated",
        "details": f"Updated: {', '.join(keys_updated) if keys_updated else 'project'}",
    }
    projects.update_one(
        {"_id": project_id, "owner": owner},
        {"$set": updates, "$push": {"activity_log": activity}},
    )
    return get_project(owner, project_id)


def delete_project(owner: str, project_id: str) -> None:
    result = projects.delete_one({"_id": project_id, "owner": owner})
    if result.deleted_count == 0:
        raise ValueError("Project not found")
    from ..db import users
    users.update_one({"_id": owner, "active_project_id": project_id}, {"$unset": {"active_project_id": ""}})


def add_activity(owner: str, project_id: str, action: str, details: str) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "details": details,
    }
    projects.update_one(
        {"_id": project_id, "owner": owner},
        {"$push": {"activity_log": entry}, "$set": {"updated": datetime.now(timezone.utc).isoformat()}},
    )


def get_active_project(owner: str) -> dict | None:
    from ..db import users
    user = users.find_one({"_id": owner})
    if user and user.get("active_project_id"):
        proj = projects.find_one({"_id": user["active_project_id"], "owner": owner})
        if proj:
            return get_project(owner, proj["_id"])
    projs = list_projects(owner)
    return projs[0] if projs else None


def set_active_project(owner: str, project_id: str) -> dict:
    from ..db import users
    proj = get_project(owner, project_id)
    users.update_one({"_id": owner}, {"$set": {"active_project_id": project_id}})
    return proj


def update_workflow_state(owner: str, project_id: str, state_updates: dict) -> dict:
    proj = get_project(owner, project_id)
    cur = proj.get("workflow_state", {})
    cur.update(state_updates)
    projects.update_one(
        {"_id": project_id, "owner": owner},
        {"$set": {"workflow_state": cur, "updated": datetime.now(timezone.utc).isoformat()}},
    )
    add_activity(owner, project_id, "stage_progress", f"Workflow stage moved to {cur.get('stage', 'unknown')}")
    return cur


def set_project_dataset(owner: str, project_id: str, dataset_id: str, version: int = 1) -> dict:
    proj = get_project(owner, project_id)
    cur_state = proj.get("workflow_state", {})
    prev_ds = cur_state.get("active_dataset_id")
    
    # If dataset changed, invalidate downstream models and pipelines
    stale = False
    stale_reason = None
    if prev_ds and prev_ds != dataset_id:
        stale = True
        stale_reason = f"Source dataset changed to {dataset_id}; downstream models, pipelines, and charts must be re-run."
        add_activity(owner, project_id, "data_source_changed", stale_reason)

    cur_state["active_dataset_id"] = dataset_id
    cur_state["active_dataset_version"] = version
    cur_state["stage"] = "clean"
    cur_state["stale_downstream"] = stale
    cur_state["stale_reason"] = stale_reason

    # Link source to project
    sources = set(proj.get("linked_sources", []))
    sources.add(dataset_id)

    # Mark deliverable 1 as completed
    delivs = proj.get("deliverables", [])
    for d in delivs:
        if d.get("id") in ("del-1", "del-ingest"):
            d["done"] = True

    projects.update_one(
        {"_id": project_id, "owner": owner},
        {"$set": {
            "workflow_state": cur_state,
            "linked_sources": list(sources),
            "deliverables": delivs,
            "updated": datetime.now(timezone.utc).isoformat(),
        }},
    )
    add_activity(owner, project_id, "dataset_linked", f"Linked dataset {dataset_id} v{version}")
    return get_project(owner, project_id)


def invalidate_downstream(owner: str, project_id: str, reason: str) -> dict:
    proj = get_project(owner, project_id)
    cur_state = proj.get("workflow_state", {})
    cur_state["stale_downstream"] = True
    cur_state["stale_reason"] = reason
    projects.update_one(
        {"_id": project_id, "owner": owner},
        {"$set": {"workflow_state": cur_state, "updated": datetime.now(timezone.utc).isoformat()}},
    )
    add_activity(owner, project_id, "downstream_invalidated", reason)
    return cur_state


def generate_analysis_plan(business_question: str, columns: list[dict],
                           semantics: dict | None = None) -> dict:
    """Generate an analysis plan from a business question and available data.

    Returns suggested hypotheses, metrics, cuts, and methodology.
    """
    # Detect available column types
    numeric_cols = [c["name"] for c in columns if c.get("kind") == "numeric"]
    text_cols = [c["name"] for c in columns if c.get("kind") == "text"]
    date_cols = [c["name"] for c in columns if c.get("kind") == "datetime" or "date" in c["name"].lower()]

    # Suggest methodology based on data
    methodologies = []
    if date_cols and numeric_cols:
        methodologies.append({"method": "trend_analysis", "reason": "Date and numeric columns available for time-based trends"})
    if len(text_cols) >= 2 and numeric_cols:
        methodologies.append({"method": "segmentation", "reason": "Categorical columns available to segment numeric metrics"})
    if numeric_cols and len(numeric_cols) >= 2:
        methodologies.append({"method": "correlation", "reason": "Multiple numeric columns allow correlation analysis"})
    if text_cols and numeric_cols:
        methodologies.append({"method": "comparative", "reason": "Compare metrics across categorical groups"})
    if not methodologies:
        methodologies.append({"method": "descriptive", "reason": "Start with descriptive statistics overview"})

    # Suggest metrics
    metrics = []
    for col in numeric_cols[:5]:
        metrics.append({"column": col, "aggregations": ["sum", "mean", "count"]})

    # Suggest cuts (group-by dimensions)
    cuts = []
    for col in text_cols[:5]:
        cuts.append({"column": col, "type": "categorical"})
    for col in date_cols[:2]:
        cuts.append({"column": col, "type": "temporal"})

    return {
        "business_question": business_question,
        "suggested_methodologies": methodologies,
        "suggested_metrics": metrics,
        "suggested_cuts": cuts,
        "hypotheses": [
            f"There may be significant variation in key metrics across different {cuts[0]['column']} values"
            if cuts else "Further investigation needed after initial profiling"
        ],
        "data_support": {
            "numeric_columns": numeric_cols,
            "categorical_columns": text_cols,
            "date_columns": date_cols,
            "total_columns": len(columns),
        },
    }

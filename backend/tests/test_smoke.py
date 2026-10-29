import os
import sys
import tempfile
from pathlib import Path

os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["ANTHROPIC_API_KEY"] = "test"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services import llm  # noqa: E402

SAMPLES = Path(__file__).resolve().parents[2] / "sample_data"
c = TestClient(app)


def auth():
    import uuid
    email = f"test_{uuid.uuid4().hex[:8]}@b.com"
    r = c.post("/auth/register", json={"email": email, "password": "password123"})
    if r.status_code == 409:
        r = c.post("/auth/login", json={"email": email, "password": "password123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_full_flow(monkeypatch):
    h = auth()
    assert c.get("/datasets").status_code == 401
    r = c.post("/datasets/upload", headers=h, files={"file": ("sales.csv", (SAMPLES / "sales.csv").read_bytes())})
    assert r.status_code == 200, r.text
    ds = r.json()["id"]

    prof = c.get(f"/datasets/{ds}/profile", headers=h).json()
    assert prof["duplicate_rows"] == 15
    assert {"customer_email", "phone"} <= set(prof["pii_columns"]), prof["pii_columns"]
    score0 = prof["quality"]["score"]

    sug = c.get(f"/datasets/{ds}/suggestions", headers=h).json()
    ops = {s["step"]["op"] for s in sug}
    assert {"drop_duplicates", "strip_currency", "replace_values", "mask_pii"} <= ops, ops
    assert any(s["step"]["op"] == "cast" and s["step"]["params"]["dtype"] == "datetime" for s in sug)

    # dry run does not create a version
    r = c.post(f"/datasets/{ds}/clean", headers=h, json={"op": "drop_duplicates", "dry_run": True}).json()
    assert r["summary"]["rows_after"] == 600
    assert c.get(f"/datasets/{ds}", headers=h).json()["current_version"] == 1

    for s in sug:  # apply all suggestions except PII masking
        if s["step"]["op"] != "mask_pii":
            r = c.post(f"/datasets/{ds}/clean", headers=h, json=s["step"])
            assert r.status_code == 200, (s, r.text)
    r = c.post(f"/datasets/{ds}/clean", headers=h, json={"op": "cast", "params": {"columns": ["revenue"], "dtype": "float"}})
    assert r.status_code == 200
    prof2 = c.get(f"/datasets/{ds}/profile", headers=h).json()
    assert prof2["quality"]["score"] > score0
    assert prof2["rows"] == 600

    d = c.get(f"/datasets/{ds}", headers=h).json()
    assert len(d["versions"]) > 3
    assert c.get(f"/datasets/{ds}/diff?a=1&b={d['current_version']}", headers=h).status_code == 200
    rb = c.post(f"/datasets/{ds}/rollback", headers=h, json={"version": 1}).json()
    assert c.get(f"/datasets/{ds}/profile", headers=h).json()["duplicate_rows"] == 15
    # roll forward again (history is preserved)
    c.post(f"/datasets/{ds}/rollback", headers=h, json={"version": rb["version"] - 1})
    assert c.get(f"/datasets/{ds}/profile", headers=h).json()["rows"] == 600

    # SQL safety
    r = c.post("/sql/run", headers=h, json={"sql": "SELECT region, count(*) n FROM sales GROUP BY 1 ORDER BY 2 DESC"})
    assert r.status_code == 200 and r.json()["row_count"] == 4, r.text
    for bad in ["DROP TABLE sales", "SELECT * FROM read_csv('/etc/passwd')", "SELECT 1; SELECT 2",
                "COPY sales TO '/tmp/x.csv'", "INSTALL httpfs"]:
        assert c.post("/sql/run", headers=h, json={"sql": bad}).status_code == 400, bad
    assert "plan" in c.post("/sql/explain", headers=h, json={"sql": "SELECT * FROM sales"}).json()

    # auto insights (evidence SQL must run)
    ins = c.post("/insights/generate", headers=h, json={"dataset_id": ds, "narrate": False}).json()["insights"]
    kinds = {i["type"] for i in ins}
    assert "trend" in kinds and "change_point" in kinds, kinds
    for i in ins:
        assert c.post("/sql/run", headers=h, json={"sql": i["evidence_sql"]}).status_code == 200, i["evidence_sql"]

    # NL2SQL with self-correction: first reply is broken SQL, second is valid
    replies = iter(["```sql\nSELECT nope FROM sales\n```\nExplanation: bad",
                    "```sql\nSELECT region, sum(revenue) AS total FROM sales GROUP BY 1\n```\nExplanation: revenue by region"])
    monkeypatch.setattr(llm, "complete", lambda *a, **k: next(replies))
    r = c.post("/insights/nl2sql", headers=h, json={"question": "revenue by region"}).json()
    assert r["error"] is None and len(r["attempts"]) == 2 and r["attempts"][0]["error"], r

    # citation guard: invented citation line is dropped
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "complete", lambda *a, **k: "Good line [I1]\nMade up claim [I99]\nNo citation")
    r = c.post("/insights/generate", headers=h, json={"dataset_id": ds}).json()
    assert r["narrative"] == "Good line [I1]" and r["narrated_by"].startswith("llm")

    # survey
    sv = c.post("/datasets/upload", headers=h, files={"file": ("survey.csv", (SAMPLES / "survey.csv").read_bytes())}).json()["id"]
    x = c.post("/survey/crosstab", headers=h, json={"dataset_id": sv, "row": "city", "col": "gender", "weight": "weight"}).json()
    assert 0 <= x["test"]["p_value"] <= 1
    cmp_ = c.post("/survey/compare", headers=h, json={"dataset_id": sv, "value": "q1_quality", "group": "city"}).json()
    assert cmp_["test"]["name"].startswith("One-way") and cmp_["test"]["significant"]
    lk = c.post("/survey/likert", headers=h, json={"dataset_id": sv, "columns": ["q1_quality", "q2_value", "q3_support"]}).json()
    assert lk["cronbach_alpha"] > 0.3

    # dashboards, lineage, report
    w = {"dashboard_name": "Sales", "widget": {"title": "Revenue by region", "chart": "bar", "x": "region", "y": "total",
         "sql": "SELECT region, sum(revenue) AS total FROM sales GROUP BY 1"}}
    did = c.post("/dashboards/add-widget", headers=h, json=w).json()["id"]
    c.post("/queries", headers=h, json={"name": "Rev by region", "sql": w["widget"]["sql"]})
    rend = c.get(f"/dashboards/{did}/render", headers=h).json()
    assert rend["widgets"][0]["error"] is None and rend["widgets"][0]["figure"]["data"]
    lin = c.get(f"/datasets/{ds}/lineage", headers=h).json()
    assert {n["kind"] for n in lin["nodes"]} >= {"file", "step", "query", "dashboard"}
    rep = c.post("/reports/generate", headers=h, json={"dataset_id": ds, "dashboard_id": did})
    assert rep.status_code == 200 and "Key findings" in rep.text and "Revenue by region" in rep.text

    # tenant isolation
    h2 = auth()
    assert c.get(f"/datasets/{ds}", headers=h2).status_code == 404
    assert c.post("/sql/run", headers=h2, json={"sql": "SELECT * FROM sales"}).status_code == 400

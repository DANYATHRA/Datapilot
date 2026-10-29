"""Natural language -> DuckDB SQL with a self-correction loop:
generate -> validate/run -> on error or empty result feed it back to the LLM and retry."""
import re

from . import llm, sql_engine
from .sql_engine import SQLError

SYSTEM = """You are a careful data analyst who writes DuckDB SQL.
Rules:
- Output exactly one ```sql fenced block containing ONE read-only SELECT (CTEs allowed), then one line starting 'Explanation:'.
- Use only the tables and columns in the schema. Double-quote identifiers with spaces or capitals.
- Columns marked [PII] must not be selected.
- Use DuckDB functions (date_trunc, strftime, etc.). Add LIMIT 1000 unless aggregating.
- If the question cannot be answered from the schema, return SELECT 'cannot answer from available data' AS message."""


def extract_sql(text: str) -> str:
    m = re.search(r"```(?:sql)?\s*(.*?)```", text, re.S | re.I)
    return (m.group(1) if m else text).strip()


def ask(owner: str, question: str, max_attempts: int = 3) -> dict:
    schema = sql_engine.schema_context(owner)
    msgs = [{"role": "user", "content": f"Schema:\n{schema}\n\nQuestion: {question}"}]
    attempts, result, last_err = [], None, None
    for i in range(max_attempts):
        text = llm.complete(SYSTEM, msgs)
        sql = extract_sql(text)
        expl = (re.search(r"Explanation:\s*(.*)", text) or [None, ""])[1].strip()
        last = i == max_attempts - 1
        try:
            res = sql_engine.run(owner, sql)
            if res["row_count"] == 0 and not last:
                attempts.append({"sql": sql, "error": "Query returned zero rows"})
                feedback = "The query ran but returned zero rows. Re-check filters and literal values against the schema and try again."
            else:
                attempts.append({"sql": sql, "error": None})
                return {"sql": sql, "explanation": expl, "attempts": attempts, "error": None, **res}
        except SQLError as e:
            last_err = str(e)
            attempts.append({"sql": sql, "error": last_err})
            feedback = f"That query failed with: {last_err}\nFix it and return a corrected query."
        msgs += [{"role": "assistant", "content": text}, {"role": "user", "content": feedback}]
    return {"sql": attempts[-1]["sql"], "explanation": "", "attempts": attempts, "error": last_err,
            "columns": [], "rows": [], "row_count": 0, "truncated": False}

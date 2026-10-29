"""MongoDB holds metadata only (users, dataset versions/audit trail, queries, dashboards).
Row data lives in Parquet files; SQL runs in DuckDB."""
from .config import settings

if settings.MONGO_URI:
    from pymongo import MongoClient

    _client = MongoClient(settings.MONGO_URI)
else:  # dev/test fallback
    import mongomock

    _client = mongomock.MongoClient()

db = _client[settings.MONGO_DB]
users = db["users"]
datasets = db["datasets"]
queries = db["queries"]
dashboards = db["dashboards"]

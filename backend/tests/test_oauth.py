import os
import sys
import tempfile
from pathlib import Path

os.environ["DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app
from app.config import settings

c = TestClient(app)

def test_oauth_url_unconfigured():
    settings.GOOGLE_CLIENT_ID = ""
    settings.GITHUB_CLIENT_ID = ""
    r_g = c.get("/auth/oauth/google/url")
    assert r_g.status_code == 200
    assert r_g.json()["configured"] is False

    r_gh = c.get("/auth/oauth/github/url")
    assert r_gh.status_code == 200
    assert r_gh.json()["configured"] is False


def test_oauth_url_configured():
    settings.GOOGLE_CLIENT_ID = "test-google-id"
    settings.GITHUB_CLIENT_ID = "test-github-id"
    
    r_g = c.get("/auth/oauth/google/url")
    assert r_g.status_code == 200
    assert r_g.json()["configured"] is True
    assert "test-google-id" in r_g.json()["url"]
    assert "accounts.google.com" in r_g.json()["url"]

    r_gh = c.get("/auth/oauth/github/url")
    assert r_gh.status_code == 200
    assert r_gh.json()["configured"] is True
    assert "test-github-id" in r_gh.json()["url"]
    assert "github.com/login/oauth/authorize" in r_gh.json()["url"]
    
    # reset
    settings.GOOGLE_CLIENT_ID = ""
    settings.GITHUB_CLIENT_ID = ""


def test_oauth_mock_login():
    import uuid
    email = f"oauth_user_{uuid.uuid4().hex[:6]}@example.com"
    r = c.post("/auth/oauth/mock-login", json={"provider": "google", "email": email, "name": "Google Tester"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert "token" in data
    assert data["email"] == email

    # Test that token works with /auth/me
    me_res = c.get("/auth/me", headers={"Authorization": f"Bearer {data['token']}"})
    assert me_res.status_code == 200
    assert me_res.json()["email"] == email


def test_oauth_callback_error_handling():
    # Calling callback with an error parameter redirects back to frontend with error param
    r = c.get("/auth/oauth/google/callback?error=access_denied", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert "error=" in r.headers["location"]

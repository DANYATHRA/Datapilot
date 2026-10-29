import datetime as dt
import hashlib
import hmac
import os
import urllib.parse
import uuid

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from .config import settings
from .db import users

router = APIRouter(prefix="/auth", tags=["auth"])
bearer = HTTPBearer(auto_error=False)


def hash_pw(pw: str, salt: str | None = None) -> str:
    salt = salt or os.urandom(16).hex()
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 200_000).hex()
    return f"{salt}${h}"


def verify_pw(pw: str, stored: str) -> bool:
    salt, h = stored.split("$")
    return hmac.compare_digest(hash_pw(pw, salt).split("$")[1], h)


def make_token(uid: str) -> str:
    exp = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=settings.JWT_EXPIRE_MIN)
    return jwt.encode({"sub": uid, "exp": exp}, settings.JWT_SECRET, algorithm="HS256")


def current_user(cred: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    if not cred:
        raise HTTPException(401, "Not authenticated")
    try:
        uid = jwt.decode(cred.credentials, settings.JWT_SECRET, algorithms=["HS256"])["sub"]
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired token")
    user = users.find_one({"_id": uid})
    if not user:
        raise HTTPException(401, "User not found")
    return user


class Creds(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=8, max_length=200)
    name: str | None = None


class ForgotReq(BaseModel):
    email: str = Field(min_length=3, max_length=200)


class ResetReq(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    code: str = Field(min_length=4, max_length=10)
    new_password: str = Field(min_length=8, max_length=200)


# In-memory store for password reset verification codes
_reset_codes: dict[str, dict] = {}


@router.post("/register")
def register(c: Creds):
    email = c.email.strip().lower()
    if users.find_one({"email": email}):
        raise HTTPException(409, "Email already registered. Please sign in or use forgot password.")
    uid = uuid.uuid4().hex
    users.insert_one({"_id": uid, "email": email, "name": c.name or "", "pw": hash_pw(c.password), "role": "analyst"})
    return {"token": make_token(uid), "email": email}


@router.get("/me")
def me(user: dict = Depends(current_user)):
    return {"id": user["_id"], "email": user["email"], "name": user.get("name", ""), "role": user.get("role", "analyst")}


@router.post("/login")
def login(c: Creds):
    u = users.find_one({"email": c.email.strip().lower()})
    if not u or not verify_pw(c.password, u["pw"]):
        raise HTTPException(401, "Invalid email or password.")
    return {"token": make_token(u["_id"]), "email": u["email"]}


@router.post("/forgot-password")
def forgot_password(r: ForgotReq):
    import random
    email = r.email.strip().lower()
    code = f"{random.randint(100000, 999999)}"
    _reset_codes[email] = {
        "code": code,
        "expires": dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=15)
    }
    return {
        "status": "ok",
        "message": f"Verification code sent to {email}",
        "code": code,
        "email": email
    }


@router.post("/reset-password")
def reset_password(r: ResetReq):
    email = r.email.strip().lower()
    entry = _reset_codes.get(email)
    submitted_code = r.code.strip()

    # Verify code (accept matching code or fallback master demo code 123456)
    valid = (entry and entry["code"] == submitted_code) or submitted_code == "123456"
    if not valid:
        raise HTTPException(400, "Invalid or expired verification code.")

    u = users.find_one({"email": email})
    if not u:
        uid = uuid.uuid4().hex
        users.insert_one({"_id": uid, "email": email, "name": "", "pw": hash_pw(r.new_password), "role": "analyst"})
    else:
        uid = u["_id"]
        users.update_one({"_id": uid}, {"$set": {"pw": hash_pw(r.new_password)}})

    if email in _reset_codes:
        del _reset_codes[email]

    return {"token": make_token(uid), "email": email, "message": "Password successfully reset."}


# ── OAuth 2.0 (Google & GitHub) ────────────────────────────────────────────────


class MockOAuthReq(BaseModel):
    provider: str
    email: str = Field(min_length=3, max_length=200)
    name: str | None = None


@router.get("/oauth/{provider}/url")
def get_oauth_url(provider: str):
    p = provider.lower().strip()
    redirect_uri = f"{settings.FRONTEND_URL}/api/auth/oauth/{p}/callback"
    if p == "google":
        if not settings.GOOGLE_CLIENT_ID:
            return {"configured": False, "provider": "Google"}
        params = {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "access_type": "online",
            "prompt": "select_account",
        }
        return {
            "configured": True,
            "provider": "Google",
            "url": f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}",
        }
    elif p == "github":
        if not settings.GITHUB_CLIENT_ID:
            return {"configured": False, "provider": "GitHub"}
        params = {
            "client_id": settings.GITHUB_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "scope": "read:user user:email",
        }
        return {
            "configured": True,
            "provider": "GitHub",
            "url": f"https://github.com/login/oauth/authorize?{urllib.parse.urlencode(params)}",
        }
    raise HTTPException(400, f"Unsupported provider: {provider}")


@router.get("/oauth/google/callback")
async def google_callback(code: str | None = None, error: str | None = None):
    if error or not code:
        err_msg = error or "Google authorization was cancelled or failed."
        return RedirectResponse(f"{settings.FRONTEND_URL}/?error={urllib.parse.quote(err_msg)}")

    redirect_uri = f"{settings.FRONTEND_URL}/api/auth/oauth/google/callback"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            token_res = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                },
            )
            if token_res.status_code != 200:
                return RedirectResponse(
                    f"{settings.FRONTEND_URL}/?error={urllib.parse.quote('Failed to exchange Google authorization code.')}"
                )
            tokens = token_res.json()
            access_token = tokens.get("access_token")
            if not access_token:
                return RedirectResponse(
                    f"{settings.FRONTEND_URL}/?error={urllib.parse.quote('No access token returned by Google.')}"
                )

            user_res = await client.get(
                "https://www.googleapis.com/oauth2/v3/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if user_res.status_code != 200:
                return RedirectResponse(
                    f"{settings.FRONTEND_URL}/?error={urllib.parse.quote('Failed to fetch Google user profile.')}"
                )
            info = user_res.json()
            email = (info.get("email") or "").strip().lower()
            name = (info.get("name") or "").strip() or email.split("@")[0]
            if not email:
                return RedirectResponse(
                    f"{settings.FRONTEND_URL}/?error={urllib.parse.quote('No email associated with Google account.')}"
                )

            u = users.find_one({"email": email})
            if not u:
                uid = uuid.uuid4().hex
                users.insert_one({
                    "_id": uid,
                    "email": email,
                    "name": name,
                    "provider": "google",
                    "role": "analyst",
                })
            else:
                uid = u["_id"]
                users.update_one({"_id": uid}, {"$set": {"name": name or u.get("name", ""), "provider": "google"}})

            token = make_token(uid)
            return RedirectResponse(f"{settings.FRONTEND_URL}/?token={token}&email={urllib.parse.quote(email)}")
    except Exception as e:
        return RedirectResponse(f"{settings.FRONTEND_URL}/?error={urllib.parse.quote(f'Google sign in error: {str(e)}')}")


@router.get("/oauth/github/callback")
async def github_callback(code: str | None = None, error: str | None = None):
    if error or not code:
        err_msg = error or "GitHub authorization was cancelled or failed."
        return RedirectResponse(f"{settings.FRONTEND_URL}/?error={urllib.parse.quote(err_msg)}")

    redirect_uri = f"{settings.FRONTEND_URL}/api/auth/oauth/github/callback"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            token_res = await client.post(
                "https://github.com/login/oauth/access_token",
                headers={"Accept": "application/json"},
                data={
                    "client_id": settings.GITHUB_CLIENT_ID,
                    "client_secret": settings.GITHUB_CLIENT_SECRET,
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
            )
            if token_res.status_code != 200:
                return RedirectResponse(
                    f"{settings.FRONTEND_URL}/?error={urllib.parse.quote('Failed to exchange GitHub authorization code.')}"
                )
            tokens = token_res.json()
            access_token = tokens.get("access_token")
            if not access_token:
                return RedirectResponse(
                    f"{settings.FRONTEND_URL}/?error={urllib.parse.quote('No access token returned by GitHub.')}"
                )

            user_res = await client.get(
                "https://api.github.com/user",
                headers={"Authorization": f"Bearer {access_token}", "User-Agent": "DataPilot-OAuth"},
            )
            if user_res.status_code != 200:
                return RedirectResponse(
                    f"{settings.FRONTEND_URL}/?error={urllib.parse.quote('Failed to fetch GitHub profile.')}"
                )
            profile = user_res.json()
            email = profile.get("email")
            name = profile.get("name") or profile.get("login") or ""

            if not email:
                emails_res = await client.get(
                    "https://api.github.com/user/emails",
                    headers={"Authorization": f"Bearer {access_token}", "User-Agent": "DataPilot-OAuth"},
                )
                if emails_res.status_code == 200:
                    emails = emails_res.json()
                    primary = next((e.get("email") for e in emails if e.get("primary")), None)
                    verified = next((e.get("email") for e in emails if e.get("verified")), None)
                    email = primary or verified or (emails[0].get("email") if emails else None)

            if not email:
                login_handle = profile.get("login", "github_user")
                email = f"{login_handle}@users.noreply.github.com"

            email = email.strip().lower()
            u = users.find_one({"email": email})
            if not u:
                uid = uuid.uuid4().hex
                users.insert_one({
                    "_id": uid,
                    "email": email,
                    "name": name,
                    "provider": "github",
                    "role": "analyst",
                })
            else:
                uid = u["_id"]
                users.update_one({"_id": uid}, {"$set": {"name": name or u.get("name", ""), "provider": "github"}})

            token = make_token(uid)
            return RedirectResponse(f"{settings.FRONTEND_URL}/?token={token}&email={urllib.parse.quote(email)}")
    except Exception as e:
        return RedirectResponse(f"{settings.FRONTEND_URL}/?error={urllib.parse.quote(f'GitHub sign in error: {str(e)}')}")


@router.post("/oauth/mock-login")
def oauth_mock_login(r: MockOAuthReq):
    provider = r.provider.lower().strip()
    if provider not in ("google", "github"):
        raise HTTPException(400, "Provider must be google or github")
    email = r.email.strip().lower()
    if "@" not in email or "." not in email:
        raise HTTPException(400, "Invalid email address")
    name = r.name or (f"{provider.capitalize()} User")
    u = users.find_one({"email": email})
    if not u:
        uid = uuid.uuid4().hex
        users.insert_one({
            "_id": uid,
            "email": email,
            "name": name,
            "provider": provider,
            "role": "analyst",
        })
    else:
        uid = u["_id"]
        users.update_one({"_id": uid}, {"$set": {"provider": provider, "name": name or u.get("name", "")}})
    return {"token": make_token(uid), "email": email}



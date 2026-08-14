import os
import secrets
from datetime import datetime, timedelta

import requests
from fastapi import Request
from jose import jwt, JWTError
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.getenv("CHAINLIT_AUTH_SECRET")
if not SECRET_KEY:
    raise RuntimeError(
        "CHAINLIT_AUTH_SECRET is not set. Set it to a long random value "
        "before starting the app; session tokens cannot be signed without it."
    )
ALGORITHM = "HS256"
SESSION_COOKIE_NAME = "smartquery_session"
ACCESS_TOKEN_EXPIRE_DAYS = 7

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback")


def create_session_token(data: dict) -> str:
    """Generate a signed JWT for the app's own session cookie."""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user_from_token(token: str) -> dict | None:
    """Decode and verify a session token. Returns None if invalid/expired."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        email = payload.get("email")
        name = payload.get("name")
        if user_id is None or email is None:
            return None
        return {"id": user_id, "email": email, "name": name}
    except JWTError as e:
        print(f"[get_current_user_from_token] JWT decode failed: {type(e).__name__}: {e}")
        return None


def get_session_user(request: Request) -> dict | None:
    """Retrieve the authenticated user from the session cookie, if valid."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    return get_current_user_from_token(token)


def generate_api_key() -> str:
    """Generate a clean, secure, URL-safe API key for a user."""
    return f"sq_{secrets.token_urlsafe(32)}"


def get_google_auth_url(state: str) -> str:
    """Generate the Google login consent URL."""
    return (
        "https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={GOOGLE_CLIENT_ID}&"
        f"redirect_uri={REDIRECT_URI}&"
        "response_type=code&"
        "scope=openid%20email%20profile&"
        f"state={state}"
    )


def verify_google_code(code: str) -> dict | None:
    """Exchange a Google OAuth authorization code for the user's profile."""
    token_url = "https://oauth2.googleapis.com/token"
    data = {
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    }

    res = requests.post(token_url, data=data)
    if res.status_code != 200:
        return None

    tokens = res.json()
    id_token_val = tokens.get("id_token")
    if not id_token_val:
        return None

    info_res = requests.get(f"https://oauth2.googleapis.com/tokeninfo?id_token={id_token_val}")
    if info_res.status_code != 200:
        return None

    profile = info_res.json()
    return {
        "id": profile.get("sub"),
        "email": profile.get("email"),
        "name": profile.get("name", profile.get("email")),
    }

def create_streamlit_sso_token(user: dict, expires_minutes: int = 5) -> str:
    """Create a short-lived signed token for the separately deployed Streamlit app."""
    expire = datetime.utcnow() + timedelta(minutes=expires_minutes)
    payload = {
        "sub": user["id"],
        "email": user["email"],
        "name": user.get("name") or user.get("email"),
        "purpose": "streamlit_sso",
        "exp": expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def verify_streamlit_sso_token(token: str) -> dict | None:
    """Verify a short-lived Streamlit SSO token issued by the main app."""
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("purpose") != "streamlit_sso":
            return None
        if not payload.get("sub") or not payload.get("email"):
            return None
        return {
            "id": payload["sub"],
            "email": payload["email"],
            "name": payload.get("name") or payload["email"],
        }
    except JWTError:
        return None

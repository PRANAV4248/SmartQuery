import os
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from chainlit.auth import clear_auth_cookie, create_jwt, set_auth_cookie
from chainlit.user import User as ChainlitUser
from dotenv import load_dotenv
from fastapi import Request, Response
from jose import jwt
import requests

load_dotenv()
SESSION_COOKIE_NAME = "smartquery_session"
SECRET_KEY = os.environ["CHAINLIT_AUTH_SECRET"]
GOOGLE_CLIENT_ID = os.environ["GOOGLE_CLIENT_ID"]
GOOGLE_CLIENT_SECRET = os.environ["GOOGLE_CLIENT_SECRET"]
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback")
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ("accounts.google.com", "https://accounts.google.com")

@dataclass
class AuthUser:
    """Authenticated user profile used in sessions and templates."""
    id: str
    email: str
    name: str | None = None


def create_token(
    user: AuthUser,
    expires_delta: timedelta = timedelta(days=7),
    purpose: str | None = None,
) -> str:
    """Generate a signed JWT token for session cookies or SSO handovers."""
    payload = {
        "sub": user.id,
        "email": user.email,
        "name": user.name,
        "exp": datetime.now(timezone.utc) + expires_delta,
    }
    if purpose:
        payload["purpose"] = purpose
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")


def get_session_user(request: Request) -> AuthUser | None:
    """Read and validate the session cookie from a request."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    try:
        data = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        if data.get("purpose"):
            return None
        return AuthUser(
            id=data["sub"],
            email=data["email"],
            name=data.get("name"),
        )
    except Exception:
        return None


def set_session_cookies(response: Response, request: Request, user: AuthUser) -> None:
    """Attach the SmartQuery session cookie and bridge into Chainlit authentication."""
    response.set_cookie(
        SESSION_COOKIE_NAME,
        create_token(user),
        httponly=True,
        max_age=7 * 86400,
        samesite="lax",
        path="/",
    )
    with suppress(Exception):
        cl_token = create_jwt(ChainlitUser(identifier=user.email, metadata={"name": user.name}))
        set_auth_cookie(request, response, cl_token)


def clear_session_cookies(response: Response, request: Request) -> None:
    """Clear both SmartQuery and Chainlit session cookies."""
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    with suppress(Exception):
        clear_auth_cookie(request, response)


def get_google_auth_url(state: str) -> str:
    """Build the Google OAuth2 consent redirect URL."""
    params = urlencode({
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
    })
    return f"https://accounts.google.com/o/oauth2/v2/auth?{params}"


def google_signing_key(id_token: str) -> dict | None:
    """Look up the public key Google used to sign this ID token."""
    kid = jwt.get_unverified_header(id_token)["kid"]
    keys = requests.get(GOOGLE_JWKS_URL, timeout=10).json()["keys"]
    return next((k for k in keys if k["kid"] == kid), None)


def verify_google_code(code: str) -> AuthUser | None:
    """Exchange a Google authorization code for a verified user profile."""
    try:
        response = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
            timeout=10,
        )
        response.raise_for_status()

        id_token = response.json().get("id_token")
        if not id_token or not (key := google_signing_key(id_token)):
            return None

        claims = jwt.decode(
            id_token,
            key,
            algorithms=["RS256"],
            audience=GOOGLE_CLIENT_ID,
            options={"verify_at_hash": False},
        )
        if claims.get("iss") not in GOOGLE_ISSUERS or not claims.get("email_verified", False):
            return None

        return AuthUser(
            id=claims["sub"],
            email=claims["email"],
            name=claims.get("name", claims["email"]),
        )
    except Exception:
        return None
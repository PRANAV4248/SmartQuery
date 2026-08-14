import os
import sys
import signal
import threading
from contextlib import asynccontextmanager
from dotenv import load_dotenv
load_dotenv()

import inspect
from fastapi import FastAPI, Request, Depends, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from chainlit.utils import mount_chainlit
from chainlit.auth import create_jwt, set_auth_cookie, clear_auth_cookie
from chainlit.user import User as ChainlitUser
import uvicorn

os.environ.setdefault("CHAINLIT_CUSTOM_AUTH", "true")


def _set_chainlit_auth_cookie(request: Request, response: Response, chainlit_user: ChainlitUser) -> None:
    """
    Bridges our Google login into Chainlit's own native cookie auth, so
    /agent (mounted Chainlit, with header_auth_callback removed and
    CHAINLIT_CUSTOM_AUTH=true) authenticates the same request /chat did.
    Uses the real chainlit.auth.create_jwt / set_auth_cookie rather than a
    hand-rolled cookie, signed with the same CHAINLIT_AUTH_SECRET.

    set_auth_cookie's exact parameter list isn't pinned to one Chainlit
    version here — this tries the (request, response, token) shape used by
    current Chainlit releases and falls back to the older (response, token)
    shape rather than guessing wrong and silently breaking auth again.
    """
    token = create_jwt(chainlit_user)
    try:
        set_auth_cookie(request, response, token)
    except TypeError:
        set_auth_cookie(response, token)


original_signal = signal.signal

def patched_signal(signalnum, handler):
    if threading.current_thread() is threading.main_thread():
        try:
            return original_signal(signalnum, handler)
        except ValueError:
            return None
    return None

signal.signal = patched_signal

try:
    from .database import init_db, SessionLocal, DBUser, get_db
    from .auth import (
        get_session_user,
        create_session_token,
        SESSION_COOKIE_NAME,
        get_google_auth_url,
        verify_google_code,
        generate_api_key,
        create_streamlit_sso_token,
    )
except ImportError:
    from database import init_db, SessionLocal, DBUser, get_db
    from auth import (
        get_session_user,
        create_session_token,
        SESSION_COOKIE_NAME,
        get_google_auth_url,
        verify_google_code,
        generate_api_key,
        create_streamlit_sso_token,
    )

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()

    yield

app = FastAPI(
    title="Smart Query Web Application",
    lifespan=lifespan
)

os.makedirs("public/css", exist_ok=True)
app.mount("/static", StaticFiles(directory="public"), name="static")
templates = Jinja2Templates(directory="templates")

# ----------------- WEB ROUTES -----------------

@app.get("/", response_class=HTMLResponse)
async def home_page(request: Request):
    """Serve public homepage."""
    user = get_session_user(request)
    return templates.TemplateResponse("home.html", {"request": request, "user": user})

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/chat", error: str = None):
    """Serve login authentication portal."""
    user = get_session_user(request)
    if user:
        return RedirectResponse(url=next)
    return templates.TemplateResponse("login.html", {
        "request": request,
        "next_url": next,
        "error": error
    })

@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    """Serve Chat screen (FastAPI auth guard wrapper)."""
    user = get_session_user(request)
    if not user:
        return RedirectResponse(url="/login?next=/chat")
    return templates.TemplateResponse("chat.html", {"request": request, "user": user})

@app.get("/explorer", response_class=HTMLResponse)
async def explorer_page(request: Request):
    """Render the authenticated Streamlit wrapper with a short-lived SSO token."""
    user = get_session_user(request)
    if not user:
        return RedirectResponse(url="/login?next=/explorer")

    streamlit_url = os.getenv("STREAMLIT_APP_URL")
    if not streamlit_url:
        return HTMLResponse(
            "Streamlit is not configured. Set STREAMLIT_APP_URL in the Render environment.",
            status_code=503,
        )

    streamlit_url = streamlit_url.rstrip("/")
    sso_token = create_streamlit_sso_token(user, expires_minutes=5)

    return templates.TemplateResponse(
        "explorer.html",
        {
            "request": request,
            "user": user,
            "streamlit_url": streamlit_url,
            "streamlit_sso_token": sso_token,
        },
    )


@app.get("/auth/google/login")
async def google_login(next: str = "/chat"):
    """Redirect to Google authentication consent screen."""
    state = next
    auth_url = get_google_auth_url(state)
    return RedirectResponse(url=auth_url)

@app.get("/auth/google/callback")
async def google_callback(
    request: Request,
    code: str = None,
    state: str = "/chat",
    db: Session = Depends(get_db)
):
    """Process Google OAuth sign-in callback."""
    if not code:
        return RedirectResponse(url=f"/login?next={state}&error=Google+login+failed")

    profile = verify_google_code(code)
    if not profile:
        return RedirectResponse(url=f"/login?next={state}&error=Failed+to+exchange+OAuth+tokens")

    db_user = db.query(DBUser).filter(DBUser.id == profile["id"]).first()
    if not db_user:
        db_user = db.query(DBUser).filter(DBUser.email == profile["email"]).first()
        if db_user:
            db_user.id = profile["id"]
        else:
            db_user = DBUser(
                id=profile["id"],
                email=profile["email"],
                username=profile["name"],
                api_key=generate_api_key(),
            )
            db.add(db_user)
        db.commit()
        db.refresh(db_user)

    name = db_user.username or db_user.email

    token = create_session_token({
        "sub": db_user.id,
        "email": db_user.email,
        "name": name
    })

    redirect = RedirectResponse(url=state)
    redirect.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        max_age=7 * 24 * 3600,
        samesite="lax",
        path="/"
    )

    chainlit_user = ChainlitUser(
        identifier=db_user.email,
        metadata={"email": db_user.email, "name": name},
    )
    try:
        _set_chainlit_auth_cookie(request, redirect, chainlit_user)
    except Exception as e:
        print(f"[google_callback] Failed to set Chainlit auth cookie for {db_user.email}: "
              f"{type(e).__name__}: {e}. /chat and /explorer will still work; "
              "/agent will show as logged out until this is fixed.")

    return redirect

@app.get("/auth/logout")
async def logout(request: Request):
    """Clear the session cookie, then log out."""
    redirect = RedirectResponse(url="/")
    redirect.delete_cookie(SESSION_COOKIE_NAME, path="/")
    try:
        clear_auth_cookie(request, redirect)
    except TypeError:
        clear_auth_cookie(redirect)
    except Exception as e:
        print(f"[logout] Failed to clear Chainlit auth cookie: {type(e).__name__}: {e}")
    return redirect

mount_chainlit(app=app, target="src/app.py", path="/agent")

if __name__ == "__main__":

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.environ["PYTHONPATH"] = project_root + os.pathsep + os.environ.get("PYTHONPATH", "")
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True)
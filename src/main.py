import os
import sys
from contextlib import asynccontextmanager
from datetime import timedelta
import uvicorn
from chainlit.utils import mount_chainlit
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import auth
import database

load_dotenv()
STREAMLIT_APP_URL = os.getenv("STREAMLIT_APP_URL", "")

def safe_next(path: str) -> str:
    """Only allow same-site relative paths as a post-login redirect target,
    so `next`/`state` can't be used to redirect users off-site."""
    if path.startswith("/") and not path.startswith("//"):
        return path
    return "/chat"

@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    yield

app = FastAPI(title="Smart Query", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="public"), name="static")
templates = Jinja2Templates(directory="templates")

# Web pages
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        "home.html",
        {"request": request, "user": auth.get_session_user(request)},
    )

@app.get("/login", response_class=HTMLResponse)
async def login(request: Request, next_url: str = "/chat", error: str | None = None):
    next_url = safe_next(next_url)
    if auth.get_session_user(request):
        return RedirectResponse(url=next_url)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "next_url": next_url, "error": error},
    )

@app.get("/chat", response_class=HTMLResponse)
async def chat(request: Request):
    user = auth.get_session_user(request)
    if not user:
        return RedirectResponse(url="/login?next=/chat")
    return templates.TemplateResponse(
        "chat.html",
        {"request": request, "user": user},
    )

@app.get("/explorer", response_class=HTMLResponse)
async def explorer(request: Request):
    user = auth.get_session_user(request)
    if not user:
        return RedirectResponse(url="/login?next=/explorer")
    if not STREAMLIT_APP_URL:
        return HTMLResponse("Streamlit not configured.", status_code=503)

    return templates.TemplateResponse(
        "explorer.html",
        {
            "request": request,
            "user": user,
            "streamlit_url": STREAMLIT_APP_URL.rstrip("/"),
            "streamlit_sso_token": auth.create_token(user, timedelta(minutes=5), purpose="streamlit_sso"),
        },
    )

# Google OAuth
@app.get("/auth/google/login")
async def google_login(next: str = "/chat"):
    return RedirectResponse(url=auth.get_google_auth_url(state=safe_next(next)))

@app.get("/auth/google/callback")
async def google_callback(request: Request, code: str | None = None, state: str = "/chat"):
    state = safe_next(state)
    if not code or not (profile := auth.verify_google_code(code)):
        return RedirectResponse(url=f"/login?next={state}&error=Google+login+failed")

    user = database.get_or_create_user(profile.id, profile.email, profile.name)
    response = RedirectResponse(url=state)
    auth.set_session_cookies(response, request, user)
    return response

@app.get("/auth/logout")
async def logout(request: Request):
    response = RedirectResponse(url="/")
    auth.clear_session_cookies(response, request)
    return response

mount_chainlit(app=app, target="src/app.py", path="/agent")

if __name__ == "__main__":
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True)
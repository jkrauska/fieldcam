"""Authentication routes and handlers for the fieldcam application."""

import asyncio
import logging
import time
from collections import defaultdict

from fastapi import HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse

from .config import login_manager, settings
from . import routes

# --- Brute-force backoff state ---
_fail_counts: dict[str, int] = defaultdict(int)
_last_fail: dict[str, float] = defaultdict(float)
_BACKOFF_THRESHOLD = 5  # failures before adding delay
_BACKOFF_SECONDS = 3  # delay per attempt beyond the threshold
_FAIL_WINDOW = 600  # reset counter after 10 minutes of no failures


def _client_ip(request: Request) -> str:
    """Best-effort client IP (respects X-Forwarded-For from ProxyHeadersMiddleware)."""
    return request.client.host if request.client else "unknown"


@login_manager.user_loader()
def load_user(user_id: str):
    """Load user for authentication."""
    if user_id == "admin_user":
        return {"user_id": user_id, "is_admin": True}
    if user_id == "shared_user":
        return {"user_id": user_id, "is_admin": False}
    return None


async def handle_login(request: Request, response: Response) -> tuple[Response, bool, str]:
    """
    Handle login POST request.
    Returns (response, success, next_url).
    When success, response has Set-Cookie; caller may replace body with fragment for SPA.
    When failure, response is login fragment with error so client can patch in place.
    """
    ip = _client_ip(request)

    form = await request.form()
    password = form.get("password")
    next_val = form.get("next") or "/"
    next_url = next_val if isinstance(next_val, str) else "/"

    # Reset counter if last failure was long ago
    if time.time() - _last_fail[ip] > _FAIL_WINDOW:
        _fail_counts[ip] = 0

    # Apply backoff delay if too many recent failures
    if _fail_counts[ip] >= _BACKOFF_THRESHOLD:
        delay = _BACKOFF_SECONDS * (_fail_counts[ip] - _BACKOFF_THRESHOLD + 1)
        delay = min(delay, 30)  # cap at 30s
        logging.warning(f"Login backoff: {ip} delayed {delay}s (attempt {_fail_counts[ip] + 1})")
        await asyncio.sleep(delay)

    # Determine role: admin password takes priority, then regular passwords
    is_admin = settings.admin_password and password == settings.admin_password
    is_regular = password in settings.passwords_list

    if not is_admin and not is_regular:
        _fail_counts[ip] += 1
        _last_fail[ip] = time.time()
        logging.warning(f"Login FAILED from {ip} (attempt {_fail_counts[ip]})")
        content = routes._render_login_fragment(request, next_url, error="Invalid password.")
        return (
            HTMLResponse(
                content=content,
                headers={"datastar-selector": "#app-content", "datastar-mode": "inner"},
            ),
            False,
            next_url,
        )

    user_id = "admin_user" if is_admin else "shared_user"

    # Success — reset counter
    _fail_counts.pop(ip, None)
    _last_fail.pop(ip, None)
    logging.info(f"Login OK from {ip} (role={'admin' if is_admin else 'user'})")

    resp = RedirectResponse(url=next_url, status_code=302)
    access_token = login_manager.create_access_token(data={"sub": user_id})
    # Set cookie with SameSite=Lax for CSRF defense
    resp.set_cookie(
        key=login_manager.cookie_name,
        value=access_token,
        httponly=True,
        samesite="lax",
    )
    return (resp, True, next_url)


def handle_logout(response: Response) -> RedirectResponse:
    """Handle logout: redirect to / so SPA shows shell with login form (no /login URL)."""
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie(login_manager.cookie_name)
    return response


async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions. 401: return SPA shell with login form (no redirect, URL unchanged)."""
    if exc.status_code == status.HTTP_401_UNAUTHORIZED:
        next_url = request.url.path or "/"
        if not isinstance(next_url, str) or len(next_url) <= 1:
            next_url = "/"
        logging.info(f"Returning shell with login form for next={next_url} (SPA, no redirect)")
        return routes.render_shell_with_login(request, next_url)
    return HTMLResponse(
        content=f"<div id='error'>{exc.detail}</div>",
        status_code=exc.status_code,
    )

"""Authentication routes and handlers for the fieldcam application."""

import logging

from fastapi import HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse

from .config import login_manager, settings
from . import routes


@login_manager.user_loader()
def load_user(user_id: str):
    """Load user for authentication."""
    if user_id == "shared_user":
        return {"user_id": user_id}
    return None


async def handle_login(request: Request, response: Response) -> tuple[Response, bool, str]:
    """
    Handle login POST request.
    Returns (response, success, next_url).
    When success, response has Set-Cookie; caller may replace body with fragment for SPA.
    When failure, response is login fragment with error so client can patch in place.
    """
    cookies = request.cookies
    logging.info(f"Incoming Cookies: {cookies}")
    user_id = "shared_user"

    form = await request.form()
    password = form.get("password")
    next_val = form.get("next") or "/"
    next_url = next_val if isinstance(next_val, str) else "/"

    logging.info("Password check")
    if password not in settings.passwords_list:
        content = routes._render_login_fragment(request, next_url, error="Invalid password.")
        return (
            HTMLResponse(
                content=content,
                headers={"datastar-selector": "#app-content", "datastar-mode": "inner"},
            ),
            False,
            next_url,
        )

    resp = RedirectResponse(url=next_url, status_code=302)
    access_token = login_manager.create_access_token(data={"sub": user_id})
    login_manager.set_cookie(resp, access_token)
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

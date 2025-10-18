"""Authentication routes and handlers for the fieldcam application."""

import logging
from urllib.parse import urlencode

from fastapi import HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse

from .config import login_manager, settings


def create_redirect_content(next: str, result: str = "unsuccessful") -> str:
    """Create HTML content for redirect with a message."""
    return f"""
        <html><head><title>Redirecting...</title>
        <script type="text/javascript">
        setTimeout(function() {{
        window.location.href = "{next}";
        }}, 100);
        </script></head>
        <body><p>Login {result}. Try again?...</p></body>
        </html>
    """


@login_manager.user_loader()
def load_user(user_id: str):
    """Load user for authentication."""
    if user_id == "shared_user":
        return {"user_id": user_id}
    return None


def get_login_form(next: str | None = None) -> HTMLResponse:
    """Generate the login form HTML."""
    next_input = f'<input type="hidden" name="next" value="{next}" />' if next else ""
    return HTMLResponse(f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Login</title>
            <style>
                * {{
                    margin: 0;
                    padding: 0;
                    box-sizing: border-box;
                    font-family: Arial, sans-serif;
                }}

                body {{
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    height: 100vh;
                    background: #f4f4f4;
                    padding: 20px;
                }}

                .login-container {{
                    width: 100%;
                    max-width: 350px;
                    padding: 20px;
                    background: white;
                    border-radius: 10px;
                    box-shadow: 0 4px 10px rgba(0, 0, 0, 0.1);
                    text-align: center;
                }}

                .login-container h2 {{
                    margin-bottom: 20px;
                }}

                .input-group {{
                    margin-bottom: 15px;
                    text-align: left;
                }}

                .input-group label {{
                    display: block;
                    font-size: 14px;
                    margin-bottom: 5px;
                }}

                .input-group input {{
                    width: 100%;
                    padding: 10px;
                    border: 1px solid #ccc;
                    border-radius: 5px;
                    font-size: 16px;
                }}

                .login-btn {{
                    width: 100%;
                    padding: 10px;
                    background: #007BFF;
                    color: white;
                    border: none;
                    border-radius: 5px;
                    font-size: 16px;
                    cursor: pointer;
                    transition: background 0.3s ease-in-out;
                }}

                .login-btn:hover {{
                    background: #0056b3;
                }}

                @media (max-width: 400px) {{
                    .login-container {{
                        padding: 15px;
                    }}
                }}
            </style>
        </head>
        <body>
            <div class="login-container">
                <h2>Login</h2>
                <form action="#" method="POST">
                    {next_input}
                    <div class="input-group">
                        <label for="password">Password</label>
                        <input type="password" id="password" name="password" required>
                    </div>
                    <button type="submit" class="login-btn">Login</button>
                </form>
            </div>
        </body>
        </html>
    """)


async def handle_login(request: Request, response: Response) -> HTMLResponse:
    """Handle login POST request."""
    cookies = request.cookies
    logging.info(f"Incoming Cookies: {cookies}")
    user_id = "shared_user"

    form = await request.form()
    password = form.get("password")
    next = form.get("next") or "/list"

    logging.info("Password check")
    if password not in settings.passwords_list:
        return create_redirect_content(next)

    # Redirect to the original page if 'next' is provided
    next_url = next or "/list"

    response = HTMLResponse(content=create_redirect_content(next_url, "successful"))
    access_token = login_manager.create_access_token(data={"sub": user_id})
    login_manager.set_cookie(response, access_token)
    return response


def handle_logout(response: Response) -> RedirectResponse:
    """Handle logout request."""
    response = RedirectResponse(url="/login")
    response.delete_cookie(login_manager.cookie_name)
    return response


async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions, particularly 401 Unauthorized."""
    if exc.status_code == status.HTTP_401_UNAUTHORIZED:
        next_url = request.url.path
        logging.info(f"Redirecting to login page with next={next_url}")

        login_url = "/login"
        if isinstance(next_url, str) and len(next_url) > 3:
            redirect_url = f"{login_url}?{urlencode({'next': next_url})}"
        else:
            redirect_url = login_url
        return RedirectResponse(url=redirect_url, status_code=302)
    else:
        # Re-raise the exception for other status codes
        raise exc

# Instructions for AI agents

When working on this repository, follow these conventions:

1. **Use uv for all Python tooling.** Run and install via `uv run`, `uv add`, `uv sync`, etc. Do not use bare `python` or `pip` in commands or documentation.

2. **Prioritize Datastar and the SPA model.** Use Datastar for partial HTML fragments and updates (`datastar-selector` / `datastar-mode` responses). Use the existing SPA shell and router (`base_shell.html.j2`, `spa-router.js`). Avoid full-page reloads when the SPA approach fits.

3. **Lint before commit.** Always run `uv run ruff check . && uv run ruff format .` from `cam-app/` before every git commit. Fix any issues before committing.

4. **Require login for features.** Any route or API that should be restricted to logged-in users must use `user=Depends(login_manager)` (from `app.config`). Do not add new user-facing or mutation endpoints without this dependency.

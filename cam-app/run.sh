#!/usr/bin/env bash
exec uv run uvicorn app.main:app --reload --port 9191 --host 0.0.0.0 --timeout-graceful-shutdown 3

"""FastAPI application factory."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db, scheduler, service, settings_store
from .config import REPO_ROOT, get_settings
from .providers.http import WriteAttemptBlocked
from .routes import agent, analytics, reviews, runs, system, wakeups
from .routes import settings as settings_routes  # `settings` is the config object below

DESCRIPTION = """\
selfcheck is a local, read-only review workbench for GitHub pull requests and
GitLab merge requests.

**It never writes to a forge.** Provider traffic goes through a client that
refuses any verb other than GET/HEAD, repo mirrors have their push URL pinned to
a non-URL, and the Claude process that reviews your code runs with `Write`,
`Edit`, `Bash`, `WebFetch` and MCP all disabled against a chmod-read-only
checkout. Review notes live in a local SQLite file; exporting them means copying
markdown yourself.

Reviews run on a choice of engine (Claude Code, Codex, Cursor Agent, the
Anthropic API, or any OpenAI-compatible endpoint) at one of three depths
(light, normal, thorough). Repository wakeups check a repo on a schedule and
review new pull requests as they appear.

See `GET /api/agent/guide` for how an agent should drive this API.
"""


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    import asyncio

    db.init_db()
    settings_store.init()
    service.recover_interrupted_runs()
    service.bind_loop(asyncio.get_running_loop())
    scheduler.start()
    try:
        yield
    finally:
        await scheduler.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="selfcheck",
        version="0.1.0",
        description=DESCRIPTION,
        lifespan=lifespan,
    )

    origins = [f"http://127.0.0.1:{settings.port}", f"http://localhost:{settings.port}",
               "http://127.0.0.1:5173", "http://localhost:5173"]
    origins += [o.strip() for o in settings.extra_cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.exception_handler(WriteAttemptBlocked)
    async def _blocked(_request: Request, exc: WriteAttemptBlocked) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    app.include_router(system.router)
    app.include_router(reviews.router)
    app.include_router(runs.router)
    app.include_router(agent.router)
    app.include_router(wakeups.router)
    app.include_router(analytics.router)
    app.include_router(settings_routes.router)

    _mount_web(app)
    return app


def _mount_web(app: FastAPI) -> None:
    """Serve the built frontend, when there is one."""
    dist = REPO_ROOT / "web" / "dist"
    if not dist.is_dir():
        @app.get("/", include_in_schema=False)
        def _no_ui() -> JSONResponse:
            return JSONResponse(
                {
                    "selfcheck": "api is up, but the web UI has not been built",
                    "build_it": "cd web && pnpm install && pnpm build",
                    "or_dev": "cd web && pnpm dev   (proxies /api to this server)",
                    "docs": "/docs",
                    "agent_guide": "/api/agent/guide",
                }
            )
        return

    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def _spa(full_path: str) -> FileResponse:
        candidate = dist / full_path
        if full_path and candidate.is_file() and Path(candidate).resolve().is_relative_to(dist):
            return FileResponse(candidate)
        # Always revalidate the page itself: it names the hashed asset files, so
        # a cached copy keeps serving the previous UI after an update.
        return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})


app = create_app()

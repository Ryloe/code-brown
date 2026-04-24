"""FastAPI app: public GET /health; all other routes require Bearer token from API_KEY env."""

from __future__ import annotations

import os
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.responses import Response
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ.get("API_KEY", "").strip()


def _is_public_path(path: str) -> bool:
    return path == "/health" or path.rstrip("/") == "/health"


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not API_KEY:
        raise RuntimeError("API_KEY environment variable must be set and non-empty")
    yield


app = FastAPI(
    title="code-brown backend",
    lifespan=lifespan,
)


@app.middleware("http")
async def bearer_auth_middleware(request: Request, call_next):
    if _is_public_path(request.url.path):
        return await call_next(request)

    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    token = auth.removeprefix("Bearer ").strip()
    if not secrets.compare_digest(token, API_KEY):
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    return await call_next(request)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.head("/health")
def health_head():
    return Response(status_code=200)

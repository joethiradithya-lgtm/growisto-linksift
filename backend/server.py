"""
server.py
---------
FastAPI server that exposes the agentic backlink analyzer.

Endpoints:
    POST /api/analyze    — runs the agent on a batch, streams SSE events
    GET  /                — serves the frontend
    GET  /healthz         — health check

Run:
    export ANTHROPIC_API_KEY=sk-ant-...
    uvicorn server:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from pydantic import BaseModel, Field

from agent import analyze_batch_agentic


app = FastAPI(title="LinkSift Agent")

# Permissive CORS for local dev. Tighten this in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request model ──────────────────────────────────────────────────────
class Backlink(BaseModel):
    domain: str
    dr: float = 0
    traffic: float = 0
    spam: float = 0
    category: str = ""
    description: str = ""
    country: str = ""
    language: str = ""


class AnalyzeRequest(BaseModel):
    target_domain: str
    industry: str
    geography: str
    window_months: int = Field(6, ge=1, le=24)
    backlinks: list[Backlink]
    batch_size: int = Field(15, ge=1, le=50)


# ── Streaming endpoint ─────────────────────────────────────────────────
def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@app.post("/api/analyze")
async def analyze(req: AnalyzeRequest):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(
            status_code=500,
            detail="ANTHROPIC_API_KEY not set on the server.",
        )

    if not req.backlinks:
        raise HTTPException(400, "No backlinks provided.")

    backlinks = [b.model_dump() for b in req.backlinks]
    # Split into batches
    batches = [
        backlinks[i : i + req.batch_size]
        for i in range(0, len(backlinks), req.batch_size)
    ]

    async def stream():
        yield _sse(
            "start",
            {"total": len(backlinks), "batches": len(batches)},
        )

        all_results: list[dict] = []
        for i, batch in enumerate(batches):
            yield _sse(
                "batch_start",
                {"index": i + 1, "total": len(batches), "size": len(batch)},
            )
            try:
                async for ev in analyze_batch_agentic(
                    batch=batch,
                    target_domain=req.target_domain,
                    industry=req.industry,
                    geography=req.geography,
                    window_months=req.window_months,
                ):
                    yield _sse(ev["type"], ev)
                    if ev["type"] == "batch_done":
                        all_results.extend(ev["results"])
            except Exception as e:  # noqa: BLE001
                yield _sse(
                    "error",
                    {"message": f"Batch {i+1} failed: {e}"},
                )

        yield _sse("done", {"results": all_results, "count": len(all_results)})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── Health ─────────────────────────────────────────────────────────────
@app.get("/healthz")
async def healthz():
    return {
        "ok": True,
        "anthropic_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
    }


# ── Frontend ───────────────────────────────────────────────────────────
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@app.get("/")
async def index():
    f = FRONTEND_DIR / "index.html"
    if not f.exists():
        return JSONResponse({"error": "frontend not built"}, status_code=404)
    return FileResponse(f)

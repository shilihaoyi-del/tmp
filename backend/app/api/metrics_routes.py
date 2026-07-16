"""Metrics / scenarios / bench harness APIs (reserved for stress & perf)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.services.metrics import APPLICATION_SCENARIOS, metrics_store

router = APIRouter(prefix="/metrics", tags=["metrics"])


class BenchStartRequest(BaseModel):
    bench_id: str = Field(..., description="External runner id, e.g. stress-2026-07-16")
    target_hz: int = Field(25, ge=1, le=200)
    notes: str = ""
    scenario_id: Optional[str] = Field(
        None,
        description="Optional APPLICATION_SCENARIOS id to tag this run",
    )


@router.get("")
async def get_metrics() -> dict:
    """Live traffic + latency snapshot for dashboards / k6 / locust collectors."""
    metrics_store.record_http()
    return metrics_store.snapshot()


@router.get("/history")
async def get_metrics_history(limit: int = Query(120, ge=10, le=600)) -> dict:
    """Rolling latency samples. Reserved series listed for future exporters."""
    metrics_store.record_http()
    return metrics_store.history(limit=limit)


@router.get("/scenarios")
async def list_scenarios() -> dict:
    """Product application scenarios + which metrics each scenario cares about."""
    metrics_store.record_http()
    return {
        "hero": "Fibocom SC171V2",
        "scenarios": APPLICATION_SCENARIOS,
    }


@router.get("/bench")
async def bench_status() -> dict:
    """Reserved stress/perf harness status."""
    metrics_store.record_http()
    return metrics_store.snapshot()["bench"]


@router.post("/bench/start")
async def bench_start(body: BenchStartRequest) -> dict:
    """
    Mark a bench session active so external runners can correlate samples.
    Does not generate load itself — reserved hook for pressure / perf suites.
    """
    metrics_store.record_http()
    notes = body.notes
    if body.scenario_id:
        notes = f"scenario={body.scenario_id}; {notes}".strip("; ")
    return {
        "ok": True,
        "bench": metrics_store.start_bench(body.bench_id, body.target_hz, notes),
        "hint": "Drive arm/pc/cmd or POST /api/cmd from your load generator; poll GET /api/metrics",
    }


@router.post("/bench/stop")
async def bench_stop() -> dict:
    metrics_store.record_http()
    return {"ok": True, "bench": metrics_store.stop_bench()}

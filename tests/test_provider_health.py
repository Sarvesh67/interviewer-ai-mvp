"""
Provider Health Check — Verify all API providers are reachable and keys are valid.

Designed for MINIMAL resource consumption:
- No interviews created, no questions generated, no audio processed
- Uses list/metadata endpoints only (free or near-zero cost)
- Safe to run repeatedly

Usage:
    python tests/test_provider_health.py          # Run all checks
    python -m pytest tests/test_provider_health.py -v  # Via pytest
"""
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Optional

# Ensure repo root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from config import settings, validate_api_keys, get_missing_realtime_keys


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

class ProviderResult:
    def __init__(self, name: str):
        self.name = name
        self.ok = False
        self.latency_ms: Optional[float] = None
        self.error: Optional[str] = None
        self.stats: dict = {}

    def __repr__(self):
        status = "PASS" if self.ok else "FAIL"
        latency = f" ({self.latency_ms:.0f}ms)" if self.latency_ms else ""
        err = f" — {self.error}" if self.error else ""
        return f"[{status}] {self.name}{latency}{err}"


def _timed(func):
    """Decorator to measure execution time."""
    async def wrapper(*args, **kwargs):
        start = time.monotonic()
        result = await func(*args, **kwargs)
        result.latency_ms = (time.monotonic() - start) * 1000
        return result
    return wrapper


# ──────────────────────────────────────────────
# Provider Checks
# ──────────────────────────────────────────────

@_timed
async def check_gemini() -> ProviderResult:
    """Verify Gemini key by listing available models (free, no tokens consumed)."""
    r = ProviderResult("Google Gemini")
    if not settings.GEMINI_API_KEY:
        r.error = "GEMINI_API_KEY not set"
        return r

    try:
        import google.generativeai as genai
        genai.configure(api_key=settings.GEMINI_API_KEY)
        models = list(genai.list_models())
        model_names = [m.name for m in models if "gemini" in m.name.lower()]
        r.ok = True
        r.stats = {
            "available_models": len(model_names),
            "question_gen_model": settings.GEMINI_MODEL,
            "scoring_model": settings.GEMINI_SCORING_MODEL,
            "question_gen_available": any(settings.GEMINI_MODEL in m for m in model_names),
            "scoring_available": any(settings.GEMINI_SCORING_MODEL in m for m in model_names),
        }
    except Exception as e:
        r.error = str(e)
    return r


@_timed
async def check_livekit() -> ProviderResult:
    """Verify LiveKit credentials by listing rooms (free, no rooms created)."""
    r = ProviderResult("LiveKit")
    if not all([settings.LIVEKIT_URL, settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET]):
        r.error = "LIVEKIT_URL, LIVEKIT_API_KEY, or LIVEKIT_API_SECRET not set"
        return r

    try:
        from livekit import api as lk_api
        from livekit.protocol.room import ListRoomsRequest
        livekit = lk_api.LiveKitAPI(
            url=settings.LIVEKIT_URL,
            api_key=settings.LIVEKIT_API_KEY,
            api_secret=settings.LIVEKIT_API_SECRET,
        )
        rooms = await livekit.room.list_rooms(ListRoomsRequest())
        r.ok = True
        r.stats = {
            "url": settings.LIVEKIT_URL,
            "active_rooms": len(rooms.rooms) if rooms.rooms else 0,
        }
        await livekit.aclose()
    except Exception as e:
        r.error = str(e)
    return r


@_timed
async def check_hedra() -> ProviderResult:
    """Verify Hedra key by listing assets (free, no assets created)."""
    r = ProviderResult("Hedra")
    if not settings.HEDRA_API_KEY:
        r.error = "HEDRA_API_KEY not set"
        return r

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # Try listing projects/assets — different Hedra API versions have different list endpoints
            for endpoint in ["/assets", "/v1/assets", "/projects"]:
                resp = await client.get(
                    f"{settings.HEDRA_API_URL}{endpoint}",
                    headers={"X-API-Key": settings.HEDRA_API_KEY},
                )
                if resp.status_code == 200:
                    r.ok = True
                    r.stats = {"api_url": settings.HEDRA_API_URL, "endpoint": endpoint}
                    return r
                elif resp.status_code == 401:
                    r.error = "Invalid API key (401)"
                    return r

            # If no list endpoint worked, verify key with a HEAD/GET to base URL
            resp = await client.get(
                settings.HEDRA_API_URL,
                headers={"X-API-Key": settings.HEDRA_API_KEY},
            )
            if resp.status_code in (200, 404):
                # 404 is ok — means the key was accepted but no root endpoint
                r.ok = True
                r.stats = {"api_url": settings.HEDRA_API_URL, "note": "Key accepted, no list endpoint found"}
            elif resp.status_code == 401:
                r.error = "Invalid API key (401)"
            else:
                r.error = f"HTTP {resp.status_code} — key may be valid but no lightweight test endpoint found"
    except Exception as e:
        r.error = str(e)
    return r


@_timed
async def check_deepgram() -> ProviderResult:
    """Verify Deepgram key by fetching project info (free, no audio processed). Used for STT + TTS."""
    r = ProviderResult("Deepgram")
    if not settings.DEEPGRAM_API_KEY:
        r.error = "DEEPGRAM_API_KEY not set"
        return r

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://api.deepgram.com/v1/projects",
                headers={"Authorization": f"Token {settings.DEEPGRAM_API_KEY}"},
            )
            if resp.status_code == 200:
                r.ok = True
                data = resp.json()
                projects = data.get("projects", [])
                if projects:
                    r.stats = {
                        "project_id": projects[0].get("project_id", ""),
                        "project_name": projects[0].get("name", ""),
                    }
                    # Try to get usage/balance for the first project
                    project_id = projects[0].get("project_id")
                    if project_id:
                        balance_resp = await client.get(
                            f"https://api.deepgram.com/v1/projects/{project_id}/balances",
                            headers={"Authorization": f"Token {settings.DEEPGRAM_API_KEY}"},
                        )
                        if balance_resp.status_code == 200:
                            balances = balance_resp.json().get("balances", [])
                            if balances:
                                b = balances[0]
                                r.stats["balance"] = b.get("amount", "unknown")
                                r.stats["units"] = b.get("units", "")
            elif resp.status_code == 401:
                r.error = "Invalid API key (401)"
            else:
                r.error = f"HTTP {resp.status_code}"
    except Exception as e:
        r.error = str(e)
    return r

# ──────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────

async def run_all_checks() -> list[ProviderResult]:
    """Run all provider checks concurrently."""
    results = await asyncio.gather(
        check_gemini(),
        check_livekit(),
        check_hedra(),
        check_deepgram(),
    )
    return list(results)


def print_report(results: list[ProviderResult]):
    """Print a formatted health report."""
    print("\n" + "=" * 60)
    print("  AI INTERVIEWER — PROVIDER HEALTH CHECK")
    print("=" * 60)

    passed = sum(1 for r in results if r.ok)
    total = len(results)

    for r in results:
        icon = "  OK " if r.ok else " FAIL"
        latency = f"  {r.latency_ms:>6.0f}ms" if r.latency_ms else "        "
        err = f"  {r.error}" if r.error else ""
        print(f"  [{icon}]{latency}  {r.name}{err}")

    # Stats section
    has_stats = [r for r in results if r.stats]
    if has_stats:
        print("\n" + "-" * 60)
        print("  STATS")
        print("-" * 60)
        for r in has_stats:
            print(f"\n  {r.name}:")
            for k, v in r.stats.items():
                print(f"    {k}: {v}")

    # Summary
    print("\n" + "-" * 60)
    status_key = validate_api_keys()
    missing_rt = get_missing_realtime_keys()

    print(f"\n  Providers: {passed}/{total} passed")
    print(f"  Core interview (Hedra + Gemini): {'READY' if all(r.ok for r in results if r.name in ['Hedra', 'Google Gemini']) else 'NOT READY'}")
    print(f"  Real-time mode (+ LiveKit + Deepgram): {'READY' if not missing_rt and all(r.ok for r in results) else 'NOT READY'}")

    if not all(r.ok for r in results):
        failed = [r.name for r in results if not r.ok]
        print(f"\n  Action needed: Fix {', '.join(failed)}")

    print("\n" + "=" * 60 + "\n")
    return passed == total


# ──────────────────────────────────────────────
# Pytest integration
# ──────────────────────────────────────────────

import pytest


@pytest.mark.asyncio
async def test_all_providers_healthy():
    """Pytest entry point — fails if any required provider is unreachable."""
    results = await run_all_checks()
    print_report(results)

    # Required providers must pass
    required = {"Google Gemini", "Hedra", "LiveKit", "Deepgram"}
    for r in results:
        if r.name in required:
            assert r.ok, f"{r.name} health check failed: {r.error}"


# ──────────────────────────────────────────────
# Standalone execution
# ──────────────────────────────────────────────

async def _run_and_report() -> bool:
    results = await run_all_checks()
    return print_report(results)


if __name__ == "__main__":
    ok = asyncio.run(_run_and_report())
    sys.exit(0 if ok else 1)

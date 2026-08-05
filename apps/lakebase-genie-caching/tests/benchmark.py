"""Genie Agent Benchmark Suite
===============================

Re-runnable, multi-phase benchmark that exercises every pipeline path:
  Phase 0 (SMOKE)          – frontend & API smoke tests (UI rendering, links, SSE)
  Phase 1 (COLD)           – 20 fresh questions, cache empty → all data Qs miss
  Phase 2 (WARM)           – re-send 10 single-space Qs → expect cache hits
  Phase 3 (PARAMETERIZED)  – 5 entity-swapped variants → template / param hits
  Phase 4 (REPHRASED)      – 5 semantically similar Qs → similarity matching

Questions span two Genie spaces, multi-space queries, and assistant routing.

Usage:
  python tests/benchmark.py [--url URL] [--plan-only] [--phase PHASE] [--concurrency N]

  --phase: SMOKE, COLD, WARM, PARAMETERIZED, REPHRASED, or ALL (default ALL)
"""

import argparse
import asyncio
import enum
import json
import statistics
import time
import uuid
from dataclasses import dataclass, field

import aiohttp

# ═══════════════════════════════════════════════════════════════════════════════
# Space IDs
# ═══════════════════════════════════════════════════════════════════════════════
# Two Genie spaces are needed to exercise multi-space supervisor routing.
# Set GENIE_SPACE_IDS="<first>,<second>" -- see tests/env_config.py.
# The question sets below are written for a cancer-incidence space and a
# clinical-trials space; swap them for your own domain when benchmarking
# different data.
from tests.env_config import require_genie_space_ids

_SPACE_IDS = require_genie_space_ids(minimum=2)
CANCER_SPACE_ID, TRIALS_SPACE_ID = _SPACE_IDS[0], _SPACE_IDS[1]

# ═══════════════════════════════════════════════════════════════════════════════
# Base questions  (20 total: 5 cancer, 5 trials, 5 multi, 5 assistant)
# ═══════════════════════════════════════════════════════════════════════════════
CANCER_QUESTIONS = [
    "What are the lung cancer incidence rates by year?",
    "Show breast cancer incidence rates by race",
    "Which cancer site has the highest incidence rate for males?",
    "How has prostate cancer incidence changed over time?",
    "Compare pancreas cancer rates between males and females",
]

TRIALS_QUESTIONS = [
    "How many Phase 3 clinical trials are currently recruiting?",
    "What are the top sponsors for breast cancer clinical trials?",
    "Show the distribution of clinical trials by study phase",
    "How many clinical trials were completed in the last 5 years?",
    "What is the average enrollment for Phase 2 interventional trials?",
]

MULTI_QUESTIONS = [
    "Compare lung cancer incidence rates with the number of lung cancer clinical trials",
    "For cancer types with rising incidence, how many clinical trials are recruiting?",
    "Show breast cancer incidence trends alongside breast cancer trial enrollment",
    "Which cancer types have the most clinical trials relative to their incidence?",
    "Compare prostate cancer incidence rates with the number of prostate cancer trials by phase",
]

ASSISTANT_QUESTIONS = [
    "Hello, what can you help me with?",
    "What data sources are available in this system?",
    "Thanks for the analysis!",
    "How does the caching system work?",
    "Can you explain what a Genie Space is?",
]

# ═══════════════════════════════════════════════════════════════════════════════
# Parameterized variants (entity-swapped versions of base questions)
# ═══════════════════════════════════════════════════════════════════════════════
PARAMETERIZED_VARIANTS = [
    {
        "question": "What are the stomach cancer incidence rates by year?",
        "base": CANCER_QUESTIONS[0],
        "change": "lung → stomach",
    },
    {
        "question": "Show colon and rectum cancer incidence rates by race",
        "base": CANCER_QUESTIONS[1],
        "change": "breast → colon and rectum",
    },
    {
        "question": "How many Phase 2 clinical trials are currently recruiting?",
        "base": TRIALS_QUESTIONS[0],
        "change": "Phase 3 → Phase 2",
    },
    {
        "question": "What are the top sponsors for lung cancer clinical trials?",
        "base": TRIALS_QUESTIONS[1],
        "change": "breast → lung",
    },
    {
        "question": "Compare stomach cancer rates between males and females",
        "base": CANCER_QUESTIONS[4],
        "change": "pancreas → stomach",
    },
]

# ═══════════════════════════════════════════════════════════════════════════════
# Rephrased variants (semantically similar, different wording)
# ═══════════════════════════════════════════════════════════════════════════════
REPHRASED_VARIANTS = [
    {
        "question": "Show me the yearly trend of lung cancer cases",
        "base": CANCER_QUESTIONS[0],
        "note": "rephrase of lung cancer by year",
    },
    {
        "question": "Incidence of breast cancer across different ethnic groups",
        "base": CANCER_QUESTIONS[1],
        "note": "rephrase of breast cancer by race",
    },
    {
        "question": "What phase are most clinical trials in?",
        "base": TRIALS_QUESTIONS[2],
        "note": "rephrase of trial phase distribution",
    },
    {
        "question": "How many trials finished in recent years?",
        "base": TRIALS_QUESTIONS[3],
        "note": "rephrase of completed trials",
    },
    {
        "question": "Average number of people enrolled in Phase 2 drug trials",
        "base": TRIALS_QUESTIONS[4],
        "note": "rephrase of Phase 2 enrollment",
    },
]

# ═══════════════════════════════════════════════════════════════════════════════
# Phases
# ═══════════════════════════════════════════════════════════════════════════════

class Phase(enum.Enum):
    SMOKE = "SMOKE"
    COLD = "COLD"
    WARM = "WARM"
    PARAMETERIZED = "PARAMETERIZED"
    REPHRASED = "REPHRASED"


# ═══════════════════════════════════════════════════════════════════════════════
# Data types
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class TestQuery:
    question: str
    category: str       # cancer, trials, multi, assistant, parameterized, rephrased
    base_question: str | None = None
    note: str = ""


@dataclass
class QueryResult:
    question: str
    category: str
    phase: str
    cache_status: str = "error"
    latency_ms: float = 0.0
    genie_latency_ms: float | None = None
    similarity_score: float | None = None
    wall_time_ms: float = 0.0
    error: str | None = None
    note: str = ""
    selected_space: str | None = None
    trace_id: str | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# Corpus builders
# ═══════════════════════════════════════════════════════════════════════════════

def build_cold_corpus() -> list[TestQuery]:
    """Phase 1: all 20 base questions."""
    corpus = []
    for q in CANCER_QUESTIONS:
        corpus.append(TestQuery(question=q, category="cancer"))
    for q in TRIALS_QUESTIONS:
        corpus.append(TestQuery(question=q, category="trials"))
    for q in MULTI_QUESTIONS:
        corpus.append(TestQuery(question=q, category="multi"))
    for q in ASSISTANT_QUESTIONS:
        corpus.append(TestQuery(question=q, category="assistant"))
    return corpus


def build_warm_corpus() -> list[TestQuery]:
    """Phase 2: re-send the 10 single-space data questions."""
    corpus = []
    for q in CANCER_QUESTIONS:
        corpus.append(TestQuery(question=q, category="cancer"))
    for q in TRIALS_QUESTIONS:
        corpus.append(TestQuery(question=q, category="trials"))
    return corpus


def build_parameterized_corpus() -> list[TestQuery]:
    """Phase 3: entity-swapped variants."""
    return [
        TestQuery(
            question=v["question"],
            category="parameterized",
            base_question=v["base"],
            note=v["change"],
        )
        for v in PARAMETERIZED_VARIANTS
    ]


def build_rephrased_corpus() -> list[TestQuery]:
    """Phase 4: semantically similar rephrasings."""
    return [
        TestQuery(
            question=v["question"],
            category="rephrased",
            base_question=v["base"],
            note=v["note"],
        )
        for v in REPHRASED_VARIANTS
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# HTTP helpers
# ═══════════════════════════════════════════════════════════════════════════════

async def ask_question(
    session: aiohttp.ClientSession,
    url: str,
    query: TestQuery,
    phase: str,
    user_id: str = "bench-user",
) -> QueryResult:
    start = time.perf_counter()
    try:
        async with session.post(
            f"{url}/api/ask",
            json={
                "question": query.question,
                "session_id": str(uuid.uuid4()),
                "user_id": user_id,
            },
            timeout=aiohttp.ClientTimeout(total=180),
        ) as resp:
            data = await resp.json()
            wall = (time.perf_counter() - start) * 1000
            if resp.status != 200 or "error" in data:
                return QueryResult(
                    question=query.question, category=query.category, phase=phase,
                    wall_time_ms=wall, error=data.get("error", f"HTTP {resp.status}"),
                    note=query.note,
                )
            return QueryResult(
                question=query.question, category=query.category, phase=phase,
                cache_status=data.get("cache_status", "unknown"),
                latency_ms=data.get("latency_ms", wall),
                genie_latency_ms=data.get("genie_latency_ms"),
                similarity_score=data.get("similarity_score"),
                wall_time_ms=wall, note=query.note,
                selected_space=data.get("selected_space_title"),
                trace_id=data.get("trace_id"),
            )
    except Exception as e:
        wall = (time.perf_counter() - start) * 1000
        return QueryResult(
            question=query.question, category=query.category, phase=phase,
            wall_time_ms=wall, error=f"{type(e).__name__}: {e}", note=query.note,
        )


async def api_call(session, url, method, path, json_body=None, retries=3):
    for attempt in range(retries):
        try:
            fn = getattr(session, method)
            kwargs = {"timeout": aiohttp.ClientTimeout(total=120)}
            if json_body is not None:
                kwargs["json"] = json_body
            async with fn(f"{url}{path}", **kwargs) as resp:
                return await resp.json()
        except Exception:
            if attempt < retries - 1:
                await asyncio.sleep(3)
            else:
                raise


# ═══════════════════════════════════════════════════════════════════════════════
# Phase runner
# ═══════════════════════════════════════════════════════════════════════════════

async def run_phase(
    url: str,
    corpus: list[TestQuery],
    phase: Phase,
    concurrency: int,
) -> tuple[list[QueryResult], float]:
    """Send all queries in a phase and return results + total wall time."""
    print(f"\n{'─' * 70}")
    print(f"  Phase: {phase.value} — {len(corpus)} queries (concurrency={concurrency})")
    print(f"{'─' * 70}")

    sem = asyncio.Semaphore(concurrency)
    start = time.perf_counter()

    async def throttled(session, q):
        async with sem:
            return await ask_question(session, url, q, phase.value)

    async with aiohttp.ClientSession() as session:
        tasks = [throttled(session, q) for q in corpus]
        results = await asyncio.gather(*tasks)

    wall = (time.perf_counter() - start) * 1000
    results = list(results)

    # Quick inline summary
    hits = sum(1 for r in results if r.cache_status == "hit")
    misses = sum(1 for r in results if r.cache_status == "miss")
    rejected = sum(1 for r in results if r.cache_status == "rejected")
    errors = sum(1 for r in results if r.error)
    lats = [r.latency_ms for r in results if not r.error]
    avg_lat = statistics.mean(lats) if lats else 0

    print(f"  → {hits} hits, {misses} misses, {rejected} rejected, {errors} errors")
    print(f"  → Avg latency: {avg_lat:,.0f} ms | Wall time: {wall:,.0f} ms")

    return results, wall


# ═══════════════════════════════════════════════════════════════════════════════
# Reporting
# ═══════════════════════════════════════════════════════════════════════════════

def print_phase_report(phase_name: str, results: list[QueryResult], wall_ms: float):
    print(f"\n{'=' * 80}")
    print(f"  {phase_name} RESULTS")
    print(f"{'=' * 80}")

    data_results = [r for r in results if not r.error]
    hits = [r for r in data_results if r.cache_status == "hit"]
    misses = [r for r in data_results if r.cache_status == "miss"]
    rejected = [r for r in data_results if r.cache_status == "rejected"]
    errors = [r for r in results if r.error]

    print(f"\n  Total queries:  {len(results)}")
    print(f"  Cache hits:     {len(hits)}")
    print(f"  Cache misses:   {len(misses)}")
    print(f"  Rejected:       {len(rejected)}")
    print(f"  Errors:         {len(errors)}")
    if data_results:
        print(f"  Hit rate:       {len(hits)/len(data_results)*100:.1f}%")

    all_lats = [r.latency_ms for r in data_results]
    if all_lats:
        hit_lats = [r.latency_ms for r in hits] or [0]
        miss_lats = [r.latency_ms for r in misses] or [0]

        def fmt(v):
            return f"{v:,.0f} ms"

        p95_idx = min(int(len(all_lats) * 0.95), len(all_lats) - 1)
        print(f"\n  {'Metric':<25} {'All':>12} {'Hits':>12} {'Misses':>12}")
        print(f"  {'-'*25} {'-'*12} {'-'*12} {'-'*12}")
        print(f"  {'Avg Latency':<25} {fmt(statistics.mean(all_lats)):>12} {fmt(statistics.mean(hit_lats)):>12} {fmt(statistics.mean(miss_lats)):>12}")
        print(f"  {'Median Latency':<25} {fmt(statistics.median(all_lats)):>12} {fmt(statistics.median(hit_lats)):>12} {fmt(statistics.median(miss_lats)):>12}")
        print(f"  {'P95 Latency':<25} {fmt(sorted(all_lats)[p95_idx]):>12}")
        print(f"  {'Min Latency':<25} {fmt(min(all_lats)):>12} {fmt(min(hit_lats)):>12} {fmt(min(miss_lats)):>12}")
        print(f"  {'Max Latency':<25} {fmt(max(all_lats)):>12} {fmt(max(hit_lats)):>12} {fmt(max(miss_lats)):>12}")

        if hits and misses:
            speedup = statistics.mean(miss_lats) / statistics.mean(hit_lats)
            print(f"\n  Cache speedup: {speedup:.1f}x")

    # Per-query detail
    print(f"\n  {'Cat':>14} {'Status':>8} {'Latency':>10} {'Sim':>6}  Question")
    print(f"  {'-'*14} {'-'*8} {'-'*10} {'-'*6}  {'-'*45}")
    for r in results:
        status = r.cache_status if not r.error else "ERROR"
        lat = f"{r.latency_ms:,.0f}ms"
        sim = f"{r.similarity_score:.3f}" if r.similarity_score else "—"
        q = r.question[:55]
        extra = f"  ({r.note})" if r.note else ""
        print(f"  {r.category:>14} {status:>8} {lat:>10} {sim:>6}  {q}{extra}")

    print(f"\n  Wall time: {wall_ms:,.0f} ms ({wall_ms/1000:.1f}s)")


def print_final_report(phase_results: dict[str, tuple[list[QueryResult], float]]):
    print(f"\n{'=' * 80}")
    print(f"  CROSS-PHASE COMPARISON")
    print(f"{'=' * 80}")

    def fmt(v):
        return f"{v:,.0f} ms"

    print(f"\n  {'Phase':<20} {'Queries':>8} {'Hits':>6} {'Misses':>8} {'Hit%':>6} {'Avg Lat':>12} {'Wall':>12}")
    print(f"  {'-'*20} {'-'*8} {'-'*6} {'-'*8} {'-'*6} {'-'*12} {'-'*12}")

    for phase_name, (results, wall_ms) in phase_results.items():
        ok = [r for r in results if not r.error]
        hits = sum(1 for r in ok if r.cache_status == "hit")
        misses = sum(1 for r in ok if r.cache_status == "miss")
        lats = [r.latency_ms for r in ok]
        avg = statistics.mean(lats) if lats else 0
        hit_pct = f"{hits/len(ok)*100:.0f}%" if ok else "—"
        print(f"  {phase_name:<20} {len(results):>8} {hits:>6} {misses:>8} {hit_pct:>6} {fmt(avg):>12} {fmt(wall_ms):>12}")

    # Speedup comparison: warm vs cold (single-space data questions only)
    if "COLD" in phase_results and "WARM" in phase_results:
        cold_data = [r for r in phase_results["COLD"][0]
                     if r.category in ("cancer", "trials") and not r.error]
        warm_data = [r for r in phase_results["WARM"][0]
                     if r.category in ("cancer", "trials") and not r.error]
        if cold_data and warm_data:
            cold_avg = statistics.mean([r.latency_ms for r in cold_data])
            warm_avg = statistics.mean([r.latency_ms for r in warm_data])
            speedup = cold_avg / warm_avg if warm_avg > 0 else 0
            saved = sum(cold_avg - r.latency_ms for r in warm_data)
            print(f"\n  Cache speedup (cold→warm):  {speedup:.1f}x")
            print(f"  Avg cold latency:           {cold_avg:,.0f} ms")
            print(f"  Avg warm latency:           {warm_avg:,.0f} ms")
            print(f"  Total latency saved:        {saved:,.0f} ms ({saved/1000:.1f}s)")

    # Parameterized breakdown
    if "PARAMETERIZED" in phase_results:
        param = phase_results["PARAMETERIZED"][0]
        print(f"\n  Parameterized query results:")
        for r in param:
            status = r.cache_status if not r.error else "ERROR"
            sim = f"sim={r.similarity_score:.3f}" if r.similarity_score else ""
            print(f"    {status:>8}  {sim:>12}  {r.question[:60]}  ({r.note})")

    # Rephrased breakdown
    if "REPHRASED" in phase_results:
        reph = phase_results["REPHRASED"][0]
        print(f"\n  Rephrased query results:")
        for r in reph:
            status = r.cache_status if not r.error else "ERROR"
            sim = f"sim={r.similarity_score:.3f}" if r.similarity_score else ""
            print(f"    {status:>8}  {sim:>12}  {r.question[:60]}  ({r.note})")


# ═══════════════════════════════════════════════════════════════════════════════
# Test plan display
# ═══════════════════════════════════════════════════════════════════════════════

def print_test_plan(phases: list[Phase]):
    print(f"\n{'=' * 80}")
    print("  BENCHMARK TEST PLAN")
    print(f"{'=' * 80}")

    print(f"\n  Genie Spaces:")
    print(f"    Cancer Incidence: {CANCER_SPACE_ID}")
    print(f"    Clinical Trials:  {TRIALS_SPACE_ID}")

    if Phase.SMOKE in phases:
        print(f"\n  Phase 0: SMOKE — frontend & API validation")
        print(f"    • Health endpoint check")
        print(f"    • Genie spaces API (2 spaces, URLs populated)")
        print(f"    • Frontend HTML serving")
        print(f"    • SSE streaming (greeting round-trip)")
        print(f"    • Cache endpoint accessible")

    if Phase.COLD in phases:
        corpus = build_cold_corpus()
        print(f"\n  Phase 1: COLD — {len(corpus)} questions (cache empty, all miss)")
        for cat_name, qs in [
            ("Cancer Incidence", CANCER_QUESTIONS),
            ("Clinical Trials", TRIALS_QUESTIONS),
            ("Multi-space", MULTI_QUESTIONS),
            ("Assistant", ASSISTANT_QUESTIONS),
        ]:
            print(f"    {cat_name} ({len(qs)}):")
            for q in qs:
                print(f"      • {q}")

    if Phase.WARM in phases:
        corpus = build_warm_corpus()
        print(f"\n  Phase 2: WARM — {len(corpus)} questions (re-send single-space → expect hits)")
        for q in CANCER_QUESTIONS + TRIALS_QUESTIONS:
            print(f"      • {q}")

    if Phase.PARAMETERIZED in phases:
        corpus = build_parameterized_corpus()
        print(f"\n  Phase 3: PARAMETERIZED — {len(corpus)} entity-swapped variants")
        for v in PARAMETERIZED_VARIANTS:
            print(f"      • {v['question']}")
            print(f"        ↳ variant of: \"{v['base'][:60]}\" ({v['change']})")

    if Phase.REPHRASED in phases:
        corpus = build_rephrased_corpus()
        print(f"\n  Phase 4: REPHRASED — {len(corpus)} semantic rephrasings")
        for v in REPHRASED_VARIANTS:
            print(f"      • {v['question']}")
            print(f"        ↳ rephrase of: \"{v['base'][:60]}\" ({v['note']})")

    total = sum(
        len(build_cold_corpus()) if p == Phase.COLD else
        len(build_warm_corpus()) if p == Phase.WARM else
        len(build_parameterized_corpus()) if p == Phase.PARAMETERIZED else
        len(build_rephrased_corpus())
        for p in phases
    )
    print(f"\n  Total queries across all phases: {total}")
    print(f"{'=' * 80}")


# ═══════════════════════════════════════════════════════════════════════════════
# Smoke tests (frontend + API)
# ═══════════════════════════════════════════════════════════════════════════════

async def run_smoke_tests(url: str) -> tuple[int, int]:
    """Validate frontend rendering, API endpoints, and SSE streaming.

    Returns (passed, failed) counts.
    """
    print(f"\n{'─' * 70}")
    print(f"  Phase: SMOKE — Frontend & API smoke tests")
    print(f"{'─' * 70}")

    passed = 0
    failed = 0

    def check(name: str, ok: bool, detail: str = ""):
        nonlocal passed, failed
        icon = "✓" if ok else "✗"
        msg = f"  {icon} {name}"
        if detail:
            msg += f"  ({detail})"
        print(msg)
        if ok:
            passed += 1
        else:
            failed += 1

    async with aiohttp.ClientSession() as session:
        # 1) Health endpoint
        try:
            async with session.get(f"{url}/api/health", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()
                check("Health endpoint returns 200", resp.status == 200)
                check("Database available", data.get("db_available") is True)
        except Exception as e:
            check("Health endpoint reachable", False, str(e))
            check("Database available", False, "skipped")

        # 2) Genie spaces endpoint
        try:
            async with session.get(f"{url}/api/genie/spaces/active", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                spaces = await resp.json()
                check("Genie spaces endpoint returns 200", resp.status == 200)
                check("Returns a list", isinstance(spaces, list))
                check("Exactly 2 spaces configured", len(spaces) == 2,
                      f"got {len(spaces)}")

                if len(spaces) >= 2:
                    titles = [s.get("title", "") for s in spaces]
                    check("Cancer Incidence space present",
                          any("Cancer" in t for t in titles), str(titles))
                    check("Clinical Trials space present",
                          any("Clinical" in t for t in titles), str(titles))

                    for s in spaces:
                        url_val = s.get("genie_room_url")
                        check(f"genie_room_url set for '{s.get('title', '?')}'",
                              url_val is not None and url_val.startswith("http"),
                              url_val or "None")
        except Exception as e:
            check("Genie spaces endpoint reachable", False, str(e))

        # 3) Frontend serves HTML
        try:
            async with session.get(f"{url}/", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                html = await resp.text()
                check("Frontend serves HTML", resp.status == 200)
                check("HTML contains root div", 'id="root"' in html or '<div id="root"' in html)
                check("HTML references JS bundle", ".js" in html)
        except Exception as e:
            check("Frontend reachable", False, str(e))

        # 4) SSE streaming works (quick test with a greeting)
        try:
            async with session.post(
                f"{url}/api/ask/stream",
                json={"question": "hello", "session_id": str(uuid.uuid4()), "user_id": "smoke-test"},
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                check("SSE stream endpoint returns 200", resp.status == 200)
                content_type = resp.headers.get("content-type", "")
                check("SSE content-type is text/event-stream",
                      "text/event-stream" in content_type, content_type)

                events = []
                has_complete = False
                async for line in resp.content:
                    decoded = line.decode("utf-8", errors="replace").strip()
                    if decoded.startswith("event: "):
                        events.append(decoded.split("event: ", 1)[1])
                    if "complete" in decoded:
                        has_complete = True

                check("SSE stream emits events", len(events) > 0, f"{len(events)} events")
                check("SSE stream includes 'complete' event", has_complete)
                check("SSE stream includes 'intent' event", "intent" in events,
                      str(events[:5]))
        except Exception as e:
            check("SSE streaming works", False, str(e))

        # 5) Cache endpoints accessible
        try:
            async with session.get(f"{url}/api/cache/entries?limit=1", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()
                check("Cache entries endpoint returns 200", resp.status == 200)
                check("Cache response has 'entries' key", "entries" in data)
                check("Cache response has 'total' key", "total" in data)
        except Exception as e:
            check("Cache endpoint reachable", False, str(e))

    print(f"\n  Smoke tests: {passed} passed, {failed} failed")
    return passed, failed


# ═══════════════════════════════════════════════════════════════════════════════
# Main benchmark orchestrator
# ═══════════════════════════════════════════════════════════════════════════════

async def run_benchmark(url: str, phases: list[Phase], concurrency: int):
    async with aiohttp.ClientSession() as session:
        # Health check
        health = await api_call(session, url, "get", "/api/health")
        print(f"\nHealth: {health}")
        if not health.get("db_available"):
            print("ERROR: Database not available. Aborting.")
            return

    phase_results: dict[str, tuple[list[QueryResult], float]] = {}

    # ── Phase 0: SMOKE ──
    if Phase.SMOKE in phases:
        smoke_passed, smoke_failed = await run_smoke_tests(url)
        if smoke_failed > 0:
            print(f"\n  WARNING: {smoke_failed} smoke test(s) failed. Pipeline tests may be unreliable.")

    # ── Phase 1: COLD ──
    if Phase.COLD in phases:
        async with aiohttp.ClientSession() as session:
            print("\n[Setup] Clearing cache for COLD phase...")
            try:
                await api_call(session, url, "delete", "/api/cache/entries")
                print("  Cache cleared")
            except Exception as e:
                print(f"  Cache clear failed: {e}")
            await asyncio.sleep(1)

        results, wall = await run_phase(url, build_cold_corpus(), Phase.COLD, concurrency)
        print_phase_report("COLD", results, wall)
        phase_results["COLD"] = (results, wall)

        # Send thumbs-up feedback for successful data queries so they get promoted to cache
        data_results = [r for r in results
                        if not r.error and r.trace_id and r.category in ("cancer", "trials", "multi")]
        if data_results:
            print(f"\n[Promotion] Sending thumbs-up feedback for {len(data_results)} successful data queries...")
            async with aiohttp.ClientSession() as session:
                for r in data_results:
                    try:
                        await api_call(session, url, "post", "/api/feedback",
                                       json_body={"trace_id": r.trace_id, "rating": 1, "user_id": "bench-user"})
                    except Exception as e:
                        print(f"  Feedback failed for {r.trace_id}: {e}")
            print(f"  Feedback sent. Waiting 60s for MLflow trace tags to propagate...")
            await asyncio.sleep(60)

            print(f"[Promotion] Running cache promotion pipeline...")
            async with aiohttp.ClientSession() as session:
                try:
                    promo = await api_call(session, url, "post", "/api/pipelines/cache",
                                           json_body=None, retries=1)
                    print(f"  Promotion result: {json.dumps(promo, indent=2, default=str)[:500]}")
                except Exception as e:
                    print(f"  Promotion failed: {e}")

            # Verify cache now has entries
            async with aiohttp.ClientSession() as session:
                cache_info = await api_call(session, url, "get", "/api/cache/entries")
                n = cache_info.get("total", 0)
                print(f"  Cache now has {n} entries")

            print(f"  Waiting 3s for state to settle...")
            await asyncio.sleep(3)
        else:
            print("\n  No successful data queries to promote. Skipping cache promotion.")
            await asyncio.sleep(3)

    # ── Phase 2: WARM ──
    if Phase.WARM in phases:
        results, wall = await run_phase(url, build_warm_corpus(), Phase.WARM, concurrency)
        print_phase_report("WARM", results, wall)
        phase_results["WARM"] = (results, wall)

    # ── Phase 3: PARAMETERIZED ──
    if Phase.PARAMETERIZED in phases:
        results, wall = await run_phase(
            url, build_parameterized_corpus(), Phase.PARAMETERIZED, concurrency,
        )
        print_phase_report("PARAMETERIZED", results, wall)
        phase_results["PARAMETERIZED"] = (results, wall)

    # ── Phase 4: REPHRASED ──
    if Phase.REPHRASED in phases:
        results, wall = await run_phase(
            url, build_rephrased_corpus(), Phase.REPHRASED, concurrency,
        )
        print_phase_report("REPHRASED", results, wall)
        phase_results["REPHRASED"] = (results, wall)

    # ── Final comparison ──
    if len(phase_results) > 1:
        print_final_report(phase_results)

    print(f"\nBenchmark complete.")


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

PHASE_MAP = {
    "SMOKE": Phase.SMOKE,
    "COLD": Phase.COLD,
    "WARM": Phase.WARM,
    "PARAMETERIZED": Phase.PARAMETERIZED,
    "REPHRASED": Phase.REPHRASED,
}
ALL_PHASES = [Phase.SMOKE, Phase.COLD, Phase.WARM, Phase.PARAMETERIZED, Phase.REPHRASED]


def parse_phases(value: str) -> list[Phase]:
    if value.upper() == "ALL":
        return ALL_PHASES
    names = [v.strip().upper() for v in value.split(",")]
    phases = []
    for n in names:
        if n not in PHASE_MAP:
            raise argparse.ArgumentTypeError(
                f"Unknown phase '{n}'. Choose from: {', '.join(PHASE_MAP)} or ALL"
            )
        phases.append(PHASE_MAP[n])
    return phases


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Genie Agent Benchmark Suite")
    parser.add_argument("--url", default="http://localhost:8000", help="App base URL")
    parser.add_argument("--concurrency", type=int, default=5, help="Max concurrent requests per phase")
    parser.add_argument("--plan-only", action="store_true", help="Show test plan without executing")
    parser.add_argument(
        "--phase", default="ALL",
        help="Phase(s) to run: COLD, WARM, PARAMETERIZED, REPHRASED, ALL, or comma-separated",
    )
    args = parser.parse_args()

    phases = parse_phases(args.phase)

    print("Genie Agent Benchmark Suite")
    print(f"URL:         {args.url}")
    print(f"Concurrency: {args.concurrency}")
    print(f"Phases:      {', '.join(p.value for p in phases)}")

    print_test_plan(phases)

    if args.plan_only:
        print("\n[--plan-only] Exiting without running. Remove flag to execute.")
    else:
        asyncio.run(run_benchmark(args.url, phases, args.concurrency))

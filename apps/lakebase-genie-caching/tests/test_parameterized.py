"""Parameterized query test: measures cache effectiveness when only entities change.

Seeds the cache with base queries, then tests variations that change only the
parameter (e.g., cancer type, state, gender) while keeping the question structure
identical. The current system relies purely on embedding similarity -- this test
quantifies how well (or poorly) that handles entity substitution.
"""

import argparse
import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field

import aiohttp

# ═══════════════════════════════════════════════════════════════════════════
# Test cases: each has a base cached query and parameterized variants
# ═══════════════════════════════════════════════════════════════════════════

PARAM_TEST_CASES = [
    {
        "name": "Cancer site filter",
        "description": "Same incidence rate query, different cancer site",
        "base": {
            "question": "What is the incidence rate for breast cancer over the years?",
            "sql": "SELECT Year, Number_of_New_Cases_Per_One_Hundred_Thousand_Population FROM john_snow_labs_cancer_statistics.cancer_statistics.us_cancer_incidence_rates WHERE Cancer_Site = 'Female Breast' AND Gender = 'Female' ORDER BY Year",
        },
        "variants": [
            {"question": "What is the incidence rate for lung cancer over the years?", "param_changed": "breast → lung"},
            {"question": "What is the incidence rate for colon cancer over the years?", "param_changed": "breast → colon"},
            {"question": "What is the incidence rate for prostate cancer over the years?", "param_changed": "breast → prostate"},
        ],
    },
    {
        "name": "Gender filter",
        "description": "Same brain cancer query, different gender filter",
        "base": {
            "question": "What are the brain cancer mortality rates by gender?",
            "sql": "SELECT Gender, Age_Adjusted_Mortality_Rate, Count_of_People_Diagnosed_With_Cancer FROM john_snow_labs_cancer_statistics.cancer_statistics.brain_cancer_by_tumor_site WHERE Gender != 'Both sexes' AND Age_Group = 'All ages'",
        },
        "variants": [
            {"question": "What are the brain cancer mortality rates for males?", "param_changed": "by gender → for males"},
            {"question": "What are the brain cancer mortality rates for females?", "param_changed": "by gender → for females"},
        ],
    },
    {
        "name": "Race filter",
        "description": "Same incidence query, different race/ethnicity",
        "base": {
            "question": "Show cancer incidence rates by race",
            "sql": "SELECT Race_and_Hispanic_Origin, Year, Number_of_New_Cases_Per_One_Hundred_Thousand_Population FROM john_snow_labs_cancer_statistics.cancer_statistics.us_cancer_incidence_rates WHERE Cancer_Site = 'All cancer sites combined' AND Gender = 'Both sexes' ORDER BY Year DESC LIMIT 20",
        },
        "variants": [
            {"question": "Show cancer incidence rates for Hispanic populations", "param_changed": "by race → Hispanic"},
            {"question": "Show cancer incidence rates for white populations", "param_changed": "by race → white"},
        ],
    },
    {
        "name": "Survival metric",
        "description": "Same cancer, different survival time window",
        "base": {
            "question": "What is the 5-year survival rate for colon cancer?",
            "sql": "SELECT Cancer_Type, Gender, Five_Year_Survival_Percentage FROM john_snow_labs_cancer_statistics.cancer_statistics.adult_cancer_survival_in_england_2013_to_2017 WHERE Cancer_Type ILIKE '%colon%'",
        },
        "variants": [
            {"question": "What is the 10-year survival rate for colon cancer?", "param_changed": "5-year → 10-year"},
            {"question": "What is the 1-year survival rate for colon cancer?", "param_changed": "5-year → 1-year"},
        ],
    },
    {
        "name": "Cancer type in area",
        "description": "Same area breakdown, different cancer organ site",
        "base": {
            "question": "Show breast cancer mortality rates by census division",
            "sql": "SELECT Census_Division_Name, Age_Adjusted_Mortality_Rate, Count_of_People_Diagnosed_With_Cancer FROM john_snow_labs_cancer_statistics.cancer_statistics.cancer_types_grouped_by_area WHERE Cancer_Organ_Site = 'Female Breast' AND Gender = 'Female' AND Cancer_Event_Type = 'Mortality'",
        },
        "variants": [
            {"question": "Show lung cancer mortality rates by census division", "param_changed": "breast → lung"},
            {"question": "Show colon cancer mortality rates by census division", "param_changed": "breast → colon"},
            {"question": "Show prostate cancer mortality rates by census division", "param_changed": "breast → prostate"},
        ],
    },
]


@dataclass
class ParamTestResult:
    case_name: str
    variant_question: str
    param_changed: str
    cache_status: str = "error"
    similarity: float | None = None
    latency_ms: float = 0.0
    error: str | None = None


async def seed_cache(session: aiohttp.ClientSession, base_url: str, cases: list[dict]) -> bool:
    url = f"{base_url}/api/cache/faq/bulk"
    entries = []
    # First configured Genie space; set GENIE_SPACE_IDS (see tests/env_config.py).
    from tests.env_config import require_genie_space_ids

    space_id = require_genie_space_ids(minimum=1)[0]
    for case in cases:
        entries.append({
            "question": case["base"]["question"],
            "sql": case["base"]["sql"],
            "genie_space_id": space_id,
        })

    for attempt in range(3):
        try:
            async with session.post(url, json=entries) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print(f"  Seeded {data.get('added', len(entries))} base queries")
                    return True
                text = await resp.text()
                print(f"  Attempt {attempt+1} failed ({resp.status}): {text[:200]}")
        except Exception as e:
            print(f"  Attempt {attempt+1} error: {e}")
        await asyncio.sleep(3)
    return False


async def clear_cache(session: aiohttp.ClientSession, base_url: str) -> bool:
    for attempt in range(3):
        try:
            async with session.delete(f"{base_url}/api/cache/entries") as resp:
                if resp.status == 200:
                    return True
        except Exception as e:
            print(f"  Clear attempt {attempt+1} error: {e}")
        await asyncio.sleep(2)
    return False


async def test_variant(
    session: aiohttp.ClientSession,
    base_url: str,
    case_name: str,
    variant: dict,
    semaphore: asyncio.Semaphore,
) -> ParamTestResult:
    result = ParamTestResult(
        case_name=case_name,
        variant_question=variant["question"],
        param_changed=variant["param_changed"],
    )

    async with semaphore:
        session_id = str(uuid.uuid4())
        payload = {
            "question": variant["question"],
            "session_id": session_id,
        }
        timeout = aiohttp.ClientTimeout(total=180)
        start = time.time()
        try:
            async with session.post(
                f"{base_url}/api/ask", json=payload, timeout=timeout
            ) as resp:
                wall = (time.time() - start) * 1000
                data = await resp.json()
                result.cache_status = data.get("cache_status", "unknown")
                result.similarity = data.get("similarity_score")
                result.latency_ms = data.get("latency_ms", wall)
        except Exception as e:
            result.error = str(e)
            result.latency_ms = (time.time() - start) * 1000

    return result


async def run_test(base_url: str, concurrency: int) -> list[ParamTestResult]:
    timeout = aiohttp.ClientTimeout(total=300)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        # Health check
        async with session.get(f"{base_url}/api/health") as resp:
            health = await resp.json()
            print(f"Server: {health}")

        # Clear + seed
        print("\n[Setup] Clearing cache...")
        await clear_cache(session, base_url)
        print("  Done")

        print("[Setup] Seeding base queries...")
        ok = await seed_cache(session, base_url, PARAM_TEST_CASES)
        if not ok:
            print("  FAILED to seed cache!")
            return []
        await asyncio.sleep(3)

        # Build variant list
        variants = []
        for case in PARAM_TEST_CASES:
            for v in case["variants"]:
                variants.append((case["name"], v))

        total = len(variants)
        print(f"\n[Test] Sending {total} parameterized variants (concurrency={concurrency})...")

        semaphore = asyncio.Semaphore(concurrency)
        tasks = [
            test_variant(session, base_url, name, v, semaphore)
            for name, v in variants
        ]
        results = await asyncio.gather(*tasks)

        # Cleanup
        await clear_cache(session, base_url)
        return list(results)


def print_results(results: list[ParamTestResult]) -> None:
    print(f"\n{'='*90}")
    print("  PARAMETERIZED QUERY TEST RESULTS")
    print(f"{'='*90}\n")

    hits = [r for r in results if r.cache_status == "hit"]
    misses = [r for r in results if r.cache_status in ("miss", "rejected")]
    errors = [r for r in results if r.error]

    print(f"  Total variants tested: {len(results)}")
    print(f"  Cache hits:  {len(hits)}  ({len(hits)/len(results)*100:.0f}%)")
    print(f"  Cache misses: {len(misses)}  ({len(misses)/len(results)*100:.0f}%)")
    if errors:
        print(f"  Errors: {len(errors)}")

    # Group by test case
    cases = {}
    for r in results:
        cases.setdefault(r.case_name, []).append(r)

    print(f"\n  {'Case':<22} {'Variant':<55} {'Status':>7} {'Sim':>6} {'Latency':>10}")
    print(f"  {'-'*22} {'-'*55} {'-'*7} {'-'*6} {'-'*10}")

    for case_name, case_results in cases.items():
        for r in case_results:
            status = "HIT" if r.cache_status == "hit" else ("ERR" if r.error else "MISS")
            sim = f"{r.similarity:.3f}" if r.similarity else "—"
            lat = f"{r.latency_ms:,.0f}ms"
            q = r.variant_question[:55]
            print(f"  {case_name:<22} {q:<55} {status:>7} {sim:>6} {lat:>10}")
        case_name = ""  # blank for subsequent rows

    if hits:
        avg_hit = sum(r.latency_ms for r in hits) / len(hits)
        print(f"\n  Avg HIT latency:  {avg_hit:,.0f} ms")
    if misses:
        avg_miss = sum(r.latency_ms for r in misses) / len(misses)
        print(f"  Avg MISS latency: {avg_miss:,.0f} ms")

    # Summary verdict
    hit_rate = len(hits) / len(results) * 100
    print(f"\n  VERDICT: {hit_rate:.0f}% of parameterized variants hit the cache.")
    if hit_rate < 30:
        print("  The current embedding-only approach is POOR at handling entity swaps.")
        print("  Recommendation: implement template extraction + parameter substitution.")
    elif hit_rate < 70:
        print("  Mixed results — some entities are close enough in embedding space, others aren't.")
    else:
        print("  Good — embedding similarity captures most parameterized variants.")


def print_test_plan() -> None:
    print(f"\n{'='*80}")
    print("  PARAMETERIZED QUERY TEST PLAN")
    print(f"{'='*80}\n")
    print("  This test seeds the cache with base queries, then asks variants that")
    print("  change ONLY the entity/parameter while keeping question structure the same.\n")

    total = 0
    for case in PARAM_TEST_CASES:
        print(f"  [{case['name']}] {case['description']}")
        print(f"    Base (cached): \"{case['base']['question']}\"")
        for v in case["variants"]:
            print(f"    → Variant ({v['param_changed']}): \"{v['question']}\"")
            total += 1
        print()

    print(f"  Total: {len(PARAM_TEST_CASES)} base queries, {total} variants to test")
    print(f"  Similarity threshold: 0.95 (current config)")
    print(f"  Expected: most variants will MISS because entity changes drop similarity.\n")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()

    print("Parameterized Query Cache Test")
    print(f"URL:         {args.url}")
    print(f"Concurrency: {args.concurrency}")

    print_test_plan()

    if args.plan_only:
        return

    results = await run_test(args.url, args.concurrency)
    if results:
        print_results(results)


if __name__ == "__main__":
    asyncio.run(main())

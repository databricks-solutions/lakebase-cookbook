#!/usr/bin/env python3
"""E2E Round 2: Edge cases, error handling, non-chat API endpoints."""
import json
import sys
import time
import subprocess
import uuid
import httpx

# Workspace-specific values come from the environment -- see tests/env_config.py.
#   export GENIE_CACHE_APP_URL="https://<app>.<region>.databricksapps.com"
#   export DATABRICKS_CONFIG_PROFILE="<your-cli-profile>"
from tests.env_config import require_app_url, require_profile

APP_URL = require_app_url()
PROFILE = require_profile()
TIMEOUT = 120


def get_token():
    result = subprocess.run(
        ["databricks", "auth", "token", "--profile", PROFILE],
        capture_output=True, text=True,
    )
    return json.loads(result.stdout)["access_token"]


def stream_ask(client: httpx.Client, question: str, session_id: str | None = None):
    body = {"question": question, "session_id": session_id}
    events = []
    complete_data = {}
    with client.stream("POST", f"{APP_URL}/api/ask/stream", json=body, timeout=TIMEOUT) as resp:
        resp.raise_for_status()
        current_event = ""
        for line in resp.iter_lines():
            if line.startswith("event: "):
                current_event = line[7:].strip()
            elif line.startswith("data: ") and current_event:
                try:
                    data = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue
                events.append({"event": current_event, "data": data})
                if current_event == "complete":
                    complete_data = data
                current_event = ""
    return {
        "events": events,
        "complete": complete_data,
        "description": complete_data.get("description") or "",
        "event_types": [e["event"] for e in events],
        "thinking": [e for e in events if e["event"] == "thinking"],
        "cache_status": complete_data.get("cache_status"),
        "trace_id": complete_data.get("trace_id"),
        "sql": complete_data.get("sql"),
        "row_count": complete_data.get("row_count"),
        "sub_results": complete_data.get("sub_results"),
    }


def run_test(name, fn):
    print(f"\n{'='*70}")
    print(f"  TEST: {name}")
    print(f"{'='*70}")
    t0 = time.time()
    try:
        result = fn()
        elapsed = time.time() - t0
        print(f"  PASS ({elapsed:.1f}s)")
        return {"name": name, "status": "PASS", "elapsed": elapsed, "result": result}
    except Exception as e:
        elapsed = time.time() - t0
        print(f"  FAIL ({elapsed:.1f}s): {e}")
        return {"name": name, "status": "FAIL", "elapsed": elapsed, "error": str(e)}


def main():
    token = get_token()
    client = httpx.Client(headers={"Authorization": f"Bearer {token}"})
    session_id = str(uuid.uuid4())
    all_results = []

    print(f"\n{'#'*70}")
    print(f"  E2E TEST ROUND 2 — EDGE CASES")
    print(f"  Session: {session_id}")
    print(f"{'#'*70}")

    # ── Test 1: API endpoints (non-chat) ──
    def test_api_endpoints():
        endpoints = [
            ("GET", "/api/health"),
            ("GET", "/api/config"),
            ("GET", "/api/tuning"),
            ("GET", "/api/whoami"),
            ("GET", "/api/genie/spaces/active"),
        ]
        for method, path in endpoints:
            r = client.request(method, f"{APP_URL}{path}")
            assert r.status_code == 200, f"{path} returned {r.status_code}: {r.text[:200]}"
            print(f"    {path}: OK ({r.status_code})")
        return {"endpoints_tested": len(endpoints)}
    all_results.append(run_test("API Endpoints Health", test_api_endpoints))

    # ── Test 2: Empty/short input ──
    def test_short_input():
        res = stream_ask(client, "hi", session_id)
        assert "complete" in set(res["event_types"]), "No complete event"
        assert len(res["description"]) > 10, f"Too short: {res['description']}"
        print(f"    Response: {res['description'][:150]}...")
        return {"desc_len": len(res["description"])}
    all_results.append(run_test("Short Input ('hi')", test_short_input))

    # ── Test 3: Ambiguous/vague query ──
    def test_vague_query():
        res = stream_ask(client, "Tell me about cancer data", session_id)
        assert "complete" in set(res["event_types"]), "No complete event"
        assert len(res["description"]) > 20, f"Too short: {res['description']}"
        thinking = res["thinking"]
        intent_nodes = [t["data"].get("label", "") for t in thinking]
        print(f"    Thinking: {intent_nodes}")
        print(f"    Response: {res['description'][:200]}...")
        return {"desc_len": len(res["description"]), "cache_status": res["cache_status"]}
    all_results.append(run_test("Vague Query", test_vague_query))

    # ── Test 4: Cross-space query (if multiple spaces) ──
    def test_specific_query():
        res = stream_ask(client, "What is the cancer incidence rate for melanoma in males?", session_id)
        assert "complete" in set(res["event_types"]), "No complete event"
        assert len(res["description"]) > 20, f"Too short"
        thinking = res["thinking"]
        print(f"    Thinking: {[t['data'].get('label','') for t in thinking]}")
        print(f"    Response: {res['description'][:250]}...")
        print(f"    Cache: {res['cache_status']}, SQL: {bool(res['sql'])}")
        return {"desc_len": len(res["description"]), "cache_status": res["cache_status"]}
    all_results.append(run_test("Specific Data Query (melanoma)", test_specific_query))

    # ── Test 5: Session persistence (new session, 2 messages) ──
    def test_session_persistence():
        new_session = str(uuid.uuid4())
        res1 = stream_ask(client, "How many cancer types are tracked in the dataset?", new_session)
        assert "complete" in set(res1["event_types"]), "No complete event for Q1"
        print(f"    Q1 response: {res1['description'][:150]}...")
        sid = res1["complete"].get("session_id") or new_session

        res2 = stream_ask(client, "Which one has the highest mortality?", sid)
        assert "complete" in set(res2["event_types"]), "No complete event for Q2"
        print(f"    Q2 response: {res2['description'][:150]}...")
        rewrite = [t for t in res2["thinking"] if t["data"].get("node") == "rewrite"]
        print(f"    Rewrite triggered: {len(rewrite) > 0}")
        return {
            "q1_len": len(res1["description"]),
            "q2_len": len(res2["description"]),
            "rewrite_triggered": len(rewrite) > 0,
        }
    all_results.append(run_test("Session Persistence + Follow-up", test_session_persistence))

    # ── Test 6: Cache entries endpoint ──
    def test_cache_entries():
        r = client.get(f"{APP_URL}/api/cache/entries?limit=5")
        assert r.status_code == 200, f"Cache entries failed: {r.status_code}"
        data = r.json()
        entries = data.get("entries", [])
        total = data.get("total", 0)
        print(f"    Cache entries: {len(entries)} (total: {total})")
        for e in entries[:3]:
            print(f"      - {e.get('query_text', '')[:60]}... (hits: {e.get('hit_count', 0)})")
        return {"count": len(entries), "total": total}
    all_results.append(run_test("Cache Entries API", test_cache_entries))

    # ── Test 7: Sessions list ──
    def test_sessions():
        r = client.get(f"{APP_URL}/api/whoami")
        uid = r.json().get("user_id", "unknown")
        r2 = client.get(f"{APP_URL}/api/memory/sessions/{uid}?limit=5")
        assert r2.status_code == 200, f"Sessions failed: {r2.status_code}"
        data = r2.json()
        sessions = data.get("sessions", [])
        print(f"    Sessions for {uid}: {len(sessions)}")
        for s in sessions[:3]:
            print(f"      - {s.get('title', 'untitled')}: {s.get('session_id', '')[:12]}...")
        return {"count": len(sessions)}
    all_results.append(run_test("Sessions API", test_sessions))

    # ── Test 8: Feedback submission ──
    def test_feedback():
        r = client.post(
            f"{APP_URL}/api/feedback",
            json={"trace_id": "test-trace-e2e", "rating": 1, "user_id": "e2e-test"},
        )
        assert r.status_code == 200, f"Feedback failed: {r.status_code}: {r.text}"
        print(f"    Feedback response: {r.json()}")
        return r.json()
    all_results.append(run_test("Feedback Submission", test_feedback))

    # ── Summary ──
    print(f"\n\n{'='*70}")
    print(f"  ROUND 2 SUMMARY")
    print(f"{'='*70}")
    passed = sum(1 for r in all_results if r["status"] == "PASS")
    failed = sum(1 for r in all_results if r["status"] == "FAIL")
    for r in all_results:
        icon = "PASS" if r["status"] == "PASS" else "FAIL"
        print(f"  [{icon}] {r['name']} ({r['elapsed']:.1f}s)")
        if r["status"] == "FAIL":
            print(f"         Error: {r.get('error', 'unknown')}")
    print(f"\n  Total: {passed} passed, {failed} failed out of {len(all_results)}")
    print(f"{'='*70}\n")

    client.close()
    return 1 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())

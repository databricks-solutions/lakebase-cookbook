#!/usr/bin/env python3
"""End-to-end API tests for the Genie Caching demo app."""
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
    """Send a question via SSE and collect all events + final AskResponse."""
    body = {"question": question, "session_id": session_id}
    events = []
    complete_data = {}

    with client.stream(
        "POST", f"{APP_URL}/api/ask/stream",
        json=body, timeout=TIMEOUT,
    ) as resp:
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

    description = complete_data.get("description") or ""
    session_title = complete_data.get("session_title")
    return {
        "events": events,
        "complete": complete_data,
        "description": description,
        "event_types": [e["event"] for e in events],
        "thinking": [e for e in events if e["event"] == "thinking"],
        "cache_status": complete_data.get("cache_status"),
        "session_id": complete_data.get("session_id"),
        "session_title": session_title,
        "trace_id": complete_data.get("trace_id"),
        "sql": complete_data.get("sql"),
        "row_count": complete_data.get("row_count"),
        "sub_results": complete_data.get("sub_results"),
    }


def run_test(name: str, fn):
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
    round_num = int(sys.argv[1]) if len(sys.argv) > 1 else 1

    print(f"\n{'#'*70}")
    print(f"  E2E TEST ROUND {round_num}")
    print(f"  Session: {session_id}")
    print(f"{'#'*70}")

    # ── Test 1: Health Check ──
    def test_health():
        r = client.get(f"{APP_URL}/api/health")
        r.raise_for_status()
        d = r.json()
        assert d["status"] == "ok", f"Health check not ok: {d}"
        assert d["db_available"] is True, "DB not available"
        print(f"    Health: {d}")
        return d
    all_results.append(run_test("Health Check", test_health))

    # ── Test 2: Greeting (Fast Path → assistant) ──
    def test_greeting():
        res = stream_ask(client, "Hello! What can you help me with?", session_id)
        et = set(res["event_types"])
        thinking = res["thinking"]
        print(f"    Thinking steps: {[t['data'].get('label','') for t in thinking]}")
        print(f"    Description: {res['description'][:200]}...")
        print(f"    Event types: {et}")

        assert "complete" in et, f"No complete event. Events: {et}"
        assert len(res["description"]) > 20, f"Description too short: {res['description']}"

        thinking_nodes = [t["data"].get("node") for t in thinking]
        print(f"    Thinking nodes: {thinking_nodes}")
        return {"desc_len": len(res["description"]), "thinking_nodes": thinking_nodes}
    all_results.append(run_test("Greeting → Fast Path → Assistant", test_greeting))

    # ── Test 3: Data Query (first data question) ──
    def test_data_query():
        res = stream_ask(client, "What are the top 5 most common cancer types by incidence?", session_id)
        et = set(res["event_types"])
        thinking = res["thinking"]
        print(f"    Thinking steps: {[t['data'].get('label','') for t in thinking]}")
        print(f"    Description: {res['description'][:250]}...")
        print(f"    Event types: {et}")
        print(f"    Cache status: {res['cache_status']}")
        print(f"    SQL: {(res['sql'] or '')[:100]}...")
        print(f"    Row count: {res['row_count']}")
        print(f"    Trace ID: {res['trace_id']}")

        assert "complete" in et, f"No complete event. Events: {et}"
        assert len(res["description"]) > 30, f"Description too short: {res['description']}"
        return {
            "desc_len": len(res["description"]),
            "cache_status": res["cache_status"],
            "has_sql": bool(res["sql"]),
            "row_count": res["row_count"],
        }
    all_results.append(run_test("Data Query → Full Pipeline", test_data_query))

    # ── Test 4: Exact repeat (already-answered or cache hit) ──
    def test_repeat():
        res = stream_ask(client, "What are the top 5 most common cancer types by incidence?", session_id)
        et = set(res["event_types"])
        thinking = res["thinking"]
        print(f"    Thinking steps: {[t['data'].get('label','') for t in thinking]}")
        print(f"    Description: {res['description'][:200]}...")
        print(f"    Cache status: {res['cache_status']}")

        assert "complete" in et, f"No complete event"
        assert len(res["description"]) > 20, f"Description too short"

        thinking_labels = [t["data"].get("label", "").lower() for t in thinking]
        already_answered = any("already" in l for l in thinking_labels)
        print(f"    Already-answered detected: {already_answered}")
        return {
            "desc_len": len(res["description"]),
            "cache_status": res["cache_status"],
            "already_answered": already_answered,
        }
    all_results.append(run_test("Repeated Query → Already Answered / Cache Hit", test_repeat))

    # ── Test 5: LEAST vs MOST (should NOT match as already-answered) ──
    def test_least_vs_most():
        res = stream_ask(client, "What are the top 5 LEAST common cancer types?", session_id)
        et = set(res["event_types"])
        thinking = res["thinking"]
        print(f"    Thinking steps: {[t['data'].get('label','') for t in thinking]}")
        print(f"    Description: {res['description'][:250]}...")
        print(f"    Cache status: {res['cache_status']}")

        assert "complete" in et, f"No complete event"
        assert len(res["description"]) > 20, f"Description too short"

        already_labels = [
            t["data"] for t in thinking
            if "already" in t["data"].get("label", "").lower()
        ]
        if already_labels:
            detail = already_labels[0].get("detail", "")
            is_match = "match" in detail.lower() and "no match" not in detail.lower() and "none" not in detail.lower()
            if is_match:
                raise AssertionError(
                    f"BUG: LEAST was matched as already-answered to MOST! Detail: {detail}"
                )
            print(f"    Already-answered checked but correctly found no match")
        else:
            print(f"    Already-answered not triggered (OK)")
        return {
            "desc_len": len(res["description"]),
            "cache_status": res["cache_status"],
        }
    all_results.append(run_test("LEAST vs MOST Discrimination", test_least_vs_most))

    # ── Test 6: Multi-turn follow-up ──
    def test_follow_up():
        res = stream_ask(client, "Can you break that down by year?", session_id)
        et = set(res["event_types"])
        thinking = res["thinking"]
        print(f"    Thinking steps: {[t['data'].get('label','') for t in thinking]}")
        print(f"    Description: {res['description'][:250]}...")
        print(f"    Cache status: {res['cache_status']}")

        assert "complete" in et, f"No complete event"
        assert len(res["description"]) > 20, f"Description too short"

        rewrite_steps = [t for t in thinking if t["data"].get("node") == "rewrite"]
        print(f"    Rewrite steps: {len(rewrite_steps)}")
        return {
            "desc_len": len(res["description"]),
            "cache_status": res["cache_status"],
            "had_rewrite": len(rewrite_steps) > 0,
        }
    all_results.append(run_test("Multi-turn Follow-up", test_follow_up))

    # ── Summary ──
    print(f"\n\n{'='*70}")
    print(f"  ROUND {round_num} SUMMARY")
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

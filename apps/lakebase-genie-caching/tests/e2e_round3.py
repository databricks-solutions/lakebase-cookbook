#!/usr/bin/env python3
"""E2E Round 3: Regression test — full fresh workflow + stress tests."""
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
    error_events = []
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
                elif current_event == "error":
                    error_events.append(data)
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
        "errors": error_events,
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
    all_results = []

    print(f"\n{'#'*70}")
    print(f"  E2E TEST ROUND 3 — REGRESSION")
    print(f"{'#'*70}")

    # ── Test 1: Full conversation flow (fresh session) ──
    def test_full_flow():
        sid = str(uuid.uuid4())
        questions = [
            ("What cancer types have the highest incidence rate for females?", "data"),
            ("And for males?", "follow-up"),
            ("Which one shows the biggest gender gap?", "follow-up"),
        ]
        results = []
        for q, qtype in questions:
            print(f"\n    [{qtype}] Q: {q}")
            res = stream_ask(client, q, sid)
            assert "complete" in set(res["event_types"]), f"No complete for: {q}"
            assert len(res["description"]) > 20, f"Short response for: {q}"
            assert not res["errors"], f"Errors for {q}: {res['errors']}"
            print(f"    A: {res['description'][:150]}...")
            print(f"    Cache: {res['cache_status']}, Thinking: {[t['data'].get('label','') for t in res['thinking']]}")
            results.append({"q": q, "type": qtype, "desc_len": len(res["description"]), "cache": res["cache_status"]})
            sid = res["complete"].get("session_id") or sid
        return results
    all_results.append(run_test("Full Conversation Flow (3 turns)", test_full_flow))

    # ── Test 2: Parallel sessions (independent) ──
    def test_parallel_sessions():
        sid1 = str(uuid.uuid4())
        sid2 = str(uuid.uuid4())
        res1 = stream_ask(client, "What is the average cancer incidence rate across all types?", sid1)
        res2 = stream_ask(client, "How many total cancer cases are in the dataset?", sid2)
        assert len(res1["description"]) > 20, "Session 1 short"
        assert len(res2["description"]) > 20, "Session 2 short"
        assert not res1["errors"], f"Session 1 errors: {res1['errors']}"
        assert not res2["errors"], f"Session 2 errors: {res2['errors']}"
        print(f"    S1: {res1['description'][:120]}...")
        print(f"    S2: {res2['description'][:120]}...")
        return {"s1_ok": True, "s2_ok": True}
    all_results.append(run_test("Independent Sessions", test_parallel_sessions))

    # ── Test 3: No errors in SSE stream ──
    def test_no_sse_errors():
        sid = str(uuid.uuid4())
        queries = [
            "Hello",
            "Show me cancer data for lung cancer",
            "What about breast cancer?",
        ]
        total_errors = []
        for q in queries:
            res = stream_ask(client, q, sid)
            if res["errors"]:
                total_errors.extend([(q, e) for e in res["errors"]])
            sid = res["complete"].get("session_id") or sid
        assert not total_errors, f"SSE errors found: {total_errors}"
        print(f"    All {len(queries)} queries completed without SSE errors")
        return {"queries_clean": len(queries)}
    all_results.append(run_test("No SSE Errors in 3-query Flow", test_no_sse_errors))

    # ── Test 4: Thinking panel completeness ──
    def test_thinking_panel():
        sid = str(uuid.uuid4())
        res = stream_ask(client, "What are the cancer incidence rates for colon cancer by gender?", sid)
        thinking = res["thinking"]
        nodes = [t["data"].get("node", "") for t in thinking]
        labels = [t["data"].get("label", "") for t in thinking]
        print(f"    Nodes: {nodes}")
        print(f"    Labels: {labels}")

        assert len(thinking) >= 2, f"Expected >=2 thinking steps, got {len(thinking)}"
        assert "fast_path" in nodes, f"Missing fast_path in thinking nodes: {nodes}"

        for t in thinking:
            assert t["data"].get("node"), f"Thinking step missing 'node': {t}"
            assert t["data"].get("label"), f"Thinking step missing 'label': {t}"
        print(f"    All {len(thinking)} thinking steps have node + label")
        return {"thinking_count": len(thinking), "nodes": nodes}
    all_results.append(run_test("Thinking Panel Completeness", test_thinking_panel))

    # ── Test 5: Session title generation ──
    def test_session_title():
        sid = str(uuid.uuid4())
        res = stream_ask(client, "Compare prostate and breast cancer rates", sid)
        actual_sid = res["complete"].get("session_id") or sid
        title = res["complete"].get("session_title")
        print(f"    Session: {actual_sid}")
        print(f"    Title: {title}")
        print(f"    Response: {res['description'][:150]}...")
        return {"session_id": actual_sid, "title": title}
    all_results.append(run_test("Session Title Generation", test_session_title))

    # ── Test 6: Tuning config GET ──
    def test_tuning_config():
        r = client.get(f"{APP_URL}/api/tuning")
        r.raise_for_status()
        cfg = r.json()
        assert "cache" in cfg, "Missing 'cache' in tuning"
        assert "memory" in cfg, "Missing 'memory' in tuning"
        assert "llm" in cfg, "Missing 'llm' in tuning"
        print(f"    Cache threshold: {cfg['cache']['similarity_threshold']}")
        print(f"    Morph threshold: {cfg['cache']['answer_morph_threshold']}")
        print(f"    Memory threshold: {cfg['memory']['similarity_threshold']}")
        print(f"    Assistant model: {cfg['llm']['assistant_endpoint']}")
        print(f"    Classifier model: {cfg['llm']['classifier_endpoint']}")
        assert cfg["cache"]["similarity_threshold"] == 0.9, f"Unexpected cache threshold"
        assert cfg["cache"]["answer_morph_threshold"] == 0.75, f"Unexpected morph threshold"
        return cfg
    all_results.append(run_test("Tuning Config Validation", test_tuning_config))

    # ── Summary ──
    print(f"\n\n{'='*70}")
    print(f"  ROUND 3 SUMMARY")
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

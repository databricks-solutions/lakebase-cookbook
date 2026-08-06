"""Tests for Genie sample question extraction and balancing."""

import json
from types import SimpleNamespace

from agent_server.sample_questions import (
    balance_sample_questions,
    extract_genie_sample_questions,
    refresh_genie_spaces_and_samples,
)


def test_extract_genie_sample_questions_reads_samples_and_benchmarks():
    serialized = json.dumps(
        {
            "config": {
                "sample_questions": [
                    {"question": ["Sample A"]},
                    {"question": "Sample B"},
                ]
            },
            "benchmarks": {
                "questions": [
                    {"question": ["Benchmark C"]},
                    {"question": ["Sample A"]},
                ]
            },
        }
    )

    questions = extract_genie_sample_questions("space-1", "Space One", serialized)

    assert questions == [
        {"question": "Sample A", "space_id": "space-1", "space_title": "Space One", "badge": None},
        {"question": "Sample B", "space_id": "space-1", "space_title": "Space One", "badge": None},
    ]


def test_balance_sample_questions_limits_each_space():
    questions = [
        {"question": f"Cancer {i}", "space_id": "cancer", "space_title": "Cancer", "badge": None}
        for i in range(5)
    ] + [
        {"question": f"Trials {i}", "space_id": "trials", "space_title": "Trials", "badge": None}
        for i in range(2)
    ]

    balanced = balance_sample_questions(questions, max_per_space=3)

    assert [q["question"] for q in balanced] == [
        "Cancer 0",
        "Cancer 1",
        "Cancer 2",
        "Trials 0",
        "Trials 1",
    ]


def test_refresh_genie_spaces_and_samples_fetches_latest_payload():
    spaces = [
        SimpleNamespace(space_id="space-1", title="old title", description="old description"),
    ]
    payload = {
        "title": "Updated Space",
        "description": "Fresh description",
        "serialized_space": json.dumps(
            {
                "config": {
                    "sample_questions": [
                        {"question": ["Fresh question"]},
                    ]
                },
                "benchmarks": {
                    "questions": [
                        {"question": ["Stale benchmark"]},
                    ]
                },
            }
        ),
    }

    class FakeResponse:
        def read(self):
            return json.dumps(payload).encode()

    client = SimpleNamespace(
        config=SimpleNamespace(
            host="https://workspace.example",
            authenticate=lambda: {"Authorization": "Bearer token"},
        )
    )

    samples = refresh_genie_spaces_and_samples(
        spaces,
        workspace_client=client,
        urlopen=lambda req, timeout: FakeResponse(),
    )

    assert spaces[0].title == "Updated Space"
    assert spaces[0].description == "Fresh description"
    assert samples == [
        {
            "question": "Fresh question",
            "space_id": "space-1",
            "space_title": "Updated Space",
            "badge": None,
        }
    ]

"""Utilities for extracting and balancing Genie Space sample questions."""

import json
from collections import defaultdict
from collections.abc import Iterable
from typing import Any
import urllib.request


def _question_text(raw: Any) -> str | None:
    """Normalize Genie sample question shapes into a plain string."""
    if isinstance(raw, list) and raw:
        raw = raw[0]
    if isinstance(raw, str):
        text = raw.strip()
        return text or None
    return None


def _loads_json(value: Any) -> dict:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return value if isinstance(value, dict) else {}


def extract_genie_sample_questions(
    space_id: str,
    space_title: str,
    serialized_space: str | dict | None,
) -> list[dict]:
    """Extract curated sample questions from a Genie Space."""
    space_data = _loads_json(serialized_space)
    config = _loads_json(space_data.get("config", {}))

    questions: list[dict] = []
    seen: set[str] = set()

    def add(raw_question: Any) -> None:
        text = _question_text(raw_question)
        if not text or text in seen:
            return
        seen.add(text)
        questions.append(
            {
                "question": text,
                "space_id": space_id,
                "space_title": space_title,
                "badge": None,
            }
        )

    for item in config.get("sample_questions", []):
        if isinstance(item, dict):
            add(item.get("question"))

    return questions


def balance_sample_questions(questions: Iterable[dict], max_per_space: int = 3) -> list[dict]:
    """Limit sample questions per Genie Space while preserving configured space order."""
    by_space: dict[str, list[dict]] = defaultdict(list)
    space_order: list[str] = []

    for question in questions:
        space_key = str(question.get("space_id") or question.get("space_title") or "")
        if not space_key:
            continue
        if space_key not in by_space:
            space_order.append(space_key)
        if len(by_space[space_key]) < max_per_space:
            by_space[space_key].append(question)

    balanced: list[dict] = []
    for space_key in space_order:
        balanced.extend(by_space[space_key])
    return balanced


def refresh_genie_spaces_and_samples(
    spaces: list,
    *,
    workspace_client: Any | None = None,
    urlopen: Any = urllib.request.urlopen,
    timeout: int = 15,
    max_per_space: int = 3,
) -> list[dict]:
    """Fetch latest Genie Space metadata and return balanced sample questions."""
    if not spaces:
        return []

    if workspace_client is None:
        from databricks.sdk import WorkspaceClient

        workspace_client = WorkspaceClient()

    host = workspace_client.config.host.rstrip("/")
    headers = workspace_client.config.authenticate()

    all_questions: list[dict] = []
    for space in spaces:
        url = f"{host}/api/2.0/genie/spaces/{space.space_id}?include_serialized_space=true"
        req = urllib.request.Request(url, headers={**headers, "Content-Type": "application/json"})
        resp = json.loads(urlopen(req, timeout=timeout).read())

        space.title = resp.get("title", space.space_id)
        space.description = resp.get("description", "")
        all_questions.extend(
            extract_genie_sample_questions(
                space_id=space.space_id,
                space_title=space.title,
                serialized_space=resp.get("serialized_space", ""),
            )
        )

    return balance_sample_questions(all_questions, max_per_space=max_per_space)

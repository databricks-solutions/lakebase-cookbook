"""Regression checks for the Chat landing demo prompts."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_chat_landing_has_cached_questions_section():
    chat_page = (ROOT / "frontend" / "src" / "pages" / "ChatPage.tsx").read_text()

    assert "getLandingData" in chat_page
    assert "Cached questions" in chat_page
    assert "badge-cached" in chat_page


def test_chat_landing_groups_prompts_by_genie_space():
    chat_page = (ROOT / "frontend" / "src" / "pages" / "ChatPage.tsx").read_text()

    assert "cachedQuestionsBySpace" in chat_page
    assert "sampleQuestionsBySpace" in chat_page
    assert "empty-space-group-title" in chat_page


def test_chat_landing_waits_for_demo_prompts_before_fallback():
    chat_page = (ROOT / "frontend" / "src" / "pages" / "ChatPage.tsx").read_text()
    api = (ROOT / "frontend" / "src" / "api.ts").read_text()

    assert "promptsLoading" in chat_page
    assert "Loading demo prompts" in chat_page
    assert "/landing-data" in api
    assert "/sample-questions" not in chat_page
    assert "/genie/spaces/active" not in chat_page

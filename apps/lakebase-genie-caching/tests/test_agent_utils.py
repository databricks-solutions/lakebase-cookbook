"""Tests for agent_server/utils.py — request extraction helpers."""

import pytest
from types import SimpleNamespace

from agent_server.utils import extract_user_id, extract_session_id, extract_question


# ---------------------------------------------------------------------------
# extract_user_id
# ---------------------------------------------------------------------------

class TestExtractUserId:
    def test_from_context(self):
        req = SimpleNamespace(
            context=SimpleNamespace(user_id="alice@example.com"),
            custom_inputs=None,
        )
        assert extract_user_id(req) == "alice@example.com"

    def test_from_custom_inputs_fallback(self):
        req = SimpleNamespace(
            context=None,
            custom_inputs={"user_id": "bob@example.com"},
        )
        assert extract_user_id(req) == "bob@example.com"

    def test_context_takes_precedence(self):
        req = SimpleNamespace(
            context=SimpleNamespace(user_id="ctx@example.com"),
            custom_inputs={"user_id": "ci@example.com"},
        )
        assert extract_user_id(req) == "ctx@example.com"

    def test_no_context_no_custom_inputs(self):
        req = SimpleNamespace(context=None, custom_inputs=None)
        assert extract_user_id(req) == "anonymous"

    def test_empty_context_user_id(self):
        req = SimpleNamespace(
            context=SimpleNamespace(user_id=""),
            custom_inputs={"user_id": "fallback@example.com"},
        )
        assert extract_user_id(req) == "fallback@example.com"

    def test_bare_object_no_attrs(self):
        req = object()
        assert extract_user_id(req) == "anonymous"


# ---------------------------------------------------------------------------
# extract_session_id
# ---------------------------------------------------------------------------

class TestExtractSessionId:
    def test_present(self):
        req = SimpleNamespace(custom_inputs={"session_id": "sess-42"})
        assert extract_session_id(req) == "sess-42"

    def test_missing_key(self):
        req = SimpleNamespace(custom_inputs={"user_id": "u1"})
        assert extract_session_id(req) is None

    def test_no_custom_inputs(self):
        req = SimpleNamespace(custom_inputs=None)
        assert extract_session_id(req) is None

    def test_no_attr(self):
        req = object()
        assert extract_session_id(req) is None


# ---------------------------------------------------------------------------
# extract_question
# ---------------------------------------------------------------------------

class TestExtractQuestion:
    def test_simple_string_content(self):
        item = SimpleNamespace(
            model_dump=lambda: {"role": "user", "content": "What is sales?"}
        )
        req = SimpleNamespace(input=[item])
        assert extract_question(req) == "What is sales?"

    def test_list_content_with_input_text(self):
        item = SimpleNamespace(
            model_dump=lambda: {
                "role": "user",
                "content": [{"type": "input_text", "text": "Hello world"}],
            }
        )
        req = SimpleNamespace(input=[item])
        assert extract_question(req) == "Hello world"

    def test_picks_last_user_message(self):
        item1 = SimpleNamespace(
            model_dump=lambda: {"role": "user", "content": "first"}
        )
        item2 = SimpleNamespace(
            model_dump=lambda: {"role": "assistant", "content": "reply"}
        )
        item3 = SimpleNamespace(
            model_dump=lambda: {"role": "user", "content": "second"}
        )
        req = SimpleNamespace(input=[item1, item2, item3])
        assert extract_question(req) == "second"

    def test_empty_input(self):
        req = SimpleNamespace(input=[])
        assert extract_question(req) == ""

    def test_none_input(self):
        req = SimpleNamespace(input=None)
        assert extract_question(req) == ""

    def test_dict_items_supported(self):
        req = SimpleNamespace(input=[{"role": "user", "content": "plain dict"}])
        assert extract_question(req) == "plain dict"

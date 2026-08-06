"""Tests for _bridge_to_our_response — pure-logic conversion from bridge to our format."""

import pandas as pd
import numpy as np
import pytest
from dataclasses import dataclass
from typing import Optional, Union

from backend.services.genie_client import _bridge_to_our_response, GenieResponse


@dataclass
class FakeBridgeResponse:
    """Mimics databricks_ai_bridge.genie.GenieResponse without importing it."""
    result: Union[str, pd.DataFrame]
    query: Optional[str] = ""
    description: Optional[str] = ""
    conversation_id: Optional[str] = None


EMPTY_STEPS: list[dict] = []


class TestNonEmptyDataFrame:
    def test_columns_and_data_extracted(self):
        df = pd.DataFrame({"name": ["Alice", "Bob"], "age": [30, 25]})
        bridge = FakeBridgeResponse(result=df, query="SELECT name, age FROM users")
        resp = _bridge_to_our_response(bridge, EMPTY_STEPS, 100.0)

        assert resp.status == "COMPLETED"
        assert resp.columns == ["name", "age"]
        assert resp.row_count == 2
        assert resp.data is not None
        assert len(resp.data) == 2
        assert resp.sql == "SELECT name, age FROM users"

    def test_datetime_values_serialized(self):
        df = pd.DataFrame({
            "ts": pd.to_datetime(["2024-01-01", "2024-06-15"]),
            "val": [1, 2],
        })
        bridge = FakeBridgeResponse(result=df, query="SELECT ts, val FROM t")
        resp = _bridge_to_our_response(bridge, EMPTY_STEPS, 50.0)

        assert resp.row_count == 2
        assert isinstance(resp.data[0][0], str)

    def test_nat_values_become_none(self):
        df = pd.DataFrame({"ts": [pd.NaT, pd.Timestamp("2024-01-01")]})
        bridge = FakeBridgeResponse(result=df, query="SELECT ts FROM t")
        resp = _bridge_to_our_response(bridge, EMPTY_STEPS, 50.0)

        assert resp.data[0][0] is None


class TestEmptyDataFrame:
    def test_empty_df_row_count_zero(self):
        df = pd.DataFrame({"x": pd.Series([], dtype="float64")})
        bridge = FakeBridgeResponse(result=df, query="SELECT x FROM t")
        resp = _bridge_to_our_response(bridge, EMPTY_STEPS, 50.0)

        assert resp.status == "COMPLETED"
        assert resp.row_count == 0
        assert resp.data == []
        assert resp.columns == ["x"]

    def test_empty_df_no_columns(self):
        df = pd.DataFrame()
        bridge = FakeBridgeResponse(result=df, query="SELECT 1")
        resp = _bridge_to_our_response(bridge, EMPTY_STEPS, 50.0)

        assert resp.row_count == 0
        assert resp.columns is None

    def test_text_attachment_used_as_description_when_zero_rows(self):
        df = pd.DataFrame({"x": pd.Series([], dtype="float64")})
        bridge = FakeBridgeResponse(result=df, query="SELECT x FROM t")
        resp = _bridge_to_our_response(
            bridge, EMPTY_STEPS, 50.0,
            text_attachment_content="No data found for breast cancer trials.",
        )
        assert resp.description == "No data found for breast cancer trials."


class TestStringResults:
    def test_error_string(self):
        bridge = FakeBridgeResponse(result="Genie query failed: timeout")
        resp = _bridge_to_our_response(bridge, EMPTY_STEPS, 200.0)

        assert resp.status == "FAILED"
        assert resp.error == "Genie query failed: timeout"
        assert resp.sql is None

    def test_timeout_string(self):
        bridge = FakeBridgeResponse(result="Genie query timed out after 60s")
        resp = _bridge_to_our_response(bridge, EMPTY_STEPS, 200.0)

        assert resp.status == "FAILED"
        assert "timed out" in resp.error

    def test_empty_string_result(self):
        bridge = FakeBridgeResponse(result="EMPTY")
        resp = _bridge_to_our_response(bridge, EMPTY_STEPS, 50.0)

        assert resp.row_count == 0
        assert resp.data == []

    def test_text_result_no_sql_becomes_description(self):
        bridge = FakeBridgeResponse(
            result="Here is a helpful explanation",
            query=None,
            description=None,
        )
        resp = _bridge_to_our_response(bridge, EMPTY_STEPS, 50.0)
        assert resp.description == "Here is a helpful explanation"


class TestMetadataPropagation:
    def test_follow_up_questions(self):
        df = pd.DataFrame({"x": [1]})
        bridge = FakeBridgeResponse(result=df, conversation_id="conv-1")
        resp = _bridge_to_our_response(
            bridge, EMPTY_STEPS, 50.0,
            follow_up_questions=["What about region B?", "Show trends"],
        )
        assert resp.follow_up_questions == ["What about region B?", "Show trends"]

    def test_message_id_propagated(self):
        df = pd.DataFrame({"x": [1]})
        bridge = FakeBridgeResponse(result=df)
        resp = _bridge_to_our_response(
            bridge, EMPTY_STEPS, 50.0, message_id="msg-42",
        )
        assert resp.message_id == "msg-42"

    def test_conversation_id_propagated(self):
        df = pd.DataFrame({"x": [1]})
        bridge = FakeBridgeResponse(result=df, conversation_id="conv-99")
        resp = _bridge_to_our_response(bridge, EMPTY_STEPS, 50.0)
        assert resp.conversation_id == "conv-99"

    def test_latency_and_steps(self):
        steps = [{"status": "COMPLETED", "label": "Complete", "elapsed_s": 1.0, "duration_ms": 500}]
        df = pd.DataFrame({"x": [1]})
        bridge = FakeBridgeResponse(result=df)
        resp = _bridge_to_our_response(bridge, steps, 1234.5)
        assert resp.latency_ms == 1234.5
        assert resp.execution_steps == steps

    def test_text_attachment_fallback_when_no_sql_no_description(self):
        bridge = FakeBridgeResponse(result="", query=None, description=None)
        resp = _bridge_to_our_response(
            bridge, EMPTY_STEPS, 50.0,
            text_attachment_content="Genie's explanation here",
        )
        assert resp.description == "Genie's explanation here"

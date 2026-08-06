"""Utility helpers for the agent server."""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def extract_user_id(request) -> str:
    """Extract user identity from a ResponsesAgentRequest.

    In Databricks Apps, the user identity flows through context.user_id
    or custom_inputs.user_id.  Falls back to "anonymous".
    """
    user_id = "anonymous"

    if hasattr(request, "context") and request.context:
        ctx = request.context
        if hasattr(ctx, "user_id") and ctx.user_id:
            user_id = ctx.user_id

    if user_id == "anonymous" and hasattr(request, "custom_inputs") and request.custom_inputs:
        user_id = request.custom_inputs.get("user_id", user_id)

    return user_id


def extract_session_id(request) -> Optional[str]:
    """Extract session_id from a ResponsesAgentRequest's custom_inputs."""
    if hasattr(request, "custom_inputs") and request.custom_inputs:
        return request.custom_inputs.get("session_id")
    return None


def extract_question(request) -> str:
    """Extract the latest user message from request.input."""
    if not request.input:
        return ""
    for item in reversed(request.input):
        item_dict = item.model_dump() if hasattr(item, "model_dump") else item
        if isinstance(item_dict, dict):
            role = item_dict.get("role")
            if role == "user":
                content = item_dict.get("content", "")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "input_text":
                            return part.get("text", "")
    return ""

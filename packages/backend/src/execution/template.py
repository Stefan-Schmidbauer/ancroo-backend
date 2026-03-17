"""Shared Jinja2 rendering and JSONPath extraction utilities."""

import json
import re
from typing import Any

from jinja2.sandbox import SandboxedEnvironment


def json_escape(value: str) -> str:
    """Escape a string so it is safe inside a JSON string literal."""
    return json.dumps(value)[1:-1]


def render_payload(template_str: str, input_data: dict[str, Any]) -> str:
    """Render a Jinja2 template with input data.

    Available variables: text, html, clipboard, fields, context, url, title, _input.
    String values are JSON-escaped for safe embedding in JSON payloads.
    """
    env = SandboxedEnvironment()
    template = env.from_string(template_str)

    text = input_data.get("text", "")
    html = input_data.get("html", "")
    clipboard = input_data.get("clipboard", "")
    context = input_data.get("context", {})

    variables = {
        "text": json_escape(text),
        "html": json_escape(html),
        "clipboard": json_escape(clipboard),
        "fields": input_data.get("fields", {}),
        "context": context,
        "url": json_escape(context.get("url", "")),
        "title": json_escape(context.get("title", "")),
        "_input": input_data,
    }

    return template.render(**variables)


def render_prompt(template_str: str, input_data: dict[str, Any]) -> str:
    """Render a Jinja2 prompt template with input data.

    Unlike render_payload, this does NOT JSON-escape strings — prompts are
    plain text, not JSON payloads.
    """
    env = SandboxedEnvironment()
    template = env.from_string(template_str)

    context = input_data.get("context", {})

    variables = {
        "text": input_data.get("text", ""),
        "html": input_data.get("html", ""),
        "clipboard": input_data.get("clipboard", ""),
        "fields": input_data.get("fields", {}),
        "context": context,
        "url": context.get("url", ""),
        "title": context.get("title", ""),
        "_input": input_data,
    }

    return template.render(**variables)


def extract_response(data: Any, mapping: str) -> str:
    """Extract a value from response data using a simple JSONPath-like expression.

    Supports: $.response, $.choices[0].message.content, $.result.text
    """
    if not mapping:
        return str(data) if not isinstance(data, str) else data

    path = mapping.lstrip("$").lstrip(".")
    current = data
    parts = re.split(r"\.(?![^\[]*\])", path)

    for part in parts:
        if not part:
            continue

        match = re.match(r"^(\w+)\[(\d+)\]$", part)
        if match:
            field, index = match.group(1), int(match.group(2))
            if isinstance(current, dict) and field in current:
                current = current[field]
                if isinstance(current, list) and index < len(current):
                    current = current[index]
                else:
                    return ""
            else:
                return ""
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return ""

    return str(current) if not isinstance(current, str) else current

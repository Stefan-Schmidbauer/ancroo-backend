"""Input/output mapping between Ancroo and external tool providers.

Mapping format:
{
    "target_field": "source.nested.field",     # Dot-notation path
    "static_field": {"_value": "fixed_value"}, # Static value
}

When no mapping is defined, data is passed through as-is.
"""

from typing import Any


def _get_nested(data: dict, path: str) -> Any:
    """Get a value from a nested dict using dot notation.

    Example: _get_nested({"context": {"url": "https://..."}}, "context.url")
    """
    keys = path.split(".")
    current = data
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key)
        else:
            return None
    return current


def apply_input_mapping(input_data: dict[str, Any], mapping: dict | None) -> dict[str, Any]:
    """Map Ancroo input to tool input format.

    Args:
        input_data: Standard Ancroo input {"text": "...", "context": {...}}
        mapping: Optional mapping definition

    Returns:
        Transformed input for the external tool.
        If no mapping, returns input_data as-is.

    Mapping format:
        {
            "text_field": "text",              # tool expects "text_field" ← Ancroo "text"
            "page_url": "context.url",         # nested access
            "mode": {"_value": "transform"}    # static value
        }
    """
    if not mapping:
        return input_data

    result = {}
    for target_key, source in mapping.items():
        if isinstance(source, dict) and "_value" in source:
            result[target_key] = source["_value"]
        elif isinstance(source, str):
            result[target_key] = _get_nested(input_data, source)
        else:
            result[target_key] = source

    return result


def apply_output_mapping(output: dict[str, Any], mapping: dict | None) -> dict[str, Any]:
    """Map tool output to Ancroo ExecutionResult format.

    Args:
        output: Raw response from external tool
        mapping: Optional mapping definition

    Returns:
        Normalized dict with keys: text, action, success, metadata

    Default behavior (no mapping):
        - text: output["text"] or output["result"] or output["output"]
        - action: output["action"] or "replace_selection"
        - success: True
        - metadata: remaining fields

    Mapping format:
        {
            "text": "output.generated_text",
            "action": {"_value": "replace_selection"}
        }
    """
    if mapping:
        return {
            "text": _resolve_mapping_value(output, mapping.get("text", "text")),
            "action": _resolve_mapping_value(output, mapping.get("action", {"_value": "replace_selection"})),
            "success": True,
            "metadata": {k: v for k, v in output.items() if k not in ("text", "result", "action", "output")},
        }

    # Default: auto-detect common response patterns
    text = output.get("text") or output.get("result") or output.get("output")
    action = output.get("action", "replace_selection")
    metadata = {k: v for k, v in output.items() if k not in ("text", "result", "action", "output", "success")}

    return {
        "text": text,
        "action": action,
        "success": output.get("success", True),
        "metadata": metadata,
    }


def _resolve_mapping_value(data: dict, mapping_value: Any) -> Any:
    """Resolve a single mapping value (path string or static value)."""
    if isinstance(mapping_value, dict) and "_value" in mapping_value:
        return mapping_value["_value"]
    elif isinstance(mapping_value, str):
        return _get_nested(data, mapping_value)
    return mapping_value

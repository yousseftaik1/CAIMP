"""
Output Validator — parses and cleans the raw JSON string returned by the LLM.

The LLM is instructed to return OUTPUT_SCHEMA (prompts.py), but models
occasionally wrap the JSON in markdown fences, add extra keys, or use
wrong enum values. This module handles all of that and returns a clean dict,
or raises ValueError when the response is unrecoverable.
"""
from __future__ import annotations

import json
import logging
import re

log = logging.getLogger(__name__)

_VALID_SEVERITY   = {"critical", "high", "medium", "low"}
_VALID_CONFIDENCE = {"high", "medium", "low"}
_REQUIRED_KEYS    = {
    "severity", "explanation", "root_cause",
    "recommended_action", "evidence_spl_queries", "confidence",
}


def _extract_json(text: str) -> str:
    """Strip markdown fences and extract the first JSON object found."""
    text = text.strip()
    # ```json ... ``` or ``` ... ```
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return m.group(1)
    # bare JSON object anywhere in the string
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        return m.group(0)
    return text


def validate_and_parse(raw: str) -> dict:
    """
    Parse and validate the LLM response string.

    Returns a clean dict conforming to OUTPUT_SCHEMA.
    Raises ValueError on unrecoverable parse or missing required keys.
    """
    cleaned = _extract_json(raw)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"LLM returned non-JSON: {exc} | raw={raw[:300]!r}"
        ) from exc

    if not isinstance(data, dict):
        raise ValueError(f"LLM returned non-object JSON type={type(data).__name__}")

    # ── required key check ────────────────────────────────────────────────────
    missing = _REQUIRED_KEYS - data.keys()
    if missing:
        raise ValueError(f"LLM response missing keys: {missing} | raw={raw[:200]!r}")

    # ── normalise severity ────────────────────────────────────────────────────
    sev = str(data["severity"]).lower().strip()
    if sev not in _VALID_SEVERITY:
        log.warning(f"Unexpected severity {sev!r} — defaulting to 'medium'")
        sev = "medium"
    data["severity"] = sev

    # ── normalise confidence ──────────────────────────────────────────────────
    conf = str(data["confidence"]).lower().strip()
    if conf not in _VALID_CONFIDENCE:
        log.warning(f"Unexpected confidence {conf!r} — defaulting to 'low'")
        conf = "low"
    data["confidence"] = conf

    # ── evidence_spl_queries must be a list of strings (max 5) ───────────────
    queries = data.get("evidence_spl_queries", [])
    if not isinstance(queries, list):
        queries = [str(queries)] if queries else []
    data["evidence_spl_queries"] = [str(q) for q in queries[:5]]

    # ── ensure free-text fields are non-empty strings ─────────────────────────
    for key in ("explanation", "root_cause", "recommended_action"):
        data[key] = str(data.get(key, "")).strip() or "(not provided)"

    return {k: data[k] for k in _REQUIRED_KEYS}

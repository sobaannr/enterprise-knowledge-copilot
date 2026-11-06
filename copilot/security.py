"""Defense in depth: deterministic boundaries remain authoritative, not this heuristic."""

import re

from fastapi import HTTPException

PATTERNS = [
    r"ignore\s+(?:all\s+)?(?:previous|prior|system)\s+instructions",
    r"(?:reveal|print|exfiltrate|send)\b.{0,50}\b(?:api.?key|secret|system prompt)",
    r"(?:approve|create|execute)\b.{0,60}\bwithout\s+(?:human\s+)?approval",
    r"<\s*(?:system|tool_call)\b",
    r"\bGEMINI_API_KEY\b",
]


def injection_signals(text):
    return [f"rule-{i + 1}" for i, pattern in enumerate(PATTERNS) if re.search(pattern, text, re.I | re.S)]


def guard_question(question):
    if injection_signals(question):
        raise HTTPException(
            400,
            "Request contains an instruction to bypass controls or expose secrets. Rephrase the business question.",
        )

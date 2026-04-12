from __future__ import annotations

import re

_INJECTION_PATTERNS = [
    re.compile(r"ignore previous instructions?", re.IGNORECASE),
    re.compile(r"disregard (all|your) (previous|prior|earlier)?\s*instructions?", re.IGNORECASE),
    re.compile(r"you are now", re.IGNORECASE),
    re.compile(r"act as (?!(a |an )?(researcher|expert|analyst))", re.IGNORECASE),
    re.compile(r"system\s*prompt", re.IGNORECASE),
    re.compile(r"<\s*(system|instruction|prompt)\s*>", re.IGNORECASE),
]

_DANGEROUS_QUERY_PATTERNS = [
    re.compile(r"\b(password|passwd|secret|api.?key|token|credentials?)\b", re.IGNORECASE),
    re.compile(r"\b(ssn|social.security|credit.card)\b", re.IGNORECASE),
]


def sanitize_query(query: str) -> str:
    for pattern in _DANGEROUS_QUERY_PATTERNS:
        if pattern.search(query):
            raise ValueError(f"Query contains sensitive terms: {query!r}")
    return query.strip()


def sanitize_web_content(content: str, max_length: int = 10000) -> str:
    for pattern in _INJECTION_PATTERNS:
        content = pattern.sub("[REDACTED]", content)
    return content[:max_length]

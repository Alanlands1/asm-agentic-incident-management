"""Deterministic facts about a ticket, computed locally before any model call."""

import re
from dataclasses import dataclass
from typing import Optional

from app.agents.data_quality.config import DQConfig, normalise

GREETING = re.compile(r"^\s*(hi|hello|hey|dear)\b[^,\n]{0,40}[,\n]\s*", re.I)
SIGN_OFF = re.compile(r"^\s*(thanks|thank you|regards|best|cheers|kind regards|sent from my)\b[\w\s&,.!]{0,30}$", re.I)


@dataclass(frozen=True)
class Signals:
    body_length: int  # after greeting, signature and filler phrases are removed
    placeholder_only: bool
    app_found: Optional[str]
    app_source: Optional[str]  # "system" when the source field names it, "keyword" when found in the text
    identifier_found: bool
    attachment_only: bool
    summary_equals_body: bool
    mentions_previous_ticket: bool


def strip_body(body: str) -> str:
    """Drop the greeting and everything from the sign-off down, and collapse whitespace."""
    lines = GREETING.sub("", body or "", count=1).splitlines()
    end = next((i for i, line in enumerate(lines) if SIGN_OFF.match(line)), len(lines))
    return " ".join(" ".join(lines[:end]).split())


def _without_filler(text: str, config: DQConfig) -> str:
    for pattern in config.filler:
        text = pattern.sub(" ", text)
    return " ".join(text.split())


def _find_app(text: str, config: DQConfig) -> Optional[str]:
    hits = {name: m.start() for name, pattern in config.apps.items() if (m := pattern.search(text))}
    return min(hits, key=hits.get) if hits else None


def compute_signals(summary: str, body: str, attachments: Optional[str], application: Optional[str], config: DQConfig) -> Signals:
    stripped = strip_body(body)
    length = len(_without_filler(stripped, config))
    text = f"{summary}\n{body}"
    keyword_app = None if application else _find_app(text, config)
    return Signals(
        body_length=length,
        placeholder_only=bool(stripped) and normalise(stripped) in config.placeholder,
        app_found=application or keyword_app,
        app_source="system" if application else "keyword" if keyword_app else None,
        identifier_found=any(p.search(config.ticket_reference.sub(" ", text)) for p in config.identifier),
        attachment_only=bool(attachments) and length < config.min_body_length,
        summary_equals_body=not stripped or stripped.casefold() == " ".join(summary.split()).casefold(),
        mentions_previous_ticket=bool(config.ticket_reference.search(text)) or any(p.search(text) for p in config.previous_ticket),
    )

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .i18n import DEICTIC_MARKERS, PLURAL_DEICTIC_MARKERS, all_locale_markers

THREAD_MATCH_WEIGHT = 10
AUTHOR_MATCH_WEIGHT = 5
DEICTIC_MEDIA_CAP_SINGULAR = 1
DEICTIC_MEDIA_CAP_PLURAL = 3
TEXT_BACKGROUND_LIMIT = 8

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic"}


@dataclass
class ContextCandidate:
    source: str
    message_id: str
    author: str
    created_at: float
    modality: str
    row: Any = None
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)


@dataclass
class ContextPack:
    scope: str
    has_explicit_anchor: bool
    text_rows: list
    media_rows: list
    memory_rows: list
    excluded: list


def deixis(text: str) -> dict | None:
    # ponytail: keyword heuristic; swap for a classifier if precision matters.
    value = text or ""
    plural = any(marker in value for marker in all_locale_markers(PLURAL_DEICTIC_MARKERS))
    if plural or any(marker in value for marker in all_locale_markers(DEICTIC_MARKERS)):
        return {"present": True, "plural": plural}
    return None


class ContextSelector:
    def select(self, event: Any, *, recent_rows, memory_rows) -> ContextPack:
        # focused_reply is triggered by an explicit user reply, NOT by whether parent media
        # downloaded — a text/failed/preview-only parent must still narrow the evidence set.
        candidates = [self._candidate(event, row) for row in recent_rows]
        excluded: list[tuple[str, str]] = []
        anchor_id = getattr(event, "reply_to_message_id", None) or self._thread_id(event)
        if anchor_id and str(anchor_id) == str(getattr(event, "message_id", "")):
            # ponytail: Slack top-level messages use their own ts as synthetic thread_id.
            anchor_id = None
        if anchor_id:
            anchor = str(anchor_id)
            anchor_candidates = [
                candidate
                for candidate in candidates
                if candidate.message_id == anchor or str(candidate.row["thread_id"] or "") == anchor
            ]
            for candidate in candidates:
                if candidate not in anchor_candidates:
                    excluded.append((candidate.message_id, "focused_reply:anchor"))
            return ContextPack(
                "focused_reply",
                True,
                [candidate.row for candidate in anchor_candidates],
                [candidate.row for candidate in anchor_candidates if self._has_media(candidate.row)],
                list(memory_rows),
                excluded,
            )

        marker = deixis(getattr(event, "text", "") or "")
        if marker:
            ranked = self._rank(candidates)
            cap = DEICTIC_MEDIA_CAP_PLURAL if marker.get("plural") else DEICTIC_MEDIA_CAP_SINGULAR
            media_candidates = [candidate for candidate in ranked if self._has_media(candidate.row)]
            media_rows = [candidate.row for candidate in media_candidates[:cap]]
            excluded.extend((candidate.message_id, "deictic:cap") for candidate in media_candidates[cap:])

            scored_exists = any(candidate.score > 0 for candidate in ranked)
            text_candidates = [candidate for candidate in ranked if candidate.score > 0] if scored_exists else ranked
            if scored_exists:
                excluded.extend((candidate.message_id, "deictic:low_relevance") for candidate in ranked if candidate.score <= 0)
            return ContextPack(
                "deictic_recent",
                False,
                [candidate.row for candidate in text_candidates[:TEXT_BACKGROUND_LIMIT]],
                media_rows,
                list(memory_rows),
                excluded,
            )

        ranked = self._rank(candidates)
        excluded.extend((candidate.message_id, "plain:no_media_signal") for candidate in ranked if self._has_media(candidate.row))
        scored = [candidate for candidate in ranked if candidate.score > 0]
        text_candidates = scored if scored else ranked
        return ContextPack(
            "plain",
            False,
            [candidate.row for candidate in text_candidates[:TEXT_BACKGROUND_LIMIT]],
            [],
            list(memory_rows),
            excluded,
        )

    def _rank(self, candidates: list[ContextCandidate]) -> list[ContextCandidate]:
        return sorted(candidates, key=lambda candidate: (candidate.score, candidate.created_at), reverse=True)

    def _candidate(self, event: Any, row: Any) -> ContextCandidate:
        reasons: list[str] = []
        score = 0.0
        thread = self._thread_id(event) or getattr(event, "reply_to_message_id", None)
        if thread and row["thread_id"] == thread:
            score += THREAD_MATCH_WEIGHT
            reasons.append("thread")
        author = self._author(event)
        if author and row["author"] == author:
            score += AUTHOR_MATCH_WEIGHT
            reasons.append("author")
        return ContextCandidate(
            source="recent",
            message_id=str(row["message_id"]),
            author=str(row["author"] or ""),
            created_at=float(row["created_at"]),
            modality=self._modality(row),
            row=row,
            score=score,
            reasons=reasons,
        )

    def _modality(self, row: Any) -> str:
        paths = self._media_paths(row)
        if not paths:
            return "text"
        suffixes = {Path(str(path)).suffix.lower() for path in paths}
        if suffixes and suffixes <= IMAGE_SUFFIXES:
            return "image"
        if suffixes and suffixes.isdisjoint(IMAGE_SUFFIXES):
            return "file"
        return "mixed"

    def _has_media(self, row: Any) -> bool:
        return bool(self._media_paths(row))

    def _media_paths(self, row: Any) -> list[str]:
        try:
            return list(json.loads(row["media_paths"] or "[]"))
        except Exception:
            return []

    def _author(self, event: Any) -> str:
        source = getattr(event, "source", None)
        return str(getattr(source, "user_id", "") or getattr(source, "user_name", "") or getattr(event, "author", ""))

    def _thread_id(self, event: Any) -> str | None:
        return getattr(getattr(event, "source", None), "thread_id", None) or getattr(event, "thread_id", None)

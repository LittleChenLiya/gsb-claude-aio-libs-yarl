"""Raw query string editing plans.

A raw query edit plan captures the original (encoded) query string of a
URL and records value replacements addressed by decoded key and occurrence
index. The plan is applied atomically: the original query is re-parsed,
and if it contains illegal percent-escapes or no longer matches the
captured baseline, no modification is made.

The byte ranges returned by the apply methods are offsets into the
original query string (the baseline), measured in bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ._quoters import QUERY_PART_QUOTER, UNQUOTER_PLUS

if TYPE_CHECKING:
    from ._url import URL

__all__ = ("RawQueryEditPlan",)


@dataclass(frozen=True)
class _RawPair:
    """A parsed pair from a raw query string, with byte offsets."""

    key: str
    value: str
    raw_key: str
    raw_value: str
    has_equals: bool
    start: int
    end: int
    value_start: int
    value_end: int


def _is_hex_byte(byte: int) -> bool:
    return 0x30 <= byte <= 0x39 or 0x41 <= byte <= 0x46 or 0x61 <= byte <= 0x66


def _validate_escapes(query: bytes) -> None:
    """Validate that every percent sign starts a valid escape."""
    pos = 0
    while True:
        idx = query.find(b"%", pos)
        if idx == -1:
            return
        if idx + 2 >= len(query) or not (
            _is_hex_byte(query[idx + 1]) and _is_hex_byte(query[idx + 2])
        ):
            raise ValueError(
                "Illegal percent-escape in query at byte "
                f"{idx}: {query[idx : idx + 3].decode('ascii', errors='replace')!r}"
            )
        pos = idx + 3


def _parse_raw_query(query: str) -> list[_RawPair]:
    """Parse a raw query string into pairs with byte offsets."""
    query_bytes = query.encode("utf-8")
    _validate_escapes(query_bytes)
    pairs: list[_RawPair] = []
    if not query_bytes:
        return pairs
    start = 0
    for segment in query_bytes.split(b"&"):
        end = start + len(segment)
        if segment:
            eq = segment.find(b"=")
            if eq == -1:
                raw_key_bytes = segment
                raw_value_bytes = b""
                has_equals = False
                value_start = end
            else:
                raw_key_bytes = segment[:eq]
                raw_value_bytes = segment[eq + 1 :]
                has_equals = True
                value_start = start + eq + 1
            value_end = end
            raw_key = raw_key_bytes.decode("utf-8")
            raw_value = raw_value_bytes.decode("utf-8")
            key = UNQUOTER_PLUS(raw_key)
            value = UNQUOTER_PLUS(raw_value)
            pairs.append(
                _RawPair(
                    key,
                    value,
                    raw_key,
                    raw_value,
                    has_equals,
                    start,
                    end,
                    value_start,
                    value_end,
                )
            )
        start = end + 1
    return pairs


class RawQueryEditPlan:
    """An immutable plan for editing a URL's raw query string.

    The plan captures the original (encoded) query string of the URL it
    is created from and records value replacements addressed by decoded
    key and occurrence index. Call set to add replacements, then apply
    (or apply_to) to produce a new URL.

    The plan is bound to the original query text. If the target URL's
    query no longer matches the captured baseline, or the query contains
    illegal percent-escapes, applying the plan raises ValueError and no
    modification is made.
    """

    __slots__ = ("_url", "_baseline", "_edits")

    def __init__(self, url: URL) -> None:
        self._url = url
        self._baseline = url._query
        self._edits: tuple[tuple[str, int, str], ...] = ()

    def set(self, key: str, value: str, *, occurrence: int = 0) -> "RawQueryEditPlan":
        """Return a new plan with an additional value replacement.

        Addresses the occurrence-th pair whose decoded key is key
        (0-based). The new value is encoded with YARL's query part
        quoter.

        Raises ValueError if occurrence is negative. The existence of
        the addressed pair is checked when the plan is applied.
        """
        if occurrence < 0:
            raise ValueError("occurrence must be >= 0")
        plan = RawQueryEditPlan.__new__(RawQueryEditPlan)
        plan._url = self._url
        plan._baseline = self._baseline
        plan._edits = (*self._edits, (key, occurrence, value))
        return plan

    def _apply(self, url: URL) -> tuple[URL, dict[tuple[str, int], tuple[int, int]]]:
        if url._query != self._baseline:
            raise ValueError(
                "Query baseline has changed since the plan was created; "
                "the plan no longer applies to this URL"
            )
        pairs = _parse_raw_query(self._baseline)
        replacements: list[tuple[int, int, str, str, int]] = []
        for key, occurrence, new_value in self._edits:
            idx = -1
            count = 0
            for i, pair in enumerate(pairs):
                if pair.key == key:
                    if count == occurrence:
                        idx = i
                        break
                    count += 1
            if idx == -1:
                raise ValueError(f"No pair with key {key!r} at occurrence {occurrence}")
            pair = pairs[idx]
            encoded_value = QUERY_PART_QUOTER(new_value)
            if pair.has_equals:
                replacement = encoded_value
            else:
                # Bare key: add '=' + value after the key.
                replacement = "=" + encoded_value
            replacements.append(
                (pair.value_start, pair.value_end, replacement, key, occurrence)
            )
        # Apply from the end of the query backwards so earlier byte
        # offsets stay valid as replacements are made.
        replacements.sort(key=lambda r: r[0], reverse=True)
        new_query = self._baseline
        ranges: dict[tuple[str, int], tuple[int, int]] = {}
        for start, end, replacement, key, occurrence in replacements:
            new_query = new_query[:start] + replacement + new_query[end:]
            # The range is measured in the original (baseline) bytes.
            ranges[(key, occurrence)] = (start, end)
        new_url = self._build_url(url, new_query)
        return new_url, ranges

    def _build_url(self, url: URL, new_query: str) -> URL:
        """Build a new URL with new_query, preserving all other parts."""
        # Imported locally to avoid loading the URL machinery at module
        # import time; _url.py is heavy and is imported right after us.
        from ._url import from_parts_uncached  # noqa: PLC0415

        new_url = from_parts_uncached(
            url._scheme,
            url._netloc,
            url._path,
            new_query,
            url._fragment,
            url._mode,
            url._empty,
        )
        if "_join_path" in url._cache:
            url._keep_join_path(new_url)
        return new_url

    def apply(self) -> tuple[URL, dict[tuple[str, int], tuple[int, int]]]:
        """Apply the plan to the URL it was created from.

        Returns a tuple of the new URL (with the edited query) and a
        mapping from (decoded_key, occurrence) to the byte range
        (start, end) in the original query that was replaced.

        Raises ValueError if the query contains illegal percent-escapes.
        """
        return self._apply(self._url)

    def apply_to(self, url: URL) -> tuple[URL, dict[tuple[str, int], tuple[int, int]]]:
        """Apply the plan to a different URL.

        Like apply, but verifies that the URL's query matches the
        captured baseline before applying. Raises ValueError if the
        baseline has changed or the query contains illegal escapes.
        """
        return self._apply(url)

    def __repr__(self) -> str:
        return f"<RawQueryEditPlan baseline={self._baseline!r} edits={self._edits!r}>"

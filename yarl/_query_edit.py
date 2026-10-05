"""Explicit edit plans for the raw query of a URL.

The :class:`~yarl.URL` class normalizes (re-quotes) the query component,
which is usually what is wanted.  Sometimes, though, the exact bytes of
the original text must be preserved: unselected percent-escapes must
keep their spelling (including case), empty items and bare keys must
stay as they are, and the fragment must keep its raw bytes.

This module plans a single-value replacement directly against the
original text of a URL.  The value is selected by its *decoded* key and
its *occurrence* (order of appearance) among the items with that key,
so duplicate keys are addressed individually instead of being collapsed
into a mapping.  The plan is bound to the original text: it is only
applied while the baseline is unchanged, and no plan is made at all for
a query that contains an invalid percent-escape.

>>> plan = plan_query_edit("http://h/?a=%2f&a=2#frag", "a", 3, occurrence=1)
>>> plan.range_map()
{'a[1]': (18, 19)}
>>> plan.apply()
'http://h/?a=%2f&a=3#frag'
"""

from dataclasses import dataclass

from ._query import SimpleQuery, query_var
from ._quoters import QUERY_PART_QUOTER, UNQUOTER_PLUS

__all__ = (
    "QueryEdit",
    "QueryEditPlan",
    "RawQuery",
    "parse_raw_query",
    "plan_query_edit",
)

_HEX_DIGITS = frozenset("0123456789ABCDEFabcdef")


@dataclass(frozen=True)
class RawQuery:
    """Location of the query and fragment components in the original text.

    ``span`` is ``None`` when the text has no query component at all, and
    a ``(start, end)`` pair -- possibly empty, with ``start == end`` --
    when a ``?`` is present.  This is how an empty query (``http://h/?``)
    is distinguished from no query (``http://h/``).  All offsets are
    counted in the original text, never in a re-encoded form of it.
    """

    span: "tuple[int, int] | None"
    fragment_span: "tuple[int, int] | None"

    @property
    def has_query(self) -> bool:
        """Whether a ``?`` is present, even if the query itself is empty."""
        return self.span is not None


def parse_raw_query(text: str) -> RawQuery:
    """Locate the query and fragment components in the raw text of a URL.

    Nothing is decoded, re-quoted or otherwise normalized; the returned
    spans always refer to the original bytes of *text*.
    """
    hash_idx = text.find("#")
    if hash_idx == -1:
        end = len(text)
        fragment_span = None
    else:
        end = hash_idx
        fragment_span = (hash_idx + 1, len(text))
    q_idx = text.find("?", 0, end)
    span = None if q_idx == -1 else (q_idx + 1, end)
    return RawQuery(span=span, fragment_span=fragment_span)


def _has_invalid_escape(text: str, start: int, end: int) -> bool:
    """Return True if text[start:end] has a '%' not followed by 2 hex digits."""
    pos = text.find("%", start, end)
    while pos != -1:
        if (
            pos + 3 > end
            or text[pos + 1] not in _HEX_DIGITS
            or text[pos + 2] not in _HEX_DIGITS
        ):
            return True
        pos = text.find("%", pos + 1, end)
    return False


@dataclass(frozen=True)
class QueryEdit:
    """One replacement within the original text of a URL.

    ``start`` and ``end`` are offsets in the *original* text (the
    baseline the plan is bound to), so the edit range is always expressed
    in original bytes, never in positions of the re-encoded output.
    ``replacement`` is the already-encoded text to splice in.
    """

    key: str
    occurrence: int
    start: int
    end: int
    replacement: str

    @property
    def span(self) -> "tuple[int, int]":
        """The ``(start, end)`` range of the edit in the original text."""
        return (self.start, self.end)


class QueryEditPlan:
    """An explicit query edit plan, bound to the original text it was made from."""

    __slots__ = ("_original", "_edits")

    def __init__(self, original: str, edits: "list[QueryEdit]") -> None:
        self._original = original
        self._edits = tuple(edits)

    @property
    def original(self) -> str:
        """The original text the plan is bound to."""
        return self._original

    @property
    def edits(self) -> "tuple[QueryEdit, ...]":
        """The planned edits, in order of appearance in the original text."""
        return self._edits

    def range_map(self) -> "dict[str, tuple[int, int]]":
        """Map each edit to its ``(start, end)`` range in the original text.

        Keys are ``"<decoded key>[<occurrence>]"``; values are offsets
        counted in the original bytes of the bound text.
        """
        return {
            f"{edit.key}[{edit.occurrence}]": (edit.start, edit.end)
            for edit in self._edits
        }

    def apply(self, text: "str | None" = None) -> str:
        """Apply the planned edits and return the modified text.

        When *text* is given it must equal the baseline the plan was
        built from; a changed baseline raises :exc:`ValueError` and
        nothing is modified.
        """
        if text is None:
            text = self._original
        elif text != self._original:
            raise ValueError(
                "the plan is bound to a different original text, "
                "refusing to modify a changed baseline"
            )
        for edit in sorted(self._edits, key=lambda e: e.start, reverse=True):
            text = text[: edit.start] + edit.replacement + text[edit.end :]
        return text

    def __repr__(self) -> str:
        return f"<QueryEditPlan edits={self._edits!r}>"


def plan_query_edit(
    text: str, key: str, value: SimpleQuery, *, occurrence: int = 0
) -> "QueryEditPlan | None":
    """Plan the replacement of one query value in the original text of a URL.

    The item is selected by its *decoded* key (``+`` and percent-escapes
    are decoded for the comparison, matching
    :func:`~urllib.parse.parse_qsl` semantics) and by *occurrence*, its
    0-based order of appearance among the items with the same decoded
    key.  The new *value* is encoded with the regular yarl query
    encoding rules; everything else -- unselected percent-escape
    spelling, empty items, bare keys and the raw fragment bytes -- is
    left untouched.

    Returns ``None``, planning and modifying nothing, when the text has
    no query, the query is empty, the decoded key does not occur often
    enough, or the query contains an invalid percent-escape.

    An item that is a bare key (``?a``) has no value to replace, so the
    edit inserts ``=<value>`` right after it; an empty value (``?a=``)
    is replaced like any other value.  The two are never conflated.
    """
    if occurrence < 0:
        raise ValueError("occurrence must be a non-negative integer")
    raw = parse_raw_query(text)
    if raw.span is None:
        return None  # no query at all
    start, end = raw.span
    if start == end:
        return None  # an empty query has no items to edit
    if _has_invalid_escape(text, start, end):
        return None  # never modify a query with invalid escapes
    replacement = QUERY_PART_QUOTER(value if type(value) is str else query_var(value))
    seen = 0
    pos = start
    while pos <= end:
        amp = text.find("&", pos, end)
        item_end = end if amp == -1 else amp
        if item_end > pos:  # empty items are preserved, never matched
            eq = text.find("=", pos, item_end)
            key_end = item_end if eq == -1 else eq
            if UNQUOTER_PLUS(text[pos:key_end]) == key:
                if seen == occurrence:
                    if eq == -1:
                        # A bare key: insert "=<value>" right after it.
                        edit = QueryEdit(
                            key, occurrence, item_end, item_end, "=" + replacement
                        )
                    else:
                        edit = QueryEdit(key, occurrence, eq + 1, item_end, replacement)
                    return QueryEditPlan(text, [edit])
                seen += 1
        if amp == -1:
            break
        pos = amp + 1
    return None

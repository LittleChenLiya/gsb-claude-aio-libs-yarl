"""Explicit canonical signing input for URL request signatures.

Different HTTP clients disagree on how a URL is rendered before a
signature (HMAC, canonical query strings in the AWS SigV4 style, OAuth
base strings, and so on). :func:`canonical_signing_input` builds the
signing input from a :class:`~yarl.URL` with explicit rules so that two
clients holding the same URL derive the same bytes:

* the query is parsed into decoded items without ever going through a
  plain ``dict``, so repeated keys survive and their value order is
  kept;
* the caller chooses which query keys take part via *include*;
* the selected items are stably sorted by their **decoded** key,
  keeping the original occurrence order for equal (including
  percent-encoding equivalent) keys;
* values of repeated keys are never reordered;
* a bare key (``a``) and an empty-valued key (``a=``) are distinct in
  the default distinguish mode;
* the scheme, host/authority, path and percent encoding follow the
  canonical form already stored on the :class:`~yarl.URL`; the URL
  itself is never modified.

The canonical byte format is::

    <scheme>://<raw-authority><raw-path>?<canonical-query>

encoded as UTF-8. A scheme-relative URL omits ``<scheme>:`` and a
relative URL omits the ``//<raw-authority>`` part entirely. The ``?`` is
present only when at least one included query item remains.

In the canonical query, spaces are written as ``+`` (form encoding),
literal plus signs as ``%2B``, and non-ASCII text as uppercase UTF-8
percent escapes, matching :func:`urllib.parse.urlencode` and the query
rendering used elsewhere in yarl.

Copyable examples::

    >>> from yarl import URL, canonical_signing_input
    >>> result = canonical_signing_input(URL("http://example.com/?b=2&a=1&a=3"))
    >>> result.canonical_query
    'a=1&a=3&b=2'
    >>> result.canonical_bytes
    b'http://example.com/?a=1&a=3&b=2'
    >>> result.index_map  # original field position -> canonical position
    {1: 0, 2: 1, 0: 2}

Bare keys (``a``) and empty values (``a=``) are distinct by default::

    >>> r = canonical_signing_input(URL("http://example.com/?a&a="))
    >>> r.canonical_query
    'a&a='
    >>> r = canonical_signing_input(
    ...     URL("http://example.com/?a&a="), distinguish_blank_values=False
    ... )
    >>> r.canonical_query
    'a=&a='

A literal space is a ``+`` and a literal plus is ``%2B``; Unicode is
UTF-8 percent encoded::

    >>> r = canonical_signing_input(URL("http://example.com/?k=a+b%2Bc&u=%C3%A9"))
    >>> r.canonical_query
    'k=a+b%2Bc&u=%C3%A9'

Only the keys passed to *include* take part::

    >>> r = canonical_signing_input(
    ...     URL("http://example.com/?sig=abc&b=2&a=1"), include=("a", "b")
    ... )
    >>> r.canonical_query
    'a=1&b=2'

The original URL is untouched::

    >>> str(URL("http://example.com/?b=2&a=1&a=3"))
    'http://example.com/?b=2&a=1&a=3'

Run the related tests with::

    python -m pytest tests/test_signing.py -q
"""

import codecs
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Union
from urllib.parse import parse_qsl

from ._quoters import QUERY_PART_REQUOTER, UNQUOTER_PLUS
from ._url import URL

__all__ = (
    "CanonicalQueryItem",
    "CanonicalSigningInput",
    "IncludeKeys",
    "canonical_signing_input",
)

# A parsed field: original field position, decoded key, decoded value,
# and whether the field carried an "=" separator.
_ParsedField = tuple[int, str, str, bool]

IncludeKeys = Union[
    Iterable[str],
    Callable[[str], bool],
    None,
]
"""Selection of query keys that take part in the signing input.

* ``None`` includes every key;
* an iterable of strings includes the listed **decoded** keys (a
  repeated key is included once per occurrence);
* a callable receives each decoded key and the item is included when it
  returns a true value.
"""


@dataclass(frozen=True)
class CanonicalQueryItem:
    """One query item in its canonical position.

    Attributes:
        key: Decoded key.
        value: Decoded value (empty for a bare key).
        has_equals: Whether the original item carried an ``=``
            separator. Distinguishes the bare ``a`` from the
            empty-valued ``a=`` while *distinguish_blank_values* is
            enabled.
        source_index: Zero-based position of the item among the
            original query's fields, including excluded fields and
            empty fields.
    """

    key: str
    value: str
    has_equals: bool
    source_index: int


@dataclass(frozen=True)
class CanonicalSigningInput:
    """Result of :func:`canonical_signing_input`.

    Attributes:
        canonical_query: The canonical query string: included items
            sorted stably by decoded key, joined with ``&``.
        query_items: The included items in their canonical order.
        index_map: Mapping from the original zero-based field position
            to the zero-based position within *query_items*. Only
            included items appear as keys.
        canonical_text: The full signing input as text.
        canonical_bytes: The full signing input as UTF-8 bytes; this is
            the value to hash or sign.
    """

    canonical_query: str
    query_items: tuple[CanonicalQueryItem, ...]
    index_map: Mapping[int, int]
    canonical_text: str
    canonical_bytes: bytes


def _decode_field(field: str, encoding: str, use_utf8: bool) -> tuple[str, str]:
    """Decode one query field (without its ``&`` separator)."""
    if "%" not in field:
        # Only "+" needs decoding, identically in every encoding.
        name, _, value = field.replace("+", " ").partition("=")
        return name, value
    if use_utf8:
        name, _, value = field.partition("=")
        return UNQUOTER_PLUS(name), UNQUOTER_PLUS(value)
    [(name, value)] = parse_qsl(field, keep_blank_values=True, encoding=encoding) or [
        ("", "")
    ]
    return name, value


def _query_items(raw_query: str, encoding: str) -> list[_ParsedField]:
    """Parse *raw_query* into ``(position, key, value, has_equals)``.

    Mirrors :func:`yarl._parse.query_to_pairs` but retains whether an
    ``=`` separator was present and tags each field with its original
    position. Empty fields (as in ``?a=1&&b=2``) are not items but do
    occupy a field position.
    """
    if not raw_query:
        return []
    use_utf8 = encoding == "utf-8" or codecs.lookup(encoding).name == "utf-8"
    items: list[_ParsedField] = []
    for position, field in enumerate(raw_query.split("&")):
        if not field:
            continue
        has_equals = "=" in field
        key, value = _decode_field(field, encoding, use_utf8)
        items.append((position, key, value, has_equals))
    return items


def _render_distinguished(field: _ParsedField) -> str:
    _, key, value, has_equals = field
    # Re-quoting is required because the decoded value can contain
    # characters that only looked percent encoded in the source.
    quoted_key = QUERY_PART_REQUOTER(key)
    if not has_equals:
        return quoted_key
    return f"{quoted_key}={QUERY_PART_REQUOTER(value)}"


def canonical_signing_input(
    url: URL,
    *,
    include: IncludeKeys = None,
    distinguish_blank_values: bool = True,
    encoding: str = "utf-8",
) -> CanonicalSigningInput:
    """Build the canonical signing input for *url*.

    Args:
        url: A :class:`~yarl.URL`. Only its stored canonical components
            are read; it is never modified.
        include: Selects which decoded query keys take part; see
            :data:`IncludeKeys`. By default every key is included.
        distinguish_blank_values: When true (the default), a bare key
            (``a``) is rendered without ``=`` and kept distinct from an
            empty-valued key (``a=``). When false, both are rendered as
            ``a=`` and compare equal for signing purposes.
        encoding: Encoding used when percent-decoding the original
            query. Canonical output is always rendered as UTF-8.

    Returns:
        A :class:`CanonicalSigningInput`; sign its
        :attr:`~CanonicalSigningInput.canonical_bytes`.
    """
    if not isinstance(url, URL):
        raise TypeError("url must be a yarl.URL instance")

    raw_items = _query_items(url.raw_query_string, encoding)

    if include is None:
        selected = raw_items
    elif callable(include):
        selected = [item for item in raw_items if include(item[1])]
    elif isinstance(include, str):
        raise TypeError(
            "include must be an iterable of decoded keys, a callable, "
            "or None; a single string is ambiguous"
        )
    else:
        wanted = set(include)
        selected = [item for item in raw_items if item[1] in wanted]

    # Stable sort by the decoded key only: repeated and
    # percent-encoding equivalent keys keep their original occurrence
    # order, and with it the order of their values.
    ordered = sorted(selected, key=lambda item: item[1])

    if distinguish_blank_values:
        fields = [_render_distinguished(item) for item in ordered]
    else:
        fields = [
            f"{QUERY_PART_REQUOTER(key)}={QUERY_PART_REQUOTER(value)}"
            for _, key, value, _ in ordered
        ]
    canonical_items = tuple(
        CanonicalQueryItem(
            key=key,
            value=value,
            has_equals=has_equals if distinguish_blank_values else True,
            source_index=position,
        )
        for position, key, value, has_equals in ordered
    )

    canonical_query = "&".join(fields)

    scheme = url.scheme
    netloc = url.raw_authority
    path = url.raw_path
    if netloc:
        text = f"{scheme + ':' if scheme else ''}//{netloc}{path}"
    elif scheme:
        text = f"{scheme}:{path}"
    else:
        text = path
    if canonical_query:
        text = f"{text}?{canonical_query}"

    index_map = {
        item.source_index: target for target, item in enumerate(canonical_items)
    }

    return CanonicalSigningInput(
        canonical_query=canonical_query,
        query_items=canonical_items,
        index_map=index_map,
        canonical_text=text,
        canonical_bytes=text.encode("utf-8"),
    )

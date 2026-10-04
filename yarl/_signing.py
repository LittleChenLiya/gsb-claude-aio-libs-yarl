"""Canonicalize a URL for request signing.

The canonical form reuses yarl's normal URL parsing and normalization:
the scheme, host, path and percent-encoding follow yarl's conventions
(see :class:`yarl.URL`), while the query string is rebuilt from a
stably sorted, caller-selected set of decoded query items. The result
is a deterministic byte string that different clients can reproduce to
verify a signature.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import NamedTuple

from ._parse import EMPTY_QUERY
from ._quoters import QUERY_PART_QUOTER, UNQUOTER_PLUS
from ._url import URL, from_parts_uncached

__all__ = ("QueryItem", "SignatureCanonicalization", "canonicalize_for_signature")


class QueryItem(NamedTuple):
    """A single decoded query item.

    Attributes:
        key: the decoded key.
        value: the decoded value. It is ``""`` for a bare key when bare
            keys are distinguished (see ``distinguish_empty``).
        has_equals: ``True`` if the item carried an ``=`` separator in the
            original query string (``a=1``), ``False`` for a bare key
            (``a``).
    """

    key: str
    value: str
    has_equals: bool


@dataclass(frozen=True, slots=True)
class SignatureCanonicalization:
    """The result of canonicalizing a URL for signing.

    Attributes:
        url: the canonical URL. This is a new :class:`yarl.URL` object;
            the original URL passed to
            :func:`canonicalize_for_signature` is never modified.
        data: the canonical byte string that is the signature input. It
            is the UTF-8 encoding of the canonical URL as yarl renders
            it (``scheme://netloc/path?query``), so it includes the
            normalized scheme, host and path and the canonical query.
        query: the canonical query string, without the leading ``?``.
        items: all original query items, decoded and in original order.
        canonical_items: the query items that participate in the
            signature, decoded and stably sorted by key. Duplicate keys
            keep their original relative order.
        mapping: for each participating original item (in original
            order), a pair ``(original_index, canonical_index)`` into
            :attr:`items` and :attr:`canonical_items`. It records where
            each original item ends up in the canonical query.
    """

    url: URL
    data: bytes
    query: str
    items: tuple[QueryItem, ...]
    canonical_items: tuple[QueryItem, ...]
    mapping: tuple[tuple[int, int], ...]


def _parse_query_items(raw_query: str) -> list[QueryItem]:
    """Decode a raw query string into items, keeping bare-key distinction.

    ``+`` is decoded as a space and percent-encoded bytes are decoded as
    UTF-8 (with replacement for invalid sequences), matching
    :func:`yarl.query_to_pairs`. Unlike :func:`yarl.query_to_pairs`, the
    ``=`` separator is recorded so that bare keys (``a``) and empty
    values (``a=``) can be told apart.
    """
    items: list[QueryItem] = []
    for field in raw_query.split("&"):
        if not field:
            # Empty fields (e.g. "a&&b") carry no item.
            continue
        name, sep, value = field.partition("=")
        items.append(
            QueryItem(
                UNQUOTER_PLUS(name),
                UNQUOTER_PLUS(value),
                bool(sep),
            )
        )
    return items


def canonicalize_for_signature(
    url: URL | str,
    *,
    keys: Iterable[str] | None = None,
    distinguish_empty: bool = False,
) -> SignatureCanonicalization:
    """Canonicalize *url* for request signing.

    The query is rebuilt from the decoded query items whose key is in
    *keys* (all items participate when *keys* is ``None``). Items are
    stably sorted by decoded key: Python's sort is stable, so duplicate
    keys keep their original relative order (the order of their values
    does not change).

    Empty values (``a=``) and bare keys (``a``) are normalized to the
    yarl convention ``a=`` unless *distinguish_empty* is ``True``, in
    which case bare keys stay bare (``a``).

    The scheme, host, path and percent-encoding follow yarl's normal
    conventions; the original *url* is never modified.

    :param url: the URL to canonicalize.
    :param keys: the decoded keys of the query items that participate in
        the signature, or ``None`` for all items.
    :param distinguish_empty: when ``True``, bare keys (``a``) and empty
        values (``a=``) are kept distinct; otherwise both normalize to
        ``a=``.
    :return: a :class:`SignatureCanonicalization` with the canonical
        :class:`~SignatureCanonicalization.url`, the canonical byte
        string (:attr:`~SignatureCanonicalization.data`), the canonical
        query string (:attr:`~SignatureCanonicalization.query`), the
        decoded :attr:`~SignatureCanonicalization.items` and
        :attr:`~SignatureCanonicalization.canonical_items` and the
        :attr:`~SignatureCanonicalization.mapping` from original item
        positions to canonical positions.

    .. doctest::

       >>> from yarl import URL, canonicalize_for_signature
       >>> res = canonicalize_for_signature(URL("http://example.com/?b=2&a=1&a=3"))
       >>> res.query
       'a=1&a=3&b=2'
       >>> res.mapping
       ((0, 2), (1, 0), (2, 1))
       >>> res.data
       b'http://example.com/?a=1&a=3&b=2'
    """
    if not isinstance(url, URL):
        url = URL(url)
    items = tuple(_parse_query_items(url.raw_query_string))

    if keys is None:
        kept = list(items)
    else:
        wanted = frozenset(keys)
        kept = [item for item in items if item.key in wanted]

    # Stable sort by decoded key: items that compare equal (duplicate
    # keys) keep their original relative order.
    kept.sort(key=lambda item: item.key)
    canonical_items = tuple(kept)

    parts: list[str] = []
    for item in canonical_items:
        key = QUERY_PART_QUOTER(item.key)
        if item.has_equals or not distinguish_empty:
            parts.append(f"{key}={QUERY_PART_QUOTER(item.value)}")
        else:
            parts.append(key)
    canonical_query = "&".join(parts)

    # Build the canonical URL with the already-encoded query as-is. Using
    # from_parts_uncached (the constructor behind URL.with_query) avoids
    # running the query through the quoter again, which would double-encode
    # the percent-escapes produced above.
    canonical_url = from_parts_uncached(
        url._scheme,
        url._netloc,
        url._path,
        canonical_query,
        url._fragment,
        url._mode,
        url._empty & ~EMPTY_QUERY,
    )

    return SignatureCanonicalization(
        url=canonical_url,
        data=str(canonical_url).encode("utf-8"),
        query=canonical_query,
        items=items,
        canonical_items=canonical_items,
        mapping=tuple(
            (orig_idx, canon_idx)
            for orig_idx, item in enumerate(items)
            for canon_idx, canon_item in enumerate(canonical_items)
            if canon_item is item
        ),
    )

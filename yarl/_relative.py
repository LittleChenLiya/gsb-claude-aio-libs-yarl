"""Explicit relative reference generator.

Given a *base* URL and a *target* URL, :func:`relative_reference` computes
the shortest legal reference that resolves back to the target through the
original :meth:`URL.join` — no network access, purely local computation.

Path, query and fragment changes are handled separately:

* a same-directory file change yields just the file name (``"other.html"``),
* a query-only change yields a query-only reference (``"?x=2"``),
* a fragment-only change yields a fragment-only reference (``"#sec"``),
* a target identical to the base (modulo the fragment) yields the empty
  reference (``""``),
* a segment with an encoded slash (``%2F``) is treated as one segment and
  is never split into path separators,
* a cross-origin target yields the explicit absolute reference, a relative
  path is never faked across hosts.

Every candidate is verified with the original ``join()`` and the comparison
uses :class:`URL` equality, so the canonical identity of the target is
preserved.

Four URL examples:

>>> from yarl import URL, relative_reference
>>> relative_reference(
...     URL("http://example.com/a/b/page.html"),
...     URL("http://example.com/a/b/other.html"),
... )
'other.html'
>>> relative_reference(
...     URL("http://example.com/a/b?x=1"), URL("http://example.com/a/b?x=2")
... )
'?x=2'
>>> relative_reference(
...     URL("http://example.com/a/"), URL("http://example.com/a/b%2Fc")
... )
'b%2Fc'
>>> relative_reference(
...     URL("http://example.com/a/b/c"),
...     URL("http://static.example.com/a/b/c"),
... )
'http://static.example.com/a/b/c'

Run the tests with::

    python -m pytest tests/test_relative_reference.py -o addopts= -q
"""

from ._parse import EMPTY_FRAGMENT, EMPTY_QUERY
from ._url import URL

__all__ = ("relative_reference",)


def _suffix(target: URL) -> str:
    """Return the "?query#fragment" part of a reference to *target*."""
    suffix = []
    if target._query or target._empty & EMPTY_QUERY:
        suffix.append(f"?{target._query}")
    if target._fragment or target._empty & EMPTY_FRAGMENT:
        suffix.append(f"#{target._fragment}")
    return "".join(suffix)


def _relative_path(base_path: str, target_path: str) -> str:
    """Return a relative path reference from *base_path* to *target_path*.

    Both paths are raw (percent-encoded), so a segment containing an
    encoded slash ("%2F") is compared as a whole and is never split
    into path separators.
    """
    # The directory of the base: everything up to and including the last "/".
    base_dir = base_path[: base_path.rfind("/") + 1]
    if target_path.startswith(base_dir):
        rel = target_path[len(base_dir) :]
    else:
        base_dir_segments = base_dir.split("/")[:-1]
        target_segments = target_path.split("/")
        common = 0
        for base_segment, target_segment in zip(base_dir_segments, target_segments):
            if base_segment != target_segment:
                break
            common += 1
        ups = len(base_dir_segments) - common
        rel = "/".join([".."] * ups + target_segments[common:])
    if not rel:
        # The target is the directory of the base itself.
        return "./"
    if rel.startswith("/") and rel != target_path:
        # An empty segment follows the common prefix; a leading "/" would
        # be read as an absolute path and "//" as an authority, so hide
        # it behind a dot segment.
        return f"./{rel}"
    first_segment, _, _ = rel.partition("/")
    if ":" in first_segment:
        # A colon in the first segment would be read as a scheme.
        return f"./{rel}"
    return rel


def relative_reference(base: URL, target: URL) -> str:
    """Return the shortest reference that joins *base* back to *target*.

    The returned string is a legal URI-reference: resolving it with
    ``base.join(URL(reference))`` produces a URL equal to *target*.
    A cross-origin *target* yields the explicit absolute reference.
    """
    if type(base) is not URL or type(target) is not URL:
        raise TypeError("base and target should be URL")
    if base._scheme != target._scheme or base._netloc != target._netloc:
        # Cross-origin: the explicit policy is an absolute reference,
        # a relative path is never faked across hosts or schemes.
        return str(target)
    suffix = _suffix(target)
    base_path = base._path
    target_path = target._path
    candidates = []
    if target_path == base_path:
        # The empty reference (the boundary case: the target is the base
        # without its fragment) and a query/fragment-only reference.
        candidates.append("")
        if suffix:
            candidates.append(suffix)
        if target._fragment or target._empty & EMPTY_FRAGMENT:
            # A fragment-only reference, valid when the query is unchanged.
            candidates.append(f"#{target._fragment}")
    else:
        candidates.append(_relative_path(base_path, target_path) + suffix)
    if target_path:
        # The root-absolute reference, shorter than "../.." chains for
        # targets far away from the base directory.
        candidates.append(target_path + suffix)
    # The explicit absolute reference always resolves to the target.
    candidates.append(str(target))
    best = None
    for candidate in candidates:
        if best is not None and len(candidate) >= len(best):
            continue
        # Verify with the original join(); the URL equality check keeps
        # the canonical identity of the target.
        if base.join(URL(candidate, encoded=True, mode=base._mode)) == target:
            best = candidate
    if best is None:  # pragma: no cover
        raise ValueError(f"Cannot make a reference from {base!r} to {target!r}")
    return best

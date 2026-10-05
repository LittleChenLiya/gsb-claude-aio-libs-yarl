"""Tests for RawQueryEditPlan.

These tests exercise the raw query editing plan: value replacement by
decoded key and occurrence order, preservation of unselected percent
escapes and fragment bytes, empty value vs bare key distinction, YARL
encoding of new values, and the byte-range mapping.

Before / after editing examples
-------------------------------

Changing the second occurrence of ``a`` in ``a=%2f&a=2``:

    before:  http://example.com/?a=%2f&a=2#frag
    after:   http://example.com/?a=%2f&a=3#frag

The first pair (``a=%2f``) is untouched, so the ``%2f`` spelling and
case are preserved. The fragment ``#frag`` is untouched. The edit
range is ``(8, 9)``, the byte range of the original value ``2``.

Distinguishing empty values from bare keys:

    before:  http://example.com/?a=&b=2&c
    after:   http://example.com/?a=x&b=2&c=y

``a=`` has an empty value (range ``(2, 2)``); ``c`` is a bare key with
no ``=`` (range ``(8, 8)``, and ``=y`` is appended).

Local test commands
-------------------

Run only this test file::

    python -m pytest tests/test_query_edit.py -p no:cacheprovider --no-cov -v

Run a single test::

    python -m pytest tests/test_query_edit.py::test_acceptance_preserve_percent_case_and_fragment -p no:cacheprovider --no-cov -v

Run with the pure-Python quoter (no Cython extension needed)::

    YARL_NO_EXTENSIONS=1 python -m pytest tests/test_query_edit.py -p no:cacheprovider --no-cov -v
"""

import pytest

from yarl import URL, RawQueryEditPlan

# ---------------------------------------------------------------------------
# Basic value replacement
# ---------------------------------------------------------------------------


def test_set_single_value() -> None:
    # before: http://example.com/?a=1&b=2
    # after:  http://example.com/?a=1&b=3
    url = URL("http://example.com/?a=1&b=2", encoded=True)
    new_url, ranges = RawQueryEditPlan(url).set("b", "3").apply()
    assert str(new_url) == "http://example.com/?a=1&b=3"
    assert ranges == {("b", 0): (6, 7)}


def test_set_first_occurrence() -> None:
    # before: http://example.com/?a=1&a=2
    # after:  http://example.com/?a=X&a=2
    url = URL("http://example.com/?a=1&a=2", encoded=True)
    new_url, ranges = RawQueryEditPlan(url).set("a", "X", occurrence=0).apply()
    assert str(new_url) == "http://example.com/?a=X&a=2"
    assert ranges == {("a", 0): (2, 3)}


def test_set_second_occurrence() -> None:
    # before: http://example.com/?a=1&a=2
    # after:  http://example.com/?a=1&a=X
    url = URL("http://example.com/?a=1&a=2", encoded=True)
    new_url, ranges = RawQueryEditPlan(url).set("a", "X", occurrence=1).apply()
    assert str(new_url) == "http://example.com/?a=1&a=X"
    assert ranges == {("a", 1): (6, 7)}


# ---------------------------------------------------------------------------
# Acceptance: a=%2f&a=2, change second item, preserve %2f case and fragment
# ---------------------------------------------------------------------------


def test_acceptance_preserve_percent_case_and_fragment() -> None:
    # before: http://example.com/?a=%2f&a=2#frag
    # after:  http://example.com/?a=%2f&a=3#frag
    url = URL("http://example.com/?a=%2f&a=2#frag", encoded=True)
    new_url, ranges = RawQueryEditPlan(url).set("a", "3", occurrence=1).apply()
    assert str(new_url) == "http://example.com/?a=%2f&a=3#frag"
    assert ranges == {("a", 1): (8, 9)}
    # The first pair's %2f spelling and case are preserved.
    assert "a=%2f" in str(new_url)
    # The fragment is preserved byte-for-byte.
    assert new_url.raw_fragment == "frag"


def test_preserve_unselected_percent_escapes() -> None:
    # before: http://example.com/?a=%2f&b=%2F&c=%3d
    # after:  http://example.com/?a=%2f&b=new&c=%3d
    url = URL("http://example.com/?a=%2f&b=%2F&c=%3d", encoded=True)
    new_url, ranges = RawQueryEditPlan(url).set("b", "new").apply()
    assert str(new_url) == "http://example.com/?a=%2f&b=new&c=%3d"
    assert ranges == {("b", 0): (8, 11)}


def test_preserve_fragment_with_percent_escapes() -> None:
    # before: http://example.com/?a=1#frag%20ment
    # after:  http://example.com/?a=2#frag%20ment
    url = URL("http://example.com/?a=1#frag%20ment", encoded=True)
    new_url, ranges = RawQueryEditPlan(url).set("a", "2").apply()
    assert str(new_url) == "http://example.com/?a=2#frag%20ment"
    assert new_url.raw_fragment == "frag%20ment"


# ---------------------------------------------------------------------------
# Empty value vs bare key distinction
# ---------------------------------------------------------------------------


def test_empty_value() -> None:
    # before: http://example.com/?a=&b=2
    # after:  http://example.com/?a=x&b=2
    url = URL("http://example.com/?a=&b=2", encoded=True)
    new_url, ranges = RawQueryEditPlan(url).set("a", "x").apply()
    assert str(new_url) == "http://example.com/?a=x&b=2"
    # The empty value occupies zero bytes after the '='.
    assert ranges == {("a", 0): (2, 2)}


def test_bare_key() -> None:
    # before: http://example.com/?a&b=2
    # after:  http://example.com/?a=x&b=2
    url = URL("http://example.com/?a&b=2", encoded=True)
    new_url, ranges = RawQueryEditPlan(url).set("a", "x").apply()
    assert str(new_url) == "http://example.com/?a=x&b=2"
    # The bare key has no '='; the range is the end of the key and
    # '=x' is appended.
    assert ranges == {("a", 0): (1, 1)}


def test_empty_value_and_bare_key_together() -> None:
    # before: http://example.com/?a=&b=2&c
    # after:  http://example.com/?a=x&b=2&c=y
    url = URL("http://example.com/?a=&b=2&c", encoded=True)
    new_url, ranges = RawQueryEditPlan(url).set("a", "x").set("c", "y").apply()
    assert str(new_url) == "http://example.com/?a=x&b=2&c=y"
    assert ranges == {("a", 0): (2, 2), ("c", 0): (8, 8)}


def test_set_empty_value() -> None:
    # before: http://example.com/?a=1&b=2
    # after:  http://example.com/?a=&b=2
    url = URL("http://example.com/?a=1&b=2", encoded=True)
    new_url, ranges = RawQueryEditPlan(url).set("a", "").apply()
    assert str(new_url) == "http://example.com/?a=&b=2"
    assert ranges == {("a", 0): (2, 3)}


# ---------------------------------------------------------------------------
# YARL encoding of new values
# ---------------------------------------------------------------------------


def test_new_value_encoding() -> None:
    # before: http://example.com/?a=1&b=2
    # after:  http://example.com/?a=hello+world&b=x%26y%3Dz
    url = URL("http://example.com/?a=1&b=2", encoded=True)
    new_url, ranges = (
        RawQueryEditPlan(url).set("a", "hello world").set("b", "x&y=z").apply()
    )
    assert str(new_url) == "http://example.com/?a=hello+world&b=x%26y%3Dz"
    assert ranges == {("a", 0): (2, 3), ("b", 0): (6, 7)}


def test_new_value_encoding_special_chars() -> None:
    url = URL("http://example.com/?a=1", encoded=True)
    new_url, _ = RawQueryEditPlan(url).set("a", "100%").apply()
    assert str(new_url) == "http://example.com/?a=100%25"


# ---------------------------------------------------------------------------
# Multiple edits and duplicate keys
# ---------------------------------------------------------------------------


def test_multiple_edits() -> None:
    # before: http://example.com/?a=1&b=2&c=3
    # after:  http://example.com/?a=X&b=2&c=Y
    url = URL("http://example.com/?a=1&b=2&c=3", encoded=True)
    new_url, ranges = RawQueryEditPlan(url).set("a", "X").set("c", "Y").apply()
    assert str(new_url) == "http://example.com/?a=X&b=2&c=Y"
    assert ranges == {("a", 0): (2, 3), ("c", 0): (10, 11)}


def test_duplicate_keys_not_collapsed() -> None:
    # before: http://example.com/?a=1&a=2&a=3
    # after:  http://example.com/?a=X&a=2&a=Y
    url = URL("http://example.com/?a=1&a=2&a=3", encoded=True)
    new_url, ranges = (
        RawQueryEditPlan(url)
        .set("a", "X", occurrence=0)
        .set("a", "Y", occurrence=2)
        .apply()
    )
    assert str(new_url) == "http://example.com/?a=X&a=2&a=Y"
    assert ranges == {("a", 0): (2, 3), ("a", 2): (10, 11)}


def test_empty_segments_skipped() -> None:
    # before: http://example.com/?a=1&&b=2
    # after:  http://example.com/?a=1&&b=3
    # The empty segment between && is skipped, but the separator bytes
    # are preserved in the output.
    url = URL("http://example.com/?a=1&&b=2", encoded=True)
    new_url, ranges = RawQueryEditPlan(url).set("b", "3").apply()
    assert str(new_url) == "http://example.com/?a=1&&b=3"
    # The value '2' is at byte 7..8 in the query string (a=1&&b=2).
    assert ranges == {("b", 0): (7, 8)}


def test_leading_and_trailing_separators_preserved() -> None:
    # before: http://example.com/?&a=1&
    # after:  http://example.com/?&a=2&
    url = URL("http://example.com/?&a=1&", encoded=True)
    new_url, ranges = RawQueryEditPlan(url).set("a", "2").apply()
    assert str(new_url) == "http://example.com/?&a=2&"
    # The value '1' is at byte 3..4 in the query string (&a=1&).
    assert ranges == {("a", 0): (3, 4)}


# ---------------------------------------------------------------------------
# Empty query and no query
# ---------------------------------------------------------------------------


def test_empty_query_cannot_be_edited() -> None:
    # http://example.com/?  (empty query)
    url = URL("http://example.com/?")
    plan = RawQueryEditPlan(url).set("a", "x")
    with pytest.raises(ValueError, match="No pair with key"):
        plan.apply()


def test_no_query_cannot_be_edited() -> None:
    # http://example.com/  (no query)
    url = URL("http://example.com/")
    plan = RawQueryEditPlan(url).set("a", "x")
    with pytest.raises(ValueError, match="No pair with key"):
        plan.apply()


# ---------------------------------------------------------------------------
# Error handling: illegal escapes and baseline changes
# ---------------------------------------------------------------------------


def test_illegal_escape_raises_at_apply() -> None:
    # An illegal percent-escape (%2g) is kept by the pre-encoded parser
    # but rejected when the plan is applied.
    url = URL("http://example.com/?a=%2g&b=2", encoded=True)
    plan = RawQueryEditPlan(url).set("a", "x")
    with pytest.raises(ValueError, match="Illegal percent-escape"):
        plan.apply()


def test_illegal_escape_at_end_raises() -> None:
    url = URL("http://example.com/?a=%", encoded=True)
    plan = RawQueryEditPlan(url).set("a", "x")
    with pytest.raises(ValueError, match="Illegal percent-escape"):
        plan.apply()


def test_baseline_change_raises() -> None:
    url1 = URL("http://example.com/?a=1&b=2", encoded=True)
    url2 = URL("http://example.com/?a=9&b=2", encoded=True)
    plan = RawQueryEditPlan(url1).set("a", "x")
    with pytest.raises(ValueError, match="baseline has changed"):
        plan.apply_to(url2)


def test_nonexistent_key_raises_at_apply() -> None:
    url = URL("http://example.com/?a=1", encoded=True)
    plan = RawQueryEditPlan(url).set("b", "x")
    with pytest.raises(ValueError, match="No pair with key"):
        plan.apply()


def test_nonexistent_occurrence_raises_at_apply() -> None:
    url = URL("http://example.com/?a=1", encoded=True)
    plan = RawQueryEditPlan(url).set("a", "x", occurrence=1)
    with pytest.raises(ValueError, match="No pair with key"):
        plan.apply()


def test_negative_occurrence_raises() -> None:
    url = URL("http://example.com/?a=1", encoded=True)
    with pytest.raises(ValueError, match="occurrence must be >= 0"):
        RawQueryEditPlan(url).set("a", "x", occurrence=-1)


# ---------------------------------------------------------------------------
# Plan immutability and repr
# ---------------------------------------------------------------------------


def test_plan_is_immutable() -> None:
    url = URL("http://example.com/?a=1", encoded=True)
    plan0 = RawQueryEditPlan(url)
    plan1 = plan0.set("a", "x")
    assert plan0 is not plan1
    # The original plan is unchanged.
    new_url0, _ = plan0.apply()
    assert str(new_url0) == "http://example.com/?a=1"
    new_url1, _ = plan1.apply()
    assert str(new_url1) == "http://example.com/?a=x"


def test_plan_repr() -> None:
    url = URL("http://example.com/?a=1", encoded=True)
    plan = RawQueryEditPlan(url).set("a", "x")
    assert "baseline='a=1'" in repr(plan)
    assert "edits=" in repr(plan)


# ---------------------------------------------------------------------------
# apply_to with matching baseline
# ---------------------------------------------------------------------------


def test_apply_to_matching_baseline() -> None:
    url1 = URL("http://example.com/?a=1&b=2", encoded=True)
    url2 = URL("http://example.com/?a=1&b=2", encoded=True)
    plan = RawQueryEditPlan(url1).set("a", "x")
    new_url, ranges = plan.apply_to(url2)
    assert str(new_url) == "http://example.com/?a=x&b=2"
    assert ranges == {("a", 0): (2, 3)}


# ---------------------------------------------------------------------------
# Relative URLs and URLs without authority
# ---------------------------------------------------------------------------


def test_relative_url() -> None:
    # before: path?a=1
    # after:  path?a=2
    url = URL("path?a=1", encoded=True)
    new_url, ranges = RawQueryEditPlan(url).set("a", "2").apply()
    assert str(new_url) == "path?a=2"
    # The range is measured in the query string (a=1 -> byte 2..3).
    assert ranges == {("a", 0): (2, 3)}


def test_url_without_authority() -> None:
    # before: /path?a=1
    # after:  /path?a=2
    url = URL("/path?a=1", encoded=True)
    new_url, ranges = RawQueryEditPlan(url).set("a", "2").apply()
    assert str(new_url) == "/path?a=2"
    # The range is measured in the query string (a=1 -> byte 2..3).
    assert ranges == {("a", 0): (2, 3)}

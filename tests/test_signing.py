"""Tests for URL signature canonicalization."""

import pytest

from yarl import URL, QueryItem, canonicalize_for_signature


def test_basic_sort_and_mapping() -> None:
    res = canonicalize_for_signature(URL("http://example.com/?b=2&a=1&a=3"))
    assert res.query == "a=1&a=3&b=2"
    assert res.mapping == ((0, 2), (1, 0), (2, 1))
    assert res.canonical_items == (
        QueryItem("a", "1", True),
        QueryItem("a", "3", True),
        QueryItem("b", "2", True),
    )
    assert res.data == b"http://example.com/?a=1&a=3&b=2"


def test_duplicate_key_value_order_is_stable() -> None:
    res = canonicalize_for_signature(URL("http://h/?z=9&a=1&a=2&a=3&m=5"))
    assert res.query == "a=1&a=2&a=3&m=5&z=9"
    assert res.mapping == ((0, 4), (1, 0), (2, 1), (3, 2), (4, 3))


def test_encoded_equivalent_keys_are_stable() -> None:
    # "%61" decodes to "a": it sorts together with "a" by decoded key, and
    # the original occurrence order is kept.
    res = canonicalize_for_signature(URL("http://h/?%61=1&a=2&b=3"))
    assert res.query == "a=1&a=2&b=3"
    assert res.mapping == ((0, 0), (1, 1), (2, 2))


def test_percent_encoding_is_canonical() -> None:
    res = canonicalize_for_signature(URL("http://h/?b=2&a=1"))
    assert res.query == "a=1&b=2"
    # The canonical URL reuses yarl's normalized host/path.
    assert res.url == URL("http://h/?a=1&b=2")
    assert res.data == b"http://h/?a=1&b=2"


def test_plus_means_space_and_literal_plus_escaped() -> None:
    # A '+' in the query is a space (form-urlencoded); a literal '+' in a
    # value is encoded as %2B.
    res = canonicalize_for_signature(URL("http://h/?a=hello+world&b=%2B"))
    assert res.query == "a=hello+world&b=%2B"
    assert res.data == b"http://h/?a=hello+world&b=%2B"


def test_unicode_is_percent_encoded() -> None:
    res = canonicalize_for_signature(URL("http://h/?c=%C3%B6&a=%C3%A9"))
    assert res.query == "a=%C3%A9&c=%C3%B6"
    assert res.data == b"http://h/?a=%C3%A9&c=%C3%B6"


def test_empty_key() -> None:
    res = canonicalize_for_signature(URL("http://h/?=v&a=1"))
    assert res.query == "=v&a=1"
    assert res.canonical_items == (
        QueryItem("", "v", True),
        QueryItem("a", "1", True),
    )


def test_empty_value_and_bare_key_default_to_equals() -> None:
    bare = canonicalize_for_signature(URL("http://h/?a"))
    empty = canonicalize_for_signature(URL("http://h/?a="))
    assert bare.query == "a="
    assert empty.query == "a="
    assert bare.data == b"http://h/?a="
    assert empty.data == b"http://h/?a="


def test_distinguish_empty_keeps_bare_key() -> None:
    bare = canonicalize_for_signature(URL("http://h/?a"), distinguish_empty=True)
    empty = canonicalize_for_signature(URL("http://h/?a="), distinguish_empty=True)
    assert bare.query == "a"
    assert empty.query == "a="
    assert bare.data == b"http://h/?a"
    assert empty.data == b"http://h/?a="
    assert bare.items == (QueryItem("a", "", False),)
    assert empty.items == (QueryItem("a", "", True),)


def test_distinguish_empty_mixed() -> None:
    res = canonicalize_for_signature(
        URL("http://h/?a=1&b&c=&a=2"), distinguish_empty=True
    )
    assert res.query == "a=1&a=2&b&c="
    assert res.mapping == ((0, 0), (1, 2), (2, 3), (3, 1))


def test_keys_select_participating_items() -> None:
    res = canonicalize_for_signature(URL("http://h/?b=2&a=1&a=3"), keys=["a"])
    assert res.query == "a=1&a=3"
    assert res.mapping == ((1, 0), (2, 1))
    assert res.data == b"http://h/?a=1&a=3"
    assert res.canonical_items == (
        QueryItem("a", "1", True),
        QueryItem("a", "3", True),
    )


def test_keys_empty_means_no_items() -> None:
    res = canonicalize_for_signature(URL("http://h/?a=1&b=2"), keys=[])
    assert res.query == ""
    assert res.data == b"http://h/"
    assert res.mapping == ()
    assert res.canonical_items == ()


def test_keys_missing_key_is_ignored() -> None:
    res = canonicalize_for_signature(URL("http://h/?a=1"), keys=["zzz"])
    assert res.query == ""
    assert res.data == b"http://h/"


def test_original_url_is_not_modified() -> None:
    original = URL("http://example.com/?b=2&a=1&a=3")
    canonicalize_for_signature(original)
    assert str(original) == "http://example.com/?b=2&a=1&a=3"
    assert original.raw_query_string == "b=2&a=1&a=3"


def test_str_input() -> None:
    res = canonicalize_for_signature("http://example.com/?b=2&a=1")
    assert isinstance(res.url, URL)
    assert res.query == "a=1&b=2"
    assert res.data == b"http://example.com/?a=1&b=2"


def test_no_query() -> None:
    res = canonicalize_for_signature(URL("http://h/path"))
    assert res.query == ""
    assert res.data == b"http://h/path"
    assert res.items == ()
    assert res.mapping == ()


def test_fragment_is_preserved() -> None:
    res = canonicalize_for_signature(URL("http://h/p?b=2&a=1#frag"))
    assert res.data == b"http://h/p?a=1&b=2#frag"


def test_scheme_host_path_are_normalized() -> None:
    res = canonicalize_for_signature(URL("HTTP://Example.com:80/Path/?b=2&a=1"))
    # yarl normalizes scheme/host to lowercase and drops the default port.
    assert res.data == b"http://example.com/Path/?a=1&b=2"


def test_mapping_indices_align_with_items() -> None:
    res = canonicalize_for_signature(URL("http://h/?b=2&a=1&a=3&c=4"))
    for orig_idx, canon_idx in res.mapping:
        assert res.items[orig_idx] == res.canonical_items[canon_idx]
    # Every participating item appears exactly once.
    assert sorted(orig for orig, _ in res.mapping) == [0, 1, 2, 3]
    assert sorted(canon for _, canon in res.mapping) == [0, 1, 2, 3]


def test_no_dict_used_for_processing() -> None:
    # Duplicate keys must not collapse: a plain dict would lose one value.
    res = canonicalize_for_signature(URL("http://h/?a=1&a=2&a=3"))
    assert res.query == "a=1&a=2&a=3"
    assert len(res.canonical_items) == 3

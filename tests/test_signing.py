import dataclasses

import pytest

from yarl import URL, CanonicalQueryItem, canonical_signing_input

ACCEPTANCE_URL = "http://example.com/?b=2&a=1&a=3"


def test_acceptance_query_sorted_by_decoded_key() -> None:
    result = canonical_signing_input(URL(ACCEPTANCE_URL))
    assert result.canonical_query == "a=1&a=3&b=2"


def test_acceptance_index_map_points_at_correct_positions() -> None:
    result = canonical_signing_input(URL(ACCEPTANCE_URL))
    # Original fields: 0=b=2, 1=a=1, 2=a=3
    # Canonical order: a=1 (src 1), a=3 (src 2), b=2 (src 0)
    assert result.index_map == {0: 2, 1: 0, 2: 1}
    assert [item.source_index for item in result.query_items] == [1, 2, 0]


def test_acceptance_canonical_bytes() -> None:
    result = canonical_signing_input(URL(ACCEPTANCE_URL))
    assert result.canonical_bytes == b"http://example.com/?a=1&a=3&b=2"
    assert result.canonical_text == "http://example.com/?a=1&a=3&b=2"
    assert result.canonical_bytes == result.canonical_text.encode("utf-8")


def test_repeated_key_values_keep_their_order() -> None:
    result = canonical_signing_input(URL("http://h/?x=2&x=1&x=3"))
    assert result.canonical_query == "x=2&x=1&x=3"
    assert [item.value for item in result.query_items] == ["2", "1", "3"]


def test_stable_order_for_percent_encoding_equivalent_keys() -> None:
    # "%61" decodes to "a"; both keys compare equal and keep occurrence
    # order, including the order of their values.
    result = canonical_signing_input(URL("http://h/?%61=z&a=y"))
    assert result.canonical_query == "a=z&a=y"
    assert result.index_map == {0: 0, 1: 1}
    # Symmetric input gives the reverse (still stable) ordering.
    reverse = canonical_signing_input(URL("http://h/?a=y&%61=z"))
    assert reverse.canonical_query == "a=y&a=z"
    assert reverse.index_map == {0: 0, 1: 1}


def test_bare_key_and_empty_value_are_distinct() -> None:
    result = canonical_signing_input(URL("http://h/?a&a="))
    assert result.canonical_query == "a&a="
    bare, empty = result.query_items
    assert bare == CanonicalQueryItem("a", "", False, 0)
    assert empty == CanonicalQueryItem("a", "", True, 1)


def test_bare_key_and_empty_value_collapse_without_distinction() -> None:
    result = canonical_signing_input(
        URL("http://h/?a&a="), distinguish_blank_values=False
    )
    assert result.canonical_query == "a=&a="
    assert all(item.has_equals for item in result.query_items)


def test_empty_value_with_equals_is_preserved() -> None:
    result = canonical_signing_input(URL("http://h/?a="))
    assert result.canonical_query == "a="
    assert result.query_items[0].has_equals is True
    assert result.query_items[0].value == ""


def test_bare_key_is_rendered_without_equals() -> None:
    result = canonical_signing_input(URL("http://h/?a"))
    assert result.canonical_query == "a"
    assert result.query_items[0].has_equals is False


def test_plus_space_and_literal_plus_round_trip() -> None:
    # "+" in the source is a space; "%2B" is a literal plus. Both are
    # re-rendered canonically so the bytes never collide.
    result = canonical_signing_input(URL("http://h/?p=a+b&q=a%2Bb", encoded=True))
    assert result.canonical_query == "p=a+b&q=a%2Bb"
    # The two keys keep their values distinct in the items.
    assert [item.value for item in result.query_items] == ["a b", "a+b"]


def test_unicode_is_utf8_percent_encoded_in_bytes() -> None:
    result = canonical_signing_input(URL("http://h/?u=%C3%A9&k=键"))
    assert result.canonical_query == "k=%E9%94%AE&u=%C3%A9"
    assert result.canonical_bytes == (b"http://h/?k=%E9%94%AE&u=%C3%A9")


def test_empty_query_key() -> None:
    result = canonical_signing_input(URL("/p?=empty"))
    assert result.canonical_query == "=empty"
    assert result.canonical_bytes == b"/p?=empty"


def test_empty_query_string_has_no_question_mark() -> None:
    result = canonical_signing_input(URL("http://h/path"))
    assert result.canonical_query == ""
    assert result.canonical_bytes == b"http://h/path"
    assert result.query_items == ()
    assert result.index_map == {}


def test_include_iterable_filters_keys_and_reindexes() -> None:
    result = canonical_signing_input(URL("http://h/?sig=x&b=2&a=1"), include=("a", "b"))
    assert result.canonical_query == "a=1&b=2"
    # Source fields 1 (b=2) and 2 (a=1) survive in canonical order.
    assert result.index_map == {1: 1, 2: 0}
    assert [item.source_index for item in result.query_items] == [2, 1]


def test_include_callable_selects_keys() -> None:
    result = canonical_signing_input(
        URL("http://h/?keep=1&drop=2"), include=lambda key: key == "keep"
    )
    assert result.canonical_query == "keep=1"


def test_include_affects_every_occurrence_of_repeated_key() -> None:
    result = canonical_signing_input(URL("http://h/?a=1&b=2&a=3"), include=("a",))
    assert result.canonical_query == "a=1&a=3"
    assert result.index_map == {0: 0, 2: 1}


def test_include_with_decoded_key_matches_encoded_occurrence() -> None:
    result = canonical_signing_input(URL("http://h/?%61=1&b=2"), include=("a",))
    assert result.canonical_query == "a=1"


def test_include_none_selects_everything() -> None:
    result = canonical_signing_input(URL("http://h/?b=2&a=1"), include=None)
    assert result.canonical_query == "a=1&b=2"


def test_include_string_is_rejected() -> None:
    with pytest.raises(TypeError):
        canonical_signing_input(URL("http://h/?a=1"), include="a")


def test_non_url_is_rejected() -> None:
    not_a_url: object = "http://h/?a=1"
    with pytest.raises(TypeError):
        canonical_signing_input(not_a_url)  # type: ignore[arg-type]


def test_original_url_is_not_modified() -> None:
    url = URL(ACCEPTANCE_URL)
    canonical_signing_input(url)
    assert str(url) == ACCEPTANCE_URL
    assert url.raw_query_string == "b=2&a=1&a=3"


def test_scheme_relative_url_omits_scheme_colon() -> None:
    result = canonical_signing_input(URL("//h/p?b=2&a=1"))
    assert result.canonical_bytes == b"//h/p?a=1&b=2"


def test_relative_url_omits_authority() -> None:
    result = canonical_signing_input(URL("/a/b?z=9"))
    assert result.canonical_bytes == b"/a/b?z=9"


def test_opaque_scheme_url() -> None:
    result = canonical_signing_input(URL("mailto:a@b?subject=hi"))
    assert result.canonical_bytes == b"mailto:a@b?subject=hi"


def test_empty_fields_keep_source_positions() -> None:
    result = canonical_signing_input(URL("http://h/?a=1&&b=2"))
    assert result.canonical_query == "a=1&b=2"
    assert {item.source_index for item in result.query_items} == {0, 2}
    assert result.index_map == {0: 0, 2: 1}


def test_non_utf8_source_query_can_be_canonicalized_as_utf8_output() -> None:
    # %E9 is the Latin-1 encoding of "é"; decode with latin-1 then
    # re-encode canonically as UTF-8.
    result = canonical_signing_input(
        URL("http://h/?k=%E9", encoded=True), encoding="latin-1"
    )
    assert result.canonical_query == "k=%C3%A9"
    assert result.canonical_bytes == b"http://h/?k=%C3%A9"


def test_encoded_chars_requoted_to_canonical_form() -> None:
    # Reserved-but-allowed in query characters are left as yarl stores
    # them; re-rendering a decoded key goes through the query quoter.
    result = canonical_signing_input(
        URL("http://h/?a%3Db=1"), include=lambda key: key == "a=b"
    )
    assert result.canonical_query == "a%3Db=1"


def test_result_is_value_object() -> None:
    result = canonical_signing_input(URL(ACCEPTANCE_URL))
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.canonical_query = "x"
    assert result == canonical_signing_input(URL(ACCEPTANCE_URL))

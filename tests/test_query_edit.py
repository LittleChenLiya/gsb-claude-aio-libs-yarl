import pytest

from yarl import parse_raw_query, plan_query_edit


def test_second_occurrence_keeps_unselected_escape_case_and_fragment() -> None:
    url = "http://example.com/?a=%2f&a=2#frag%2fment"
    plan = plan_query_edit(url, "a", 3, occurrence=1)
    assert plan is not None
    # Only the second "a" value changes; "%2f" keeps its lowercase spelling
    # and the fragment keeps its raw bytes.
    assert plan.apply() == "http://example.com/?a=%2f&a=3#frag%2fment"


def test_first_occurrence_replaces_raw_value_span() -> None:
    url = "http://example.com/?a=%2f&a=2"
    plan = plan_query_edit(url, "a", "x", occurrence=0)
    assert plan is not None
    assert plan.apply() == "http://example.com/?a=x&a=2"


def test_range_map_is_counted_in_original_bytes() -> None:
    url = "http://example.com/?a=%2f&a=2#frag"
    plan = plan_query_edit(url, "a", 3, occurrence=1)
    assert plan is not None
    start = url.index("2", url.index("&a="))
    assert plan.range_map() == {"a[1]": (start, start + 1)}
    (edit,) = plan.edits
    assert edit.span == (start, start + 1)
    assert url[edit.start : edit.end] == "2"
    assert edit.replacement == "3"


def test_duplicate_keys_are_addressed_by_occurrence_not_collapsed() -> None:
    url = "http://h/?a=1&a=2&a=3"
    plan = plan_query_edit(url, "a", "x", occurrence=2)
    assert plan is not None
    assert plan.apply() == "http://h/?a=1&a=2&a=x"
    # There is no fourth occurrence.
    assert plan_query_edit(url, "a", "x", occurrence=3) is None


def test_decoded_key_matching() -> None:
    # "+" and percent-escapes are decoded for the key comparison only;
    # the raw key spelling is preserved in the output.
    plan = plan_query_edit("http://h/?a+b=1", "a b", 2)
    assert plan is not None
    assert plan.apply() == "http://h/?a+b=2"
    plan = plan_query_edit("http://h/?%61=1", "a", 2)
    assert plan is not None
    assert plan.apply() == "http://h/?%61=2"


def test_empty_value_is_replaced() -> None:
    plan = plan_query_edit("http://h/?a=&b=2", "a", 1)
    assert plan is not None
    assert plan.apply() == "http://h/?a=1&b=2"


def test_bare_key_gets_value_inserted() -> None:
    url = "http://h/?a&b=2"
    plan = plan_query_edit(url, "a", 1)
    assert plan is not None
    (edit,) = plan.edits
    # A bare key has no value span: the edit is a zero-width insertion.
    assert edit.span == (url.index("&b"),) * 2
    assert edit.replacement == "=1"
    assert plan.apply() == "http://h/?a=1&b=2"


def test_empty_value_and_bare_key_are_not_conflated() -> None:
    url = "http://h/?a=&a"
    empty = plan_query_edit(url, "a", 1, occurrence=0)
    bare = plan_query_edit(url, "a", 1, occurrence=1)
    assert empty is not None and bare is not None
    assert empty.apply() == "http://h/?a=1&a"
    assert bare.apply() == "http://h/?a=&a=1"


def test_empty_items_are_preserved() -> None:
    url = "http://h/?a=1&&b=2&"
    plan = plan_query_edit(url, "b", 3)
    assert plan is not None
    assert plan.apply() == "http://h/?a=1&&b=3&"


def test_empty_query_is_distinguished_from_no_query() -> None:
    empty = parse_raw_query("http://h/?")
    assert empty.has_query
    assert empty.span == (10, 10)
    missing = parse_raw_query("http://h/")
    assert not missing.has_query
    assert missing.span is None
    # Neither one yields an edit plan.
    assert plan_query_edit("http://h/?", "a", 1) is None
    assert plan_query_edit("http://h/", "a", 1) is None


def test_fragment_span_and_question_mark_inside_fragment() -> None:
    raw = parse_raw_query("http://h/#frag?a=1")
    assert raw.span is None
    assert raw.fragment_span == (10, 18)
    assert plan_query_edit("http://h/#frag?a=1", "a", 2) is None


def test_invalid_escape_in_fragment_does_not_block_and_stays_raw() -> None:
    url = "http://h/?a=1#%zz"
    plan = plan_query_edit(url, "a", 2)
    assert plan is not None
    assert plan.apply() == "http://h/?a=2#%zz"


@pytest.mark.parametrize(
    "url",
    [
        "http://h/?a=%zz",
        "http://h/?a=%",
        "http://h/?a=%1",
        "http://h/?a=1&b=%2g",
        "http://h/?a=1%",
    ],
)
def test_invalid_escape_in_query_plans_nothing(url: str) -> None:
    assert plan_query_edit(url, "a", 1) is None


def test_baseline_change_refuses_to_modify() -> None:
    plan = plan_query_edit("http://h/?a=1", "a", 2)
    assert plan is not None
    with pytest.raises(ValueError, match="bound to a different original text"):
        plan.apply("http://h/?a=9")
    # The bound baseline still applies cleanly.
    assert plan.apply() == "http://h/?a=2"
    assert plan.apply("http://h/?a=1") == "http://h/?a=2"


def test_new_value_uses_yarl_query_encoding() -> None:
    plan = plan_query_edit("http://h/?a=1", "a", "x & y/z?")
    assert plan is not None
    # QUERY_PART_QUOTER rules: space -> "+", "&" -> "%26", "/" and "?" safe.
    assert plan.apply() == "http://h/?a=x+%26+y/z?"


def test_new_value_from_non_str_types() -> None:
    plan = plan_query_edit("http://h/?a=1", "a", 2.5)
    assert plan is not None
    assert plan.apply() == "http://h/?a=2.5"


def test_missing_key_plans_nothing() -> None:
    assert plan_query_edit("http://h/?a=1", "b", 2) is None


def test_negative_occurrence_is_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        plan_query_edit("http://h/?a=1", "a", 2, occurrence=-1)


def test_plan_is_bound_to_the_original_text() -> None:
    url = "http://h/?a=1"
    plan = plan_query_edit(url, "a", 2)
    assert plan is not None
    assert plan.original == url
    assert repr(plan).startswith("<QueryEditPlan edits=(QueryEdit(")

"""Tests for yarl.relative_reference().

Run with::

    python -m pytest tests/test_relative_reference.py -o addopts= -q
"""

import pytest

from yarl import URL, relative_reference


def test_same_directory_file_change_is_bare_name() -> None:
    base = URL("http://example.com/a/b/page.html")
    target = URL("http://example.com/a/b/other.html")
    assert relative_reference(base, target) == "other.html"


def test_query_only_change_is_query_reference() -> None:
    base = URL("http://example.com/a/b?x=1")
    target = URL("http://example.com/a/b?x=2")
    assert relative_reference(base, target) == "?x=2"


def test_fragment_only_change_is_fragment_reference() -> None:
    base = URL("http://example.com/a/b?x=1")
    target = URL("http://example.com/a/b?x=1#sec")
    assert relative_reference(base, target) == "#sec"


def test_empty_reference_boundary() -> None:
    # The empty reference resolves to the base without its fragment.
    base = URL("http://example.com/a?x#f")
    assert relative_reference(base, URL("http://example.com/a?x")) == ""
    # A target that keeps the fragment of the base needs it spelled out.
    assert relative_reference(base, base) == "#f"
    # A base without a fragment is its own empty reference.
    plain = URL("http://example.com/a?x")
    assert relative_reference(plain, plain) == ""


def test_encoded_slash_segment_roundtrip() -> None:
    base = URL("http://example.com/a/")
    target = URL("http://example.com/a/b%2Fc")
    ref = relative_reference(base, target)
    assert ref == "b%2Fc"
    # The encoded slash is not unpacked into a separator by the round trip.
    joined = base.join(URL(ref))
    assert joined == target
    assert joined.raw_path == "/a/b%2Fc"
    assert joined.raw_parts == ("/", "a", "b%2Fc")


def test_encoded_slash_in_base_directory() -> None:
    base = URL("http://example.com/a/b%2Fc/d")
    target = URL("http://example.com/a/b%2Fc/e")
    assert relative_reference(base, target) == "e"


def test_cross_host_is_absolute_not_faked_relative() -> None:
    base = URL("http://example.com/a/b/c")
    target = URL("http://static.example.com/a/b/c")
    ref = relative_reference(base, target)
    assert ref == "http://static.example.com/a/b/c"
    assert not ref.startswith(".")


def test_cross_scheme_is_absolute() -> None:
    base = URL("http://example.com/a/b")
    target = URL("https://example.com/a/b")
    assert relative_reference(base, target) == "https://example.com/a/b"


def test_cross_port_is_absolute() -> None:
    base = URL("http://example.com/a/b")
    target = URL("http://example.com:8080/a/b")
    assert relative_reference(base, target) == "http://example.com:8080/a/b"


def test_parent_directory() -> None:
    base = URL("http://example.com/a/b/c")
    target = URL("http://example.com/a/x")
    assert relative_reference(base, target) == "../x"


def test_subdirectory() -> None:
    base = URL("http://example.com/a/b/c")
    target = URL("http://example.com/a/b/c/d/e")
    assert relative_reference(base, target) == "c/d/e"


def test_root_absolute_shorter_than_parent_chain() -> None:
    base = URL("http://example.com/a/b/c/d/e")
    target = URL("http://example.com/x")
    assert relative_reference(base, target) == "/x"


def test_target_is_directory_of_base() -> None:
    base = URL("http://example.com/a/b/c")
    target = URL("http://example.com/a/b/")
    assert relative_reference(base, target) == "./"


def test_first_segment_colon_is_hidden() -> None:
    base = URL("http://example.com/a/b")
    target = URL("http://example.com/a/c:d")
    assert relative_reference(base, target) == "./c:d"


def test_dropped_query_needs_path_reference() -> None:
    # A relative reference without a query inherits the base query,
    # so clearing it requires a path reference.
    base = URL("http://example.com/a/b?x=1")
    target = URL("http://example.com/a/b")
    assert relative_reference(base, target) == "/a/b"


def test_type_error() -> None:
    with pytest.raises(TypeError):
        relative_reference("http://example.com/", URL("http://example.com/"))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("base", "target"),
    [
        ("http://example.com/a/b/page.html", "http://example.com/a/b/other.html"),
        ("http://example.com/a/b?x=1", "http://example.com/a/b?x=2"),
        ("http://example.com/a/", "http://example.com/a/b%2Fc"),
        ("http://example.com/a/b/c", "http://static.example.com/a/b/c"),
        ("http://example.com/a/b/c", "http://example.com/a/b/c"),
        ("http://example.com/a/b/c", "http://example.com/a/b/"),
        ("http://example.com/a/b/c", "http://example.com/a/x?y=1#f"),
        ("http://example.com/a/b", "http://example.com/a//c"),
        ("http://example.com/a/b", "http://example.com/a/c:d"),
        ("http://example.com/", "http://example.com/a"),
        ("http://example.com/a/b%2Fc/d", "http://example.com/a/b%2Fc/e%2Ff"),
    ],
)
def test_join_roundtrip(base: str, target: str) -> None:
    base_url, target_url = URL(base), URL(target)
    ref = relative_reference(base_url, target_url)
    assert base_url.join(URL(ref)) == target_url

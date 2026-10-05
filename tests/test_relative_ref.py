"""Tests for the explicit relative reference generator.

``relative_ref(base, target)`` returns the shortest legal reference that
restores *target* when joined with *base*. Every candidate is verified
with :meth:`yarl.URL.join`, and the comparison preserves the target's
canonical identity. No network access is performed.
"""

import socket

import pytest

from yarl import URL, relative_ref

# The four URL examples from the acceptance criteria:
#
# 1. A same-directory file change gives just the relative filename.
# 2. A query-only change gives just the query reference.
# 3. A percent-encoded slash round-trips unchanged.
# 4. A cross-host target is not given a fabricated relative path.
FOUR_URL_EXAMPLES = (
    (
        "http://example.com/a/b/c.html",
        "http://example.com/a/b/d.html",
        "d.html",
    ),
    (
        "http://example.com/a/b/c.html",
        "http://example.com/a/b/c.html?q=1",
        "?q=1",
    ),
    (
        "http://example.com/a%2Fb/c/d.html",
        "http://example.com/a%2Fb/c/e.html",
        "e.html",
    ),
    (
        "http://example.com/a/b/c.html",
        "http://other.com/a/b/d.html",
        "http://other.com/a/b/d.html",
    ),
)


@pytest.mark.parametrize("base,target,expected", FOUR_URL_EXAMPLES)
def test_four_url_examples(base: str, target: str, expected: str) -> None:
    ref = relative_ref(URL(base), URL(target))
    assert str(ref) == expected
    # The candidate must restore the target through the original join().
    assert URL(base).join(ref) == URL(target)


def test_same_directory_file_change_gives_relative_filename() -> None:
    base = URL("http://example.com/a/b/c.html")
    assert str(relative_ref(base, base.with_name("d.html"))) == "d.html"


def test_query_only_change_gives_query_reference() -> None:
    base = URL("http://example.com/a/b/c.html")
    assert str(relative_ref(base, base.with_query("q=1"))) == "?q=1"


def test_fragment_only_change_gives_fragment_reference() -> None:
    base = URL("http://example.com/a/b/c.html")
    assert str(relative_ref(base, base.with_fragment("sec"))) == "#sec"


def test_encoded_slash_round_trips_unchanged() -> None:
    base = URL("http://example.com/a%2Fb/c/d.html")
    target = URL("http://example.com/a%2Fb/c/e.html")
    ref = relative_ref(base, target)
    assert str(ref) == "e.html"
    joined = base.join(ref)
    assert joined == target
    # The encoded slash must stay inside its segment, not become a separator.
    assert joined.raw_path == target.raw_path
    assert "%2F" in joined.raw_path


def test_cross_host_returns_absolute_reference() -> None:
    base = URL("http://example.com/a/b/c.html")
    target = URL("http://other.com/a/b/d.html")
    ref = relative_ref(base, target)
    assert str(ref) == "http://other.com/a/b/d.html"
    assert base.join(ref) == target


def test_cross_scheme_returns_absolute_reference() -> None:
    base = URL("http://example.com/a/b/c.html")
    target = URL("https://example.com/a/b/d.html")
    assert str(relative_ref(base, target)) == "https://example.com/a/b/d.html"


def test_cross_port_returns_absolute_reference() -> None:
    base = URL("http://example.com:8080/a/b/c.html")
    target = URL("http://example.com/a/b/d.html")
    assert str(relative_ref(base, target)) == "http://example.com/a/b/d.html"


def test_same_origin_different_userinfo_gives_network_path() -> None:
    base = URL("http://example.com/a/b/c.html")
    target = URL("http://user@example.com/a/b/d.html")
    ref = relative_ref(base, target)
    assert str(ref) == "//user@example.com/a/b/d.html"
    assert base.join(ref) == target


def test_empty_reference_boundary() -> None:
    # An empty reference restores the target when nothing is missing.
    base = URL("http://example.com/a/b/c.html")
    assert str(relative_ref(base, base)) == ""
    assert base.join(relative_ref(base, base)) == base


def test_empty_reference_drops_fragment() -> None:
    # join() drops the fragment of an empty reference, so a target with a
    # fragment needs a fragment-only reference, not the empty one.
    base = URL("http://example.com/a/b/c.html#sec")
    assert str(relative_ref(base, base)) == "#sec"


def test_target_equal_to_base_with_query_and_fragment() -> None:
    base = URL("http://example.com/a/b/c.html?q=1#f")
    assert str(relative_ref(base, base)) == "#f"


def test_empty_query_marker() -> None:
    base = URL("http://example.com/a/b/c.html")
    assert str(relative_ref(base, URL("http://example.com/a/b/c.html?"))) == "?"


def test_empty_fragment_marker() -> None:
    base = URL("http://example.com/a/b/c.html")
    assert str(relative_ref(base, URL("http://example.com/a/b/c.html#"))) == "#"


def test_empty_query_and_fragment_marker() -> None:
    base = URL("http://example.com/a/b/c.html")
    assert str(relative_ref(base, URL("http://example.com/a/b/c.html?#"))) == "?#"


def test_target_without_query_clears_it() -> None:
    # A relative reference cannot clear the query; the absolute reference
    # is the shortest one that restores a query-less target.
    base = URL("http://example.com/a/b/c.html?q=1")
    target = URL("http://example.com/a/b/c.html")
    ref = relative_ref(base, target)
    assert base.join(ref) == target


def test_directory_target() -> None:
    base = URL("http://example.com/a/b/c.html")
    assert str(relative_ref(base, URL("http://example.com/a/b/"))) == "./"


def test_ancestor_file_target() -> None:
    base = URL("http://example.com/a/b/c.html")
    assert str(relative_ref(base, URL("http://example.com/a/b"))) == "../b"


def test_root_target() -> None:
    base = URL("http://example.com/a/b/c.html")
    assert str(relative_ref(base, URL("http://example.com/"))) == "/"


def test_cross_directory_uses_shortest_reference() -> None:
    # The absolute-path reference is shorter than the relative-path one.
    base = URL("http://example.com/a/b/c/d.html")
    target = URL("http://example.com/x/y.html")
    assert str(relative_ref(base, target)) == "/x/y.html"


def test_subdirectory_target() -> None:
    base = URL("http://example.com/a/b/c.html")
    target = URL("http://example.com/a/b/d/e.html")
    assert str(relative_ref(base, target)) == "d/e.html"


def test_relative_base() -> None:
    base = URL("a/b/c.html")
    assert str(relative_ref(base, URL("a/b/d.html"))) == "d.html"
    assert str(relative_ref(base, URL("a/x/d.html"))) == "../x/d.html"


def test_rfc_mode() -> None:
    base = URL("http://example.com/a/b/c.html", mode="rfc")
    target = URL("http://example.com/a/b/d.html", mode="rfc")
    assert str(relative_ref(base, target)) == "d.html"
    other = URL("http://other.com/a/b/d.html", mode="rfc")
    assert str(relative_ref(base, other)) == "http://other.com/a/b/d.html"


def test_method_form() -> None:
    base = URL("http://example.com/a/b/c.html")
    assert str(base.relative_ref(base.with_name("d.html"))) == "d.html"


def test_type_error_on_non_url() -> None:
    with pytest.raises(TypeError):
        relative_ref(
            "http://example.com/a/b/c.html", URL("http://example.com/a/b/d.html")
        )
    with pytest.raises(TypeError):
        relative_ref(
            URL("http://example.com/a/b/c.html"), "http://example.com/a/b/d.html"
        )


def test_no_network_access(monkeypatch: pytest.MonkeyPatch) -> None:
    # The generator must not touch the network; a blocked socket is enough
    # to prove it never tries.
    def _blocked(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "socket", _blocked)
    base = URL("http://example.com/a/b/c.html")
    target = URL("http://other.com/a/b/d.html")
    assert str(relative_ref(base, target)) == "http://other.com/a/b/d.html"

"""Tests for the Genie Space selection helper."""

from scripts.select_genie_spaces import parse_selection, render_var_argument


def test_parse_selection_supports_comma_separated_indices():
    spaces = [
        {"space_id": "space-a", "title": "A"},
        {"space_id": "space-b", "title": "B"},
        {"space_id": "space-c", "title": "C"},
    ]

    selected = parse_selection("1,3", spaces)

    assert selected == ["space-a", "space-c"]


def test_parse_selection_supports_literal_space_ids():
    spaces = [{"space_id": "space-a", "title": "A"}]

    selected = parse_selection("space-a,space-b", spaces)

    assert selected == ["space-a", "space-b"]


def test_render_var_argument_outputs_bundle_flag():
    assert (
        render_var_argument(["space-a", "space-b"])
        == "--var='genie_space_ids=space-a,space-b'"
    )


# ── list_genie_spaces ──


class _Space:
    def __init__(self, space_id, title=None):
        self.space_id = space_id
        self.title = title


class _Response:
    """Stand-in for GenieListSpacesResponse: a wrapper, not an iterable."""

    def __init__(self, spaces, next_page_token=None):
        self.spaces = spaces
        self.next_page_token = next_page_token


def test_list_genie_spaces_reads_the_spaces_attribute(monkeypatch):
    """Regression: the response object is not iterable.

    `for space in w.genie.list_spaces()` raised
    TypeError: 'GenieListSpacesResponse' object is not iterable, so this helper
    failed for every user.
    """
    import scripts.select_genie_spaces as mod

    class _Genie:
        def list_spaces(self, page_token=None):
            return _Response([_Space("space-a", "A"), _Space("space-b", "B")])

    class _Client:
        genie = _Genie()

    monkeypatch.setattr(mod, "WorkspaceClient", lambda **kw: _Client())

    spaces = mod.list_genie_spaces()

    assert spaces == [
        {"space_id": "space-a", "title": "A"},
        {"space_id": "space-b", "title": "B"},
    ]


def test_list_genie_spaces_follows_pagination(monkeypatch):
    """A workspace with more spaces than one page must not be silently truncated."""
    import scripts.select_genie_spaces as mod

    pages = [
        _Response([_Space("space-a", "A")], next_page_token="tok-2"),
        _Response([_Space("space-b", "B")], next_page_token=None),
    ]
    seen_tokens = []

    class _Genie:
        def list_spaces(self, page_token=None):
            seen_tokens.append(page_token)
            return pages[len(seen_tokens) - 1]

    class _Client:
        genie = _Genie()

    monkeypatch.setattr(mod, "WorkspaceClient", lambda **kw: _Client())

    spaces = mod.list_genie_spaces()

    assert [s["space_id"] for s in spaces] == ["space-a", "space-b"]
    assert seen_tokens == [None, "tok-2"]


def test_list_genie_spaces_falls_back_to_id_when_untitled(monkeypatch):
    import scripts.select_genie_spaces as mod

    class _Genie:
        def list_spaces(self, page_token=None):
            return _Response([_Space("space-a", None)])

    class _Client:
        genie = _Genie()

    monkeypatch.setattr(mod, "WorkspaceClient", lambda **kw: _Client())

    assert mod.list_genie_spaces() == [{"space_id": "space-a", "title": "space-a"}]

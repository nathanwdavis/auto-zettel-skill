"""fetch_source.py: captures are mechanical, immutable, and honest about shells (A11)."""

from __future__ import annotations

import json

import pytest
import yaml

from conftest import REF_KEY, load, make_pdf, run_script
from zettel_lib import http
from zettel_lib.repo import ContentRepo

import fetch_source

URL = "https://example.org/paper"
PDF = make_pdf("A fetched paper")
FULL_HTML = "<html><body><h1>Article</h1>" + "<p>" + ("Real prose about slip boxes. " * 40) + "</p></body></html>"
SHELL_HTML = '<html><head><script src="app.js"></script></head><body><div id="root"></div><noscript>Please enable JavaScript</noscript></body></html>'


def uncaptured(repo):
    """The fixture reference with its capture removed, so it needs one."""
    note = load(repo, f"reference/{REF_KEY}.md")
    (repo / note.meta["raw_capture"]).unlink()
    note.meta["raw_capture"] = ""
    note.meta["verification"] = {"method": "", "source": "", "verified": False, "date": ""}
    note.save()
    return note


def set_renderer(repo, renderer):
    cfg = yaml.safe_load((repo / "config.yml").read_text())
    cfg["fetch"]["renderer"] = renderer
    (repo / "config.yml").write_text(yaml.safe_dump(cfg), encoding="utf-8")


def test_pdf_is_captured_verbatim_and_named_from_the_reference(clean_repo):
    uncaptured(clean_repo)
    transport = http.CassetteTransport({URL: http.Response(200, "", {"Content-Type": "application/pdf"}, PDF)})
    result = fetch_source.fetch(ContentRepo(clean_repo), REF_KEY, URL, transport=transport)
    assert result["capture"] == f"raw/{REF_KEY.rsplit('--', 1)[1]}-{REF_KEY.rsplit('--', 1)[0]}.pdf"
    assert (clean_repo / result["capture"]).read_bytes() == PDF
    assert load(clean_repo, f"reference/{REF_KEY}.md").meta["raw_capture"] == result["capture"]
    assert "fetch_source: " in (clean_repo / "log.md").read_text()
    assert run_script("verify_refs.py", clean_repo, "--offline").returncode == 0
    assert run_script("lint_citations.py", clean_repo).returncode == 0


def test_full_html_is_saved_as_html_without_a_renderer(clean_repo):
    uncaptured(clean_repo)
    transport = http.CassetteTransport({URL: http.Response(200, FULL_HTML, {"Content-Type": "text/html"})})
    result = fetch_source.fetch(ContentRepo(clean_repo), REF_KEY, URL, transport=transport)
    assert result["capture"].endswith(".html") and result["renderer"] == "none"
    assert transport.calls == [URL]


def test_shell_page_with_no_renderer_fails_and_files_an_inbox_entry(clean_repo):
    uncaptured(clean_repo)
    cassette = http.CassetteTransport({URL: http.Response(200, SHELL_HTML, {"Content-Type": "text/html"})})
    with pytest.raises(fetch_source.FetchError, match="empty shell"):
        fetch_source.fetch(ContentRepo(clean_repo), REF_KEY, URL, transport=cassette)
    assert not list((clean_repo / "raw").glob("*.html")), "a shell is never saved as the source"


def test_shell_page_is_rendered_through_jina_when_enabled(clean_repo):
    uncaptured(clean_repo)
    set_renderer(clean_repo, "jina")
    transport = http.CassetteTransport({
        "r.jina.ai": http.Response(200, "# Article\n\nRendered prose.", {"Content-Type": "text/plain"}),
        URL: http.Response(200, SHELL_HTML, {"Content-Type": "text/html"}),
    })
    result = fetch_source.fetch(ContentRepo(clean_repo), REF_KEY, URL, transport=transport)
    assert result["renderer"] == "jina" and result["capture"].endswith(".md")
    assert (clean_repo / result["capture"]).read_text() == "# Article\n\nRendered prose."
    assert transport.calls == [URL, f"https://r.jina.ai/{URL}"]


def test_firecrawl_renderer_posts_with_the_api_key(clean_repo):
    uncaptured(clean_repo)
    get = http.CassetteTransport({URL: http.Response(200, SHELL_HTML, {"Content-Type": "text/html"})})
    post = http.CassetteTransport({"api.firecrawl.dev": http.Response(
        200, json.dumps({"success": True, "data": {"markdown": "# Rendered by firecrawl"}}), {})})
    result = fetch_source.fetch(ContentRepo(clean_repo), REF_KEY, URL, renderer="firecrawl",
                                transport=get, post_transport=post, env={"FIRECRAWL_API_KEY": "k"})
    assert result["renderer"] == "firecrawl"
    assert post.bodies == [{"url": URL, "formats": ["markdown"]}]
    assert (clean_repo / result["capture"]).read_text().startswith("# Rendered by firecrawl")


def test_firecrawl_without_a_key_is_a_clear_failure(clean_repo):
    uncaptured(clean_repo)
    get = http.CassetteTransport({URL: http.Response(200, SHELL_HTML, {"Content-Type": "text/html"})})
    with pytest.raises(fetch_source.FetchError, match="FIRECRAWL_API_KEY"):
        fetch_source.fetch(ContentRepo(clean_repo), REF_KEY, URL, renderer="firecrawl",
                           transport=get, env={})


def test_author_sharing_sites_are_leads_not_sources(clean_repo):
    note = uncaptured(clean_repo)
    note.meta["verification"]["open_access"] = "https://repo.example.edu/paper.pdf"
    note.save()
    transport = http.CassetteTransport({})
    with pytest.raises(fetch_source.FetchError, match="lead, not a source") as info:
        fetch_source.fetch(ContentRepo(clean_repo), REF_KEY,
                           "https://www.academia.edu/12345/Some_Paper", transport=transport)
    assert "repo.example.edu/paper.pdf" in str(info.value)
    assert transport.calls == [], "never even fetched"


def test_existing_capture_is_never_overwritten(clean_repo):
    from zettel_lib.repo import ContentRepoError
    transport = http.CassetteTransport({URL: http.Response(200, "", {"Content-Type": "application/pdf"}, PDF)})
    with pytest.raises(ContentRepoError, match="immutable"):
        fetch_source.fetch(ContentRepo(clean_repo), REF_KEY, URL, transport=transport)


def test_cli_failure_exits_one_and_files_the_handoff(clean_repo):
    uncaptured(clean_repo)
    result = run_script("fetch_source.py", clean_repo, "--ref", REF_KEY,
                        "--url", "https://www.researchgate.net/publication/1")
    assert result.returncode == 1
    inbox = (clean_repo / "INBOX.md").read_text()
    assert f"Source needed: {REF_KEY}" in inbox and "drop/" in inbox
    assert run_script("fetch_source.py", clean_repo, "--help").returncode == 0

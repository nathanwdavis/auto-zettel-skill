"""fetch_remote.py: Mode-B fetching for public and private repos (FR-23, AC-31)."""

from __future__ import annotations

import json
import subprocess
import sys

from conftest import SCRIPTS, build_clean_repo
from zettel_lib import http

import fetch_remote


def manifest_for(tmp_path):
    repo = build_clean_repo(tmp_path / "kb")
    return (repo / "manifest.json").read_text(encoding="utf-8")


def run_cli(tmp_path, *args, env_token=None):
    import os
    env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_TOKEN", "GH_TOKEN")}
    if env_token:
        env["GITHUB_TOKEN"] = env_token
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "fetch_remote.py"), *args],
        capture_output=True, text=True, env=env)


def test_public_manifest_and_note_fetch(tmp_path, monkeypatch):
    manifest_text = manifest_for(tmp_path)
    key = json.loads(manifest_text)["notes"][0]["key"]
    transport = http.CassetteTransport({
        "manifest.json": http.Response(200, manifest_text, {}),
        "raw.githubusercontent.com": http.Response(200, "note body", {}),
    })
    monkeypatch.setattr(http, "requests_transport", transport)
    out = tmp_path / "out"
    rc = fetch_remote.main(["--manifest-url",
                            "https://raw.githubusercontent.com/example/kb-fixture/main/manifest.json",
                            "--out", str(out), "--keys", key])
    assert rc == 0
    assert (out / "manifest.json").exists()
    fetched = list(out.rglob("*.md"))
    assert fetched and fetched[0].read_text(encoding="utf-8") == "note body"


def test_owner_repo_falls_back_to_api_with_token(tmp_path, monkeypatch):
    manifest_text = manifest_for(tmp_path)
    transport = http.CassetteTransport({
        # raw 404s (private repo); the API succeeds
        "raw.githubusercontent.com": http.Response(404, "Not Found", {}),
        "api.github.com": http.Response(200, manifest_text, {}),
    })
    monkeypatch.setattr(http, "requests_transport", transport)
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    out = tmp_path / "out"
    rc = fetch_remote.main(["--owner", "example", "--repo", "kb-fixture",
                            "--out", str(out)])
    assert rc == 0
    api_calls = [u for u in transport.calls if "api.github.com" in u]
    assert api_calls, "expected the API fallback to be used"


def test_api_base64_envelope_is_decoded(tmp_path, monkeypatch):
    import base64
    manifest_text = manifest_for(tmp_path)
    envelope = json.dumps({
        "encoding": "base64",
        "content": base64.b64encode(manifest_text.encode()).decode(),
    })
    transport = http.CassetteTransport({
        "raw.githubusercontent.com": http.Response(404, "", {}),
        "api.github.com": http.Response(200, envelope, {}),
    })
    monkeypatch.setattr(http, "requests_transport", transport)
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    out = tmp_path / "out"
    rc = fetch_remote.main(["--owner", "example", "--repo", "kb-fixture",
                            "--out", str(out)])
    assert rc == 0
    assert json.loads((out / "manifest.json").read_text(encoding="utf-8"))["note_count"] == 4


def test_private_without_token_fails_with_actionable_message(tmp_path, monkeypatch, capsys):
    transport = http.CassetteTransport({"": http.Response(404, "", {})})
    monkeypatch.setattr(http, "requests_transport", transport)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    rc = fetch_remote.main(["--owner", "example", "--repo", "kb-private",
                            "--out", str(tmp_path / "out")])
    assert rc == 1
    err = capsys.readouterr().err
    assert "GITHUB_TOKEN" in err and "GitHub MCP" in err


def test_unknown_key_fails(tmp_path, monkeypatch):
    manifest_text = manifest_for(tmp_path)
    transport = http.CassetteTransport({
        "manifest.json": http.Response(200, manifest_text, {}),
    })
    monkeypatch.setattr(http, "requests_transport", transport)
    rc = fetch_remote.main(["--manifest-url",
                            "https://raw.githubusercontent.com/e/r/main/manifest.json",
                            "--out", str(tmp_path / "out"),
                            "--keys", "ghost-note--209901010000"])
    assert rc == 1


def test_help_and_arg_validation(tmp_path):
    ok = run_cli(tmp_path, "--help")
    assert ok.returncode == 0
    bad = run_cli(tmp_path, "--owner", "example")
    assert bad.returncode != 0
    assert "--repo" in bad.stderr

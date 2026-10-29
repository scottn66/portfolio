"""Console script. Link checks are stubbed here so this module never uses the network."""

from __future__ import annotations

import json
from importlib.metadata import version
from pathlib import Path

import pytest

from portfolio_qc.cli import main
from portfolio_qc.links import DEFAULT_MAX_PAGES, LinkCheck, LinkReport


def _report(*results: LinkCheck) -> LinkReport:
    return LinkReport(
        base="https://scottn66.github.io/",
        pages_crawled=("https://scottn66.github.io/",),
        results=results,
    )


def test_no_args_returns_zero() -> None:
    assert main([]) == 0


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == f"portfolio-qc {version('portfolio-qc')}"
    assert captured.err == ""


def test_links_defaults_and_writes_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    seen: dict[str, object] = {}
    report = _report(
        LinkCheck(
            url="https://cdn.example/app.js",
            kind="external",
            outcome="warn",
            status=403,
            error=None,
            sources=("https://scottn66.github.io/",),
        )
    )

    def fake_check(base: str, *, max_pages: int) -> LinkReport:
        seen["base"] = base
        seen["max_pages"] = max_pages
        return report

    monkeypatch.setattr("portfolio_qc.cli.check_links", fake_check)
    destination = tmp_path / "report.json"
    assert main(["links", "--json", str(destination)]) == 0
    assert seen == {
        "base": "https://scottn66.github.io",
        "max_pages": DEFAULT_MAX_PAGES,
    }
    assert json.loads(destination.read_text(encoding="utf-8")) == report.to_dict()
    captured = capsys.readouterr()
    assert "broken_internal: 0" in captured.out
    assert "warn: 1" in captured.out
    assert "broken internal:" not in captured.out
    assert captured.err == ""


def test_links_exit_one_lists_broken_internal(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = _report(
        LinkCheck(
            url="https://scottn66.github.io/missing",
            kind="internal",
            outcome="broken",
            status=404,
            error=None,
            sources=("https://scottn66.github.io/",),
        )
    )
    monkeypatch.setattr("portfolio_qc.cli.check_links", lambda *_a, **_k: report)
    assert (
        main(
            [
                "links",
                "--base",
                "https://example.test/docs",
                "--max-pages",
                "3",
            ]
        )
        == 1
    )
    captured = capsys.readouterr()
    assert "broken_internal: 1" in captured.out
    assert (
        "https://scottn66.github.io/missing (404) from https://scottn66.github.io/"
        in captured.out
    )


def test_links_rejects_bad_base(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["links", "--base", "not-a-url"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "absolute http" in captured.err


def test_links_rejects_non_positive_max_pages() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["links", "--max-pages", "0"])
    assert exc.value.code == 2


def test_links_rejects_non_integer_max_pages() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["links", "--max-pages", "nope"])
    assert exc.value.code == 2


def test_links_json_os_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("portfolio_qc.cli.check_links", lambda *_a, **_k: _report())
    missing = tmp_path / "missing" / "report.json"
    assert main(["links", "--json", str(missing)]) == 2
    captured = capsys.readouterr()
    assert "pages_crawled: 1" in captured.out
    assert "portfolio-qc:" in captured.err

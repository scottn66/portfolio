"""Console-script stub. No network."""

from __future__ import annotations

from importlib.metadata import version

import pytest

from portfolio_qc.cli import main


def test_no_args_returns_zero() -> None:
    assert main([]) == 0


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == f"portfolio-qc {version('portfolio-qc')}"
    assert captured.err == ""

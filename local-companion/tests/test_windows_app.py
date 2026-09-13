from pathlib import Path

import pytest

from tda_companion.installed_acceptance import REQUIRED_OBSERVATIONS
from tda_companion.pairing import TOKEN_PATTERN, ensure_pairing_token
from tda_companion.windows_app import (
    PRODUCTION_ORIGIN,
    default_roots,
    parse_args,
    validate_origin,
)


def test_default_roots_are_isolated_from_legacy(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    state, data = default_roots()
    assert state == tmp_path / "TDA" / "State"
    assert data == tmp_path / "TDA" / "Data"
    assert "DnDScribe" not in str(state)
    assert "DnDScribe" not in str(data)


def test_pairing_token_is_generated_once(tmp_path: Path):
    path = tmp_path / "pairing-token.txt"
    first = ensure_pairing_token(path)
    second = ensure_pairing_token(path)
    assert first == second
    assert TOKEN_PATTERN.fullmatch(first)
    assert path.read_text(encoding="utf-8").strip() == first


def test_invalid_existing_pairing_token_fails_closed(tmp_path: Path):
    path = tmp_path / "pairing-token.txt"
    path.write_text("curto\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="INVALID_EXISTING_PAIRING_TOKEN"):
        ensure_pairing_token(path)


@pytest.mark.parametrize(
    "origin",
    [
        PRODUCTION_ORIGIN,
        "https://preview.example.test",
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ],
)
def test_allowed_origin_shapes(origin: str):
    assert validate_origin(origin) == origin


@pytest.mark.parametrize(
    "origin",
    [
        "http://example.com",
        "https://example.com/path",
        "https://*.example.com",
        "file:///tmp/index.html",
    ],
)
def test_disallowed_origin_shapes(origin: str):
    with pytest.raises(ValueError, match="EXACT_HTTPS_OR_LOOPBACK_ORIGIN_REQUIRED"):
        validate_origin(origin)


def test_default_cli_origin_port_and_roots(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    args = parse_args([])
    assert args.port == 8765
    assert args.origins == frozenset({PRODUCTION_ORIGIN})
    assert args.state_root == tmp_path / "TDA" / "State"
    assert args.data_root == tmp_path / "TDA" / "Data"
    assert args.logs_root == tmp_path / "TDA" / "Logs"
    assert args.agent is False


def test_headless_remains_compatibility_alias_for_agent(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    args = parse_args(["--headless"])
    assert args.agent is True


def test_installed_acceptance_requires_candidate_source_craig_and_result(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    with pytest.raises(SystemExit):
        parse_args(["--installed-acceptance"])


def test_installed_acceptance_parses_only_named_observations(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    argv = [
        "--installed-acceptance",
        "--acceptance-candidate-msi",
        str(tmp_path / "candidate.msi"),
        "--acceptance-source-sha",
        "0" * 40,
        "--acceptance-craig-zip",
        str(tmp_path / "craig.zip"),
        "--acceptance-result-file",
        str(tmp_path / "receipt.json"),
    ]
    for observation in sorted(REQUIRED_OBSERVATIONS):
        argv.extend(["--acceptance-observation", observation])

    args = parse_args(argv)

    assert args.installed_acceptance is True
    assert args.acceptance_craig_zip == tmp_path / "craig.zip"
    assert frozenset(args.acceptance_observation or ()) == REQUIRED_OBSERVATIONS

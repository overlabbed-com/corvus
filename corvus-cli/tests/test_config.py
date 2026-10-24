"""config.py - resolution order is env var, then ~/.corvus.json, then the default."""

from __future__ import annotations

import json

from corvus_cli import config


def _write_config(home, payload: dict) -> None:
    (home / ".corvus.json").write_text(json.dumps(payload))


def test_base_url_defaults_to_localhost_when_nothing_configured():
    assert config.get_base_url() == "http://localhost:8000"


def test_base_url_comes_from_env(monkeypatch):
    monkeypatch.setenv("CORVUS_URL", "http://corvus.test:9420/")
    assert config.get_base_url() == "http://corvus.test:9420"


def test_base_url_strips_every_trailing_slash(monkeypatch):
    monkeypatch.setenv("CORVUS_URL", "http://corvus.test:9420///")
    assert config.get_base_url() == "http://corvus.test:9420"


def test_base_url_comes_from_config_file(isolated_env):
    _write_config(isolated_env, {"url": "https://corvus.example/"})
    assert config.get_base_url() == "https://corvus.example"


def test_base_url_config_file_without_url_key_falls_back(isolated_env):
    _write_config(isolated_env, {"token": "t"})
    assert config.get_base_url() == "http://localhost:8000"


def test_base_url_env_wins_over_config_file(monkeypatch, isolated_env):
    _write_config(isolated_env, {"url": "https://from-file"})
    monkeypatch.setenv("CORVUS_URL", "https://from-env")
    assert config.get_base_url() == "https://from-env"


def test_empty_env_url_falls_through_to_config_file(monkeypatch, isolated_env):
    _write_config(isolated_env, {"url": "https://from-file"})
    monkeypatch.setenv("CORVUS_URL", "")
    assert config.get_base_url() == "https://from-file"


def test_token_comes_from_env(monkeypatch):
    monkeypatch.setenv("CORVUS_TOKEN", "env-token")
    assert config.get_token() == "env-token"


def test_token_comes_from_config_file(isolated_env):
    _write_config(isolated_env, {"token": "file-token"})
    assert config.get_token() == "file-token"


def test_token_defaults_to_empty_string():
    assert config.get_token() == ""


def test_token_env_wins_over_config_file(monkeypatch, isolated_env):
    _write_config(isolated_env, {"token": "file-token"})
    monkeypatch.setenv("CORVUS_TOKEN", "env-token")
    assert config.get_token() == "env-token"


def test_load_config_file_returns_empty_dict_when_absent():
    assert config._load_config_file() == {}


def test_load_config_file_reads_the_json(isolated_env):
    _write_config(isolated_env, {"url": "https://corvus.example", "token": "abc"})
    assert config._load_config_file() == {"url": "https://corvus.example", "token": "abc"}

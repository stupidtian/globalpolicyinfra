"""Configuration resolution for GlobalPolicyInfra.

ARCHITECTURE.md decision record 2026-08-20:

- Precedence: **explicit argument > ``POLICY_DATA_ROOT`` environment variable
  > config file > loud error with guidance**. There is deliberately **no
  silent default** data root.
- The config file is global: ``~/.globalpolicyinfra/config.toml``. In v1 it
  carries a single field, ``data_root``. It is created by ``gpi init``.
- Secrets travel through a repo-local ``.env`` file (gitignored, template at
  ``.env.example``): the primary channel for API keys, loaded into the
  environment by :func:`load_env_file`. Non-secret settings (``data_root``)
  never go in ``.env``; secrets never go in config.toml. v1 has no secret
  consumers yet — they land with Part 4 (extraction, LLM).

Project-level config files (overriding the global one inside a directory) are
deliberately deferred until multiple data roots coexist.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

__all__ = [
    "CONFIG_DIR_NAME",
    "CONFIG_FILE_NAME",
    "DATA_ROOT_ENV_VAR",
    "ENV_FILE_NAME",
    "ConfigError",
    "default_config_dir",
    "default_config_path",
    "load_config",
    "load_env_file",
    "parse_env_file",
    "resolve_data_root",
    "write_config",
]

CONFIG_DIR_NAME = ".globalpolicyinfra"
CONFIG_FILE_NAME = "config.toml"
DATA_ROOT_ENV_VAR = "POLICY_DATA_ROOT"
ENV_FILE_NAME = ".env"

_GUIDANCE = (
    "No data root configured. Choose one of:\n"
    f"  1. run `gpi init` to create ~/{CONFIG_DIR_NAME}/{CONFIG_FILE_NAME},\n"
    f"  2. set the {DATA_ROOT_ENV_VAR} environment variable,\n"
    "  3. pass data_root explicitly.\n"
    "GPI never guesses a data location for you."
)


class ConfigError(RuntimeError):
    """Raised when configuration is missing or invalid."""


def default_config_dir() -> Path:
    """Global config directory ``~/.globalpolicyinfra``."""
    return Path.home() / CONFIG_DIR_NAME


def default_config_path() -> Path:
    """Global config file ``~/.globalpolicyinfra/config.toml``."""
    return default_config_dir() / CONFIG_FILE_NAME


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """Load the TOML config file.

    A missing file is not an error: it simply counts as "no config source"
    during resolution. An unreadable or malformed file is.
    """
    path = Path(config_path) if config_path is not None else default_config_path()
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Malformed config file {path}: {exc}") from exc


def resolve_data_root(
    data_root: str | Path | None = None,
    config_path: str | Path | None = None,
) -> Path:
    """Resolve the data root following the documented precedence chain.

    Args:
        data_root: Explicit value; wins over everything when given.
        config_path: Explicit config file location (useful for tests and
            scripted setups); defaults to :func:`default_config_path`.

    Raises:
        ConfigError: when no source yields a usable value. The message
            explains exactly how to configure one (no silent fallback).
    """
    if data_root is not None:
        candidate = str(data_root).strip()
        if not candidate:
            raise ConfigError("An explicitly empty data_root is not allowed.")
        return Path(candidate).expanduser()

    env_value = os.environ.get(DATA_ROOT_ENV_VAR, "").strip()
    if env_value:
        return Path(env_value).expanduser()

    config = load_config(config_path)
    file_value = config.get("data_root")
    if file_value is not None:
        if not isinstance(file_value, str) or not file_value.strip():
            source = Path(config_path) if config_path is not None else default_config_path()
            raise ConfigError(f"Config file {source} has an invalid data_root value.")
        return Path(file_value.strip()).expanduser()

    raise ConfigError(_GUIDANCE)


def _toml_escape(value: str) -> str:
    """Escape a string for a TOML basic string."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def write_config(
    data_root: str | Path,
    config_dir: str | Path | None = None,
    *,
    overwrite: bool = False,
) -> Path:
    """Write the global config file (used by ``gpi init``).

    Returns the path written. Refuses to clobber an existing config unless
    ``overwrite`` is true.
    """
    directory = Path(config_dir) if config_dir is not None else default_config_dir()
    path = directory / CONFIG_FILE_NAME
    if path.exists() and not overwrite:
        raise ConfigError(f"Config file already exists at {path}; use --force to overwrite.")
    directory.mkdir(parents=True, exist_ok=True)
    content = (
        "# GlobalPolicyInfra configuration.\n"
        "# Created by `gpi init`. Currently the only field is data_root.\n"
        "# Secrets (API keys) never go here; they live in the repo-local .env.\n"
        f'data_root = "{_toml_escape(str(data_root))}"\n'
    )
    path.write_text(content, encoding="utf-8")
    return path


def _repo_root() -> Path:
    """Best-effort repository root: this file sits in
    ``{repo}/core/config.py`` under the flat layout."""
    return Path(__file__).resolve().parents[2]


def parse_env_file(path: str | Path) -> dict[str, str]:
    """Parse a ``.env`` file into a dict (stdlib only, no dependency).

    Supported syntax: ``KEY=VALUE`` lines, blank lines, ``#`` comments, an
    optional ``export `` prefix, and optional matching single/double quotes
    around the value. Lines without ``=`` are ignored.
    """
    entries: dict[str, str] = {}
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        entries[key] = value
    return entries


def load_env_file(path: str | Path | None = None, *, override: bool = False) -> dict[str, str]:
    """Load secrets from ``.env`` into the environment.

    Args:
        path: Explicit ``.env`` location. When omitted, looks in the current
            working directory first, then at the repository root.
        override: When false (default), variables already present in the
            environment win — the usual dotenv convention, so externally
            injected secrets always take precedence.

    Returns:
        The parsed entries. A missing file is not an error (returns ``{}``).

    v1 parses and exposes the entries; the actual secret consumers arrive
    with Part 4 (extraction, LLM).
    """
    if path is None:
        for candidate in (Path.cwd() / ENV_FILE_NAME, _repo_root() / ENV_FILE_NAME):
            if candidate.is_file():
                path = candidate
                break
    if path is None or not Path(path).is_file():
        return {}
    entries = parse_env_file(path)
    for key, value in entries.items():
        if override or key not in os.environ:
            os.environ[key] = value
    return entries

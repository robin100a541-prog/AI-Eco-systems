"""Strukturerad loggning (FR-04, SR-10) med Pythons `logging`.

Loggern heter `aie`. Moduler hämtar en underlogger med `get_logger("namn")`.

- **Fil:** `<log_dir>/aie.log`, en JSON-rad per händelse med tidsstämpel (UTC), nivå,
  källa (loggerns namn), plats i koden och meddelande. Filen roteras vid 5 MB och tre
  gamla filer sparas, så loggarna växer aldrig obegränsat.
- **Konsol:** samma händelser som läsbar text på stderr.

Hemligheter maskeras som `***` innan något skrivs, i både fil och konsol (SR-10):
1. `nyckel=värde` och `nyckel: värde` i texten, där nyckeln ser ut som en hemlighet
   (`*_KEY`, `*_TOKEN`, `*_SECRET`, `*_PASSWORD`, `password`, `key`, `token`, `secret`).
2. Fält i `extra={"fields": {...}}` vars nyckel ser ut som en hemlighet, även i nästlade tabeller.
3. Värdet av varje miljövariabel vars namn ser ut som en hemlighet, var det än står,
   till exempel i ett felmeddelande eller en traceback.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, TextIO

from ..config import is_secret_key

LOGGER_NAME = "aie"
LOG_FILE_NAME = "aie.log"
LOG_MAX_BYTES = 5 * 1024 * 1024  # 5 MB per fil
LOG_BACKUP_COUNT = 3  # aie.log.1 … aie.log.3; högst cirka 20 MB loggar totalt
MASK = "***"
_MIN_ENV_SECRET_LENGTH = 4  # kortare miljövärden skulle maskera vanliga ord

_SECRET_KEY = (
    r"[A-Za-z0-9_]*(?:_key|_token|_secret|_password)|password|passwd|secret|token|key"
)
_KEY_VALUE = re.compile(
    rf"""(?P<key>["']?\b(?:{_SECRET_KEY})\b["']?)(?P<sep>\s*[:=]\s*)(?P<value>"[^"]*"|'[^']*'|[^\s,;)\]}}]+)""",
    re.IGNORECASE,
)


class LoggingSetupError(Exception):
    """Loggningen kan inte startas, till exempel för att `log_dir` inte kan skapas."""


def mask_secrets(text: str, environ: Mapping[str, str] | None = None) -> str:
    """Ersätter hemligheter i `text` med `***` (SR-10). Se modulens docstring för reglerna."""
    environ = os.environ if environ is None else environ
    for name, value in environ.items():
        if is_secret_key(name) and len(value) >= _MIN_ENV_SECRET_LENGTH:
            text = text.replace(value, MASK)
    return _KEY_VALUE.sub(lambda m: f"{m['key']}{m['sep']}{MASK}", text)


def mask_fields(data: Any) -> Any:
    """Maskerar strukturerade fält: hemliga nycklar helt, övriga strängar som text."""
    if isinstance(data, Mapping):
        return {
            str(k): MASK if is_secret_key(str(k)) else mask_fields(v)
            for k, v in data.items()
        }
    if isinstance(data, (list, tuple)):
        return [mask_fields(v) for v in data]
    if data is None or isinstance(data, (bool, int, float)):
        return data
    return mask_secrets(str(data))


class JsonLineFormatter(logging.Formatter):
    """En JSON-rad per händelse (FR-04). Allt maskeras innan det kodas (SR-10)."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "source": record.name,
            "where": f"{record.module}:{record.lineno}",
            "message": mask_secrets(record.getMessage()),
        }
        fields = getattr(record, "fields", None)
        if fields:
            entry["fields"] = mask_fields(fields)
        if record.exc_info:
            entry["exception"] = mask_secrets(self.formatException(record.exc_info))
        return json.dumps(entry, ensure_ascii=False, default=str)


class ConsoleFormatter(logging.Formatter):
    """Läsbar rad för konsolen: `2026-10-23 18:00:00 INFO aie.cli: meddelande {fält}`."""

    def __init__(self) -> None:
        super().__init__(
            "%(asctime)s %(levelname)s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"
        )

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        fields = getattr(record, "fields", None)
        if fields:
            text += " " + json.dumps(
                mask_fields(fields), ensure_ascii=False, default=str
            )
        return mask_secrets(text)


def setup_logging(
    log_dir: Path | str,
    level: str = "INFO",
    *,
    console: bool = True,
    stream: TextIO | None = None,
    max_bytes: int = LOG_MAX_BYTES,
    backup_count: int = LOG_BACKUP_COUNT,
) -> logging.Logger:
    """Startar loggningen till `<log_dir>/aie.log` och, om `console`, till `stream` (stderr).

    En saknad `log_dir` skapas, även nästlade mappar. Om mappen inte kan skapas eller filen
    inte kan öppnas kastas `LoggingSetupError` med sökvägen och orsaken. Ett nytt anrop
    ersätter tidigare handlers, så samma händelse skrivs aldrig två gånger.

    Filen roteras när den når `max_bytes`: `aie.log` blir `aie.log.1`, `aie.log.1` blir
    `aie.log.2` och så vidare. Högst `backup_count` gamla filer sparas, den äldsta raderas.
    """
    log_dir = Path(log_dir)
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / LOG_FILE_NAME,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
    except OSError as exc:
        raise LoggingSetupError(
            # Inte !r: repr dubblerar backslash i Windows-sökvägar och gör meddelandet svårläst.
            f"log_dir '{log_dir}' kan inte skapas eller skrivas: {exc}"
        ) from exc

    shutdown_logging()
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False
    file_handler.setFormatter(JsonLineFormatter())
    logger.addHandler(file_handler)
    if console:
        console_handler = logging.StreamHandler(
            sys.stderr if stream is None else stream
        )
        console_handler.setFormatter(ConsoleFormatter())
        logger.addHandler(console_handler)
    return logger


def shutdown_logging() -> None:
    """Stänger och tar bort loggerns handlers, så att loggfilen släpps (viktigt på Windows).

    Kvar blir bara en `NullHandler`: utan loggning igång ska ingenting skrivas, inte heller
    via Pythons reserv-handler som annars skriver varningar till stderr.
    """
    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.addHandler(logging.NullHandler())


def get_logger(name: str | None = None) -> logging.Logger:
    """Logger under `aie`: `get_logger("cli")` ger `aie.cli`."""
    return logging.getLogger(f"{LOGGER_NAME}.{name}" if name else LOGGER_NAME)


shutdown_logging()  # loggern `aie` är tyst tills setup_logging anropas

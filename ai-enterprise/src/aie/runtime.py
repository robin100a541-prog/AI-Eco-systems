"""Start, stopp och status för systemet (Fas 1.6, FR-01) med grundläggande felhantering.

Kommandona i `python -m aie` anropar funktionerna här. Varje funktion returnerar en
avslutningskod: 0 = lyckades, 1 = fel (felet är då utskrivet och loggat).

Ordning vid `start`:
1. Läs och validera konfigurationen (FR-02). Fel → kod 1, felen skrivs ut och loggas.
2. Starta loggningen (FR-04). En `log_dir` som inte kan skapas → kod 1.
3. Öppna databasen och kör migrationer (FR-03). Lagringsfel → kod 1.
4. Kontrollera revisionsloggen (SR-09). En manipulerad kedja → kod 1, systemet startar inte.
5. Vägra starta om en annan process redan kör. Har en tidigare körning dött utan att
   stänga ned (strömavbrott, dödad process) loggas och revideras det, sedan startas systemet.
6. Markera systemet som igång och vänta tills `aie stop`, Ctrl+C eller SIGTERM ber det stanna.
7. Stäng ned rent: markera som stoppat, skriv revisionsrad med kedjans senaste hash, stäng
   databasen. Ett oväntat fel loggas med traceback och ger kod 1, men nedstängningen görs ändå.
"""

from __future__ import annotations

import os
import signal
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .audit import AuditLog
from .config import Config, ConfigError, load_config
from .memory import Database, StorageError, open_database
from .monitoring import LoggingSetupError, get_logger, setup_logging

# När konfigurationen är ogiltig är log_dir okänd. Felen loggas då här, relativt
# mappen kommandot körs från, samma som standardvärdet i config/system.toml.
FALLBACK_LOG_DIR = Path("logs")
ACTOR = "system"
DEFAULT_POLL_SECONDS = 1.0
DEFAULT_STOP_WAIT_SECONDS = 30.0

log = get_logger("runtime")


@dataclass(frozen=True, slots=True)
class RuntimeState:
    state: str  # "running" eller "stopped"
    pid: int | None
    started_at: str | None
    stopped_at: str | None
    stop_requested: bool
    last_exit: str | None  # "clean", "error", "unclean" eller None (aldrig körts)


class StartupError(Exception):
    """Systemet kan inte starta. Meddelandet är skrivet för människor."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# --- Driftläget i databasen ------------------------------------------------------------


def read_state(db: Database) -> RuntimeState:
    row = db.connection.execute(
        "SELECT state, pid, started_at, stopped_at, stop_requested, last_exit "
        "FROM runtime_state WHERE id = 1"
    ).fetchone()
    state, pid, started_at, stopped_at, stop_requested, last_exit = row
    return RuntimeState(
        state, pid, started_at, stopped_at, bool(stop_requested), last_exit
    )


def _set_running(db: Database, pid: int) -> None:
    with db.transaction() as tx:
        tx.execute(
            "UPDATE runtime_state SET state = 'running', pid = ?, started_at = ?, "
            "stopped_at = NULL, stop_requested = 0 WHERE id = 1",
            (pid, _now()),
        )


def _set_stopped(db: Database, last_exit: str) -> None:
    with db.transaction() as tx:
        tx.execute(
            "UPDATE runtime_state SET state = 'stopped', pid = NULL, stopped_at = ?, "
            "stop_requested = 0, last_exit = ? WHERE id = 1",
            (_now(), last_exit),
        )


def _request_stop(db: Database) -> None:
    with db.transaction() as tx:
        tx.execute("UPDATE runtime_state SET stop_requested = 1 WHERE id = 1")


def pid_alive(pid: int) -> bool:
    """Finns processen fortfarande? Fungerar på Windows, macOS och Linux."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        # os.kill(pid, 0) skulle AVSLUTA processen på Windows, därför Win32-API:t.
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(
            0x1000, False, pid
        )  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return (
                bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code)))
                and code.value == 259
            )
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # processen finns men tillhör någon annan
        return True
    return True


# --- Gemensam uppstart för alla kommandon ------------------------------------------------


def _log_config_errors(exc: ConfigError) -> None:
    """Loggar konfigurationsfelen i FALLBACK_LOG_DIR. Går det inte är felen redan utskrivna."""
    try:
        setup_logging(FALLBACK_LOG_DIR, console=False)
    except LoggingSetupError:
        return
    config_log = get_logger("config")
    for error in exc.errors:
        config_log.error("konfigurationsfel: %s", error)
    for warning in exc.warnings:
        config_log.warning("konfigurationsvarning: %s", warning)


def _load(config_dir: Path, *, console: bool) -> Config:
    """Konfiguration + loggning. Kastar StartupError med ett läsbart meddelande."""
    try:
        config = load_config(config_dir)
    except ConfigError as exc:
        _log_config_errors(exc)
        raise StartupError(str(exc)) from exc
    system = config.system
    try:
        setup_logging(system.log_dir, system.log_level, console=console)
    except LoggingSetupError as exc:
        raise StartupError(f"FEL: {exc}") from exc
    for warning in config.warnings:
        log.warning("konfigurationsvarning: %s", warning)
    return config


def _open(config: Config) -> Database:
    try:
        return open_database(config.system)  # felet loggas redan i aie.memory
    except StorageError as exc:
        raise StartupError(f"FEL: {exc}") from exc


def _fail(exc: StartupError) -> int:
    print(exc, file=sys.stderr)
    return 1


# --- Kommandon -------------------------------------------------------------------------------


def init(config_dir: Path) -> int:
    """Skapar eller uppgraderar databasen och visar var den ligger."""
    try:
        config = _load(config_dir, console=False)
        with _open(config) as db:
            AuditLog(db).append(
                ACTOR, "system.init", {"schema_version": db.schema_version}
            )
            print(
                f"Databasen är klar: {db.path} (miljö: {db.environment}, schemaversion: {db.schema_version})"
            )
            log.info(
                "init klar",
                extra={
                    "fields": {
                        "path": str(db.path),
                        "schema_version": db.schema_version,
                    }
                },
            )
    except StartupError as exc:
        return _fail(exc)
    return 0


def status(config_dir: Path) -> int:
    """Visar driftläget och kontrollerar revisionsloggen. Kod 1 om kedjan är manipulerad."""
    try:
        config = _load(config_dir, console=False)
        with _open(config) as db:
            state = read_state(db)
            check = AuditLog(db).verify()
            running = (
                state.state == "running"
                and state.pid is not None
                and pid_alive(state.pid)
            )
            if state.state == "running" and not running:
                shown = "stoppad (förra körningen avslutades inte rent)"
            else:
                shown = f"igång (pid {state.pid})" if running else "stoppad"
            print(f"Miljö:          {db.environment}")
            print(f"Databas:        {db.path} (schemaversion {db.schema_version})")
            print(f"Status:         {shown}")
            print(f"Startad:        {state.started_at or '-'}")
            print(f"Stoppad:        {state.stopped_at or '-'}")
            print(f"Senaste avslut: {state.last_exit or '-'}")
            if check.ok:
                print(
                    f"Revisionslogg:  OK, {check.checked} rader, senaste hash {check.head_hash}"
                )
                return 0
            message = f"MANIPULERAD vid rad {check.first_bad_seq}: {check.reason}"
            print(f"Revisionslogg:  {message}", file=sys.stderr)
            log.error("revisionsloggen är %s", message)
            return 1
    except StartupError as exc:
        return _fail(exc)


def stop(config_dir: Path, wait_seconds: float = DEFAULT_STOP_WAIT_SECONDS) -> int:
    """Ber den körande processen stanna och väntar tills den har stängt ned."""
    try:
        config = _load(config_dir, console=False)
        with _open(config) as db:
            state = read_state(db)
            if (
                state.state != "running"
                or state.pid is None
                or not pid_alive(state.pid)
            ):
                print("Systemet är inte igång.")
                return 0
            _request_stop(db)
            AuditLog(db).append(ACTOR, "system.stop_requested", {"pid": state.pid})
            log.info("stopp begärt", extra={"fields": {"pid": state.pid}})
            deadline = time.monotonic() + wait_seconds
            while time.monotonic() < deadline:
                if read_state(db).state == "stopped":
                    print("Systemet har stoppats.")
                    return 0
                time.sleep(0.1)
            message = f"Systemet (pid {state.pid}) stoppade inte inom {wait_seconds:g} sekunder."
            print(message, file=sys.stderr)
            log.error(message)
            return 1
    except StartupError as exc:
        return _fail(exc)


def start(
    config_dir: Path,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    *,
    stop_event: threading.Event | None = None,
    on_running: Callable[[], None] | None = None,
) -> int:
    """Startar systemet och kör tills det ombeds stanna. Se modulens docstring för ordningen.

    `stop_event` och `on_running` finns för tester: de låter ett test stoppa loopen och få
    veta när systemet är igång, utan att starta en ny process.
    """
    stop_event = stop_event or threading.Event()
    # Signalerna fångas före allt annat: ett Ctrl+C under uppstarten ska också ge en ren
    # nedstängning, inte ett avbrott mitt i en skrivning.
    restore = _install_signal_handlers(stop_event)
    try:
        return _run(config_dir, poll_seconds, stop_event, on_running)
    finally:
        restore()


def _run(
    config_dir: Path,
    poll_seconds: float,
    stop_event: threading.Event,
    on_running: Callable[[], None] | None,
) -> int:
    try:
        config = _load(config_dir, console=True)
        db = _open(config)
    except StartupError as exc:
        return _fail(exc)

    audit = AuditLog(db)
    pid = os.getpid()
    marked_running = False
    exit_code = 0
    try:
        check = audit.verify()
        if not check.ok:
            raise StartupError(
                f"FEL: revisionsloggen är manipulerad vid rad {check.first_bad_seq}: {check.reason}. "
                "Systemet startar inte (SR-09)."
            )
        previous = read_state(db)
        if previous.state == "running" and previous.pid is not None:
            if previous.pid != pid and pid_alive(previous.pid):
                raise StartupError(
                    f"FEL: systemet är redan igång (pid {previous.pid})."
                )
            log.warning("förra körningen (pid %s) avslutades inte rent", previous.pid)
            _set_stopped(db, "unclean")
            audit.append(ACTOR, "system.unclean_stop_detected", {"pid": previous.pid})

        _set_running(db, pid)
        marked_running = True
        audit.append(ACTOR, "system.start", {"pid": pid, "environment": db.environment})
        log.info(
            "systemet startat",
            extra={"fields": {"pid": pid, "environment": db.environment}},
        )
        print(
            f"Systemet är igång (pid {pid}, miljö {db.environment}). Stoppa med: python -m aie stop"
        )

        if on_running:
            on_running()
        while not stop_event.wait(poll_seconds):  # returnerar direkt om stopp redan begärts
            if read_state(db).stop_requested:
                break
    except StartupError as exc:
        log.error("%s", exc)
        exit_code = _fail(exc)
    except Exception:
        log.exception("oväntat fel; systemet stängs ned")
        print("FEL: oväntat fel, se loggfilen. Systemet stängs ned.", file=sys.stderr)
        exit_code = 1
    finally:
        try:
            if marked_running:
                _shutdown(db, audit, pid, "clean" if exit_code == 0 else "error")
                print("Systemet har stängts ned.")
        finally:
            db.close()
    return exit_code


def _shutdown(db: Database, audit: AuditLog, pid: int, last_exit: str) -> None:
    _set_stopped(db, last_exit)
    head = audit.append(ACTOR, "system.stop", {"pid": pid, "exit": last_exit}).hash
    log.info(
        "systemet stoppat",
        extra={"fields": {"pid": pid, "exit": last_exit, "audit_head_hash": head}},
    )


def _install_signal_handlers(stop_event: threading.Event) -> Callable[[], None]:
    """Ctrl+C och SIGTERM ber systemet stanna i stället för att avbryta mitt i en skrivning."""
    if threading.current_thread() is not threading.main_thread():
        return lambda: None  # signaler kan bara fångas i huvudtråden (gäller tester)
    names = ["SIGINT", "SIGTERM"] + (["SIGBREAK"] if sys.platform == "win32" else [])
    previous = {}
    for name in names:
        signum = getattr(signal, name, None)
        if signum is not None:
            previous[signum] = signal.signal(signum, lambda *_: stop_event.set())

    def restore() -> None:
        for signum, handler in previous.items():
            signal.signal(signum, handler)

    return restore

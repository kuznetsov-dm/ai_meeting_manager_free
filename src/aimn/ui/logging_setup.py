from __future__ import annotations

import faulthandler
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QtMsgType, qInstallMessageHandler


_LOG_NAME = "aimn"
_CRASH_HANDLE: object | None = None


def setup_logging(repo_root: Path) -> Path:
    logs_dir = repo_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / "ui.log"
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        if isinstance(handler, logging.FileHandler) and handler.baseFilename == str(log_path):
            return log_path
    root_logger.setLevel(logging.INFO)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(JsonFormatter())
    root_logger.addHandler(handler)
    return log_path


def install_exception_hook() -> None:
    logger = logging.getLogger(f"{_LOG_NAME}.ui")
    handling = {"active": False}

    def _handle(exc_type, exc, tb) -> None:
        if handling["active"]:
            sys.__excepthook__(exc_type, exc, tb)
            return
        handling["active"] = True
        try:
            try:
                logger.error("unhandled_exception", exc_info=(exc_type, exc, tb))
            except Exception:
                pass
            sys.__excepthook__(exc_type, exc, tb)
        finally:
            handling["active"] = False

    sys.excepthook = _handle


def enable_faulthandler(repo_root: Path) -> Path:
    global _CRASH_HANDLE
    logs_dir = repo_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    crash_path = logs_dir / "ui_crash.log"
    _CRASH_HANDLE = crash_path.open("a", encoding="utf-8")
    faulthandler.enable(file=_CRASH_HANDLE)
    return crash_path


def install_qt_message_handler() -> None:
    logger = logging.getLogger(f"{_LOG_NAME}.qt")

    def _handler(mode, context, message) -> None:
        if mode == QtMsgType.QtCriticalMsg or mode == QtMsgType.QtFatalMsg:
            level = logging.ERROR
        elif mode == QtMsgType.QtWarningMsg:
            level = logging.WARNING
        else:
            level = logging.INFO
        source = context.file or ""
        line = context.line or 0
        logger.log(level, f"qt_message {source}:{line} {message}")

    qInstallMessageHandler(_handler)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key
            not in {
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
            }
        }
        if extras:
            payload["context"] = extras
        return json.dumps(payload, ensure_ascii=True)

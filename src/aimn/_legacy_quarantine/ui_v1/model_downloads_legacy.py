from __future__ import annotations

import logging
import re
import urllib.request
from pathlib import Path

from PySide6.QtCore import QThread, Signal


class ModelDownloadThread(QThread):
    progress = Signal(int)
    log = Signal(str)
    failed = Signal(str)
    finished_ok = Signal(str)

    def __init__(self, model: str, url: str, *, target_path: Path) -> None:
        super().__init__()
        self._model = model
        self._url = url
        self._target_path = Path(target_path)
        self._last_logged = -1

    def run(self) -> None:
        logger = logging.getLogger("aimn.network.models")
        logger.info("whisper_download_start model=%s url=%s", self._model, self._url)
        try:
            if self.isInterruptionRequested():
                self.failed.emit("download_cancelled")
                return
            self._target_path.parent.mkdir(parents=True, exist_ok=True)

            def _report_hook(count: int, block_size: int, total_size: int) -> None:
                if total_size <= 0:
                    return
                percent = int(min(100, (count * block_size * 100) / total_size))
                if percent != self._last_logged:
                    self._last_logged = percent
                    self.progress.emit(percent)

            self.log.emit(f"Downloading {self._model}...")
            urllib.request.urlretrieve(self._url, self._target_path, reporthook=_report_hook)
            logger.info("whisper_download_finished model=%s", self._model)
            self.finished_ok.emit(self._model)
        except Exception as exc:
            logger.error("whisper_download_failed model=%s error=%s", self._model, exc)
            self.failed.emit(str(exc))

    def request_cancel(self) -> None:
        self.requestInterruption()


class TextModelDownloadThread(QThread):
    progress = Signal(int)
    log = Signal(str)
    failed = Signal(str)
    finished_ok = Signal(str)

    def __init__(self, model_kind: str, target_path: str, url: str) -> None:
        super().__init__()
        self._model_kind = model_kind
        self._target_path = target_path
        self._url = url
        self._last_logged = -1

    def run(self) -> None:
        try:
            if self.isInterruptionRequested():
                self.failed.emit("download_cancelled")
                return
            if self._model_kind == "fasttext":
                self._download_fasttext()
                self.finished_ok.emit("fasttext")
                return
            if self._model_kind == "embeddings":
                self._download_embeddings()
                self.finished_ok.emit("embeddings")
                return
            raise ValueError(f"Unknown model kind: {self._model_kind}")
        except Exception as exc:
            self.failed.emit(str(exc))

    def _download_fasttext(self) -> None:
        import urllib.request

        target = Path(self._target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        urls = [u.strip() for u in re.split(r"[,\s]+", self._url) if u.strip()]
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "*/*",
            "Accept-Encoding": "identity",
            "Connection": "keep-alive",
        }
        last_error: Exception | None = None
        for url in urls:
            try:
                self.log.emit(f"FastText download attempt: {url}")
                request = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(request) as response:
                    total_size = int(response.headers.get("Content-Length", "0") or 0)
                    downloaded = 0
                    chunk_size = 1024 * 1024
                    with open(target, "wb") as handle:
                        while True:
                            if self.isInterruptionRequested():
                                raise RuntimeError("download_cancelled")
                            chunk = response.read(chunk_size)
                            if not chunk:
                                break
                            handle.write(chunk)
                            downloaded += len(chunk)
                            if total_size > 0:
                                percent = int(min(100, (downloaded * 100) / total_size))
                                if percent != self._last_logged:
                                    self._last_logged = percent
                                    self.progress.emit(percent)
                return
            except Exception as exc:
                last_error = exc
                self.log.emit(f"FastText download failed: {exc}")
                if target.exists():
                    target.unlink()
        if last_error:
            raise last_error

    def _download_embeddings(self) -> None:
        if self.isInterruptionRequested():
            raise RuntimeError("download_cancelled")
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as exc:
            raise RuntimeError("sentence-transformers not installed") from exc
        cache_dir = Path(self._target_path)
        cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            SentenceTransformer(self._url, cache_folder=str(cache_dir))
        except Exception as exc:
            message = str(exc)
            hint = ""
            lowered = message.lower()
            if "401" in lowered or "403" in lowered or "unauthorized" in lowered or "forbidden" in lowered:
                hint = (
                    " Access denied. If the model is gated/private, set HUGGINGFACE_HUB_TOKEN or login via "
                    "huggingface-cli."
                )
            elif "connection" in lowered or "timed out" in lowered or "temporary failure" in lowered:
                hint = " Network error. Check internet/proxy access to huggingface.co."
            if "not a local folder" in lowered and "valid model identifier" in lowered:
                raise RuntimeError(
                    f"Cannot download model '{self._url}'. The ID is valid, but it could not be fetched."
                    f"{hint} Details: {message}"
                ) from exc
            raise RuntimeError(f"Embeddings download failed: {message}{hint}") from exc

    def request_cancel(self) -> None:
        self.requestInterruption()

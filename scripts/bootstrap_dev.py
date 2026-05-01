from __future__ import annotations

import json
from pathlib import Path


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _ensure_file(path: Path, content: str) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    _ensure_dir(repo_root / "output")
    _ensure_dir(repo_root / "logs")
    _ensure_dir(repo_root / "models" / "whisper")
    _ensure_dir(repo_root / "models" / "llama")
    _ensure_dir(repo_root / "config" / "settings" / "pipeline")
    _ensure_dir(repo_root / "config" / "settings" / "plugins")
    _ensure_dir(repo_root / "config" / "index")

    active_path = repo_root / "config" / "settings" / "pipeline" / "active.json"
    if not active_path.exists():
        active_path.write_text(json.dumps({"preset": "default"}, indent=2), encoding="utf-8")

    secrets_template = (
        "# Local secrets template\n"
        "# Copy to config/secrets.toml and fill values.\n"
        "\n"
        "[openrouter]\n"
        "api_key = \"\"\n"
        "\n"
        "[deepseek]\n"
        "api_key = \"\"\n"
    )
    _ensure_file(repo_root / "config" / "secrets.template.toml", secrets_template)

    env_template = (
        "# Optional environment variables for local dev\n"
        "# AIMN_OPENROUTER_API_KEY=\n"
        "# AIMN_DEEPSEEK_API_KEY=\n"
        "# AIMN_FFMPEG_PATH=\n"
        "# AIMN_WHISPER_PATH=\n"
        "# AIMN_LLAMA_CLI_PATH=\n"
    )
    _ensure_file(repo_root / ".env.local", env_template)

    print("Dev bootstrap complete.")


if __name__ == "__main__":
    main()

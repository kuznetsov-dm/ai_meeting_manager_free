import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PLUGINS_ROOT = APP_ROOT / "tests" / "fixtures" / "plugins"


def install_plugin_fixture(target_root: Path, fixture_name: str) -> Path:
    source_dir = FIXTURE_PLUGINS_ROOT / str(fixture_name)
    if not source_dir.exists():
        raise FileNotFoundError(f"plugin_fixture_missing:{fixture_name}")
    target_dir = target_root / str(fixture_name)
    shutil.copytree(source_dir, target_dir)
    return target_dir


def write_plugin_package(target_root: Path, package_name: str, files: dict[str, str]) -> Path:
    package_dir = target_root / str(package_name)
    package_dir.mkdir(parents=True, exist_ok=True)
    for relative_path, content in files.items():
        file_path = package_dir / str(relative_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
    return package_dir


@contextmanager
def temporary_plugin_roots(*fixture_names: str) -> Iterator[Path]:
    previous = os.environ.get("AIMN_INSTALLED_PLUGINS_DIR")
    with tempfile.TemporaryDirectory() as temp_dir:
        plugins_root = Path(temp_dir)
        for fixture_name in fixture_names:
            install_plugin_fixture(plugins_root, fixture_name)
        os.environ["AIMN_INSTALLED_PLUGINS_DIR"] = str(plugins_root)
        try:
            yield plugins_root
        finally:
            if previous is None:
                os.environ.pop("AIMN_INSTALLED_PLUGINS_DIR", None)
            else:
                os.environ["AIMN_INSTALLED_PLUGINS_DIR"] = previous

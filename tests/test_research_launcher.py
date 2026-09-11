from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPOSITORY_ROOT / "research"


def _write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _old_python_fixture(path: Path) -> None:
    _write_executable(
        path,
        """#!/bin/sh
if [ "${1-}" = "-I" ]; then
    echo "Python 3.9.18 at /synthetic/python3"
    exit 64
fi
exit 70
""",
    )


def _supported_python_fixture(path: Path) -> None:
    _write_executable(
        path,
        f"""#!/bin/sh
exec {shlex.quote(sys.executable)} "$@"
""",
    )


def _launcher_environment(
    *,
    path: str,
    override: str | None = None,
    pythonpath: str | None = None,
) -> dict[str, str]:
    environment = {
        "PATH": path,
        "HOME": os.environ.get("HOME", ""),
    }
    if override is not None:
        environment["FARADAY_PYTHON"] = override
    if pythonpath is not None:
        environment["PYTHONPATH"] = pythonpath
    return environment


def test_launcher_uses_verified_absolute_override_without_path_python() -> None:
    completed = subprocess.run(
        [str(LAUNCHER), "--help"],
        cwd=REPOSITORY_ROOT,
        env=_launcher_environment(path="", override=sys.executable),
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "usage: research" in completed.stdout
    assert completed.stderr == ""


def test_launcher_rejects_relative_override_without_falling_back(
    tmp_path: Path,
) -> None:
    supported_directory = tmp_path / "supported"
    _supported_python_fixture(supported_directory / "python3")

    completed = subprocess.run(
        [str(LAUNCHER), "--help"],
        cwd=REPOSITORY_ROOT,
        env=_launcher_environment(
            path=str(supported_directory),
            override="python3",
        ),
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 126
    assert completed.stdout == ""
    assert "FARADAY_PYTHON must be an absolute interpreter path" in completed.stderr


def test_launcher_reports_missing_absolute_override(tmp_path: Path) -> None:
    missing_python = tmp_path / "missing" / "python3"

    completed = subprocess.run(
        [str(LAUNCHER), "--help"],
        cwd=REPOSITORY_ROOT,
        env=_launcher_environment(path="", override=str(missing_python)),
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 126
    assert completed.stdout == ""
    assert "does not name a regular interpreter file" in completed.stderr
    assert str(missing_python) in completed.stderr


def test_launcher_fails_closed_on_explicit_python_39_override(
    tmp_path: Path,
) -> None:
    old_python = tmp_path / "old" / "python3"
    supported_python = tmp_path / "supported" / "python3"
    _old_python_fixture(old_python)
    _supported_python_fixture(supported_python)

    completed = subprocess.run(
        [str(LAUNCHER), "--help"],
        cwd=REPOSITORY_ROOT,
        env=_launcher_environment(
            path=str(supported_python.parent),
            override=str(old_python),
        ),
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 126
    assert completed.stdout == ""
    assert "explicit FARADAY_PYTHON override is not usable" in completed.stderr
    assert "Python 3.9.18" in completed.stderr
    assert "requires Python >= 3.11" in completed.stderr


def test_launcher_searches_past_python_39_path_drift(tmp_path: Path) -> None:
    old_directory = tmp_path / "stale-path"
    supported_directory = tmp_path / "supported-path"
    _old_python_fixture(old_directory / "python3")
    _supported_python_fixture(supported_directory / "python3")

    completed = subprocess.run(
        [str(LAUNCHER), "--help"],
        cwd=REPOSITORY_ROOT,
        env=_launcher_environment(
            path=os.pathsep.join((str(old_directory), str(supported_directory)))
        ),
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "usage: research" in completed.stdout
    assert completed.stderr == ""


def test_launcher_reports_all_old_path_as_closed_failure(tmp_path: Path) -> None:
    old_directory = tmp_path / "stale-path"
    old_python = old_directory / "python3"
    _old_python_fixture(old_python)

    completed = subprocess.run(
        [str(LAUNCHER), "--help"],
        cwd=REPOSITORY_ROOT,
        env=_launcher_environment(path=str(old_directory)),
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 126
    assert completed.stdout == ""
    assert "no usable Python >= 3.11 interpreter was selected" in completed.stderr
    assert str(old_python) in completed.stderr
    assert "Python 3.9.18" in completed.stderr


def test_launcher_ignores_ambient_pythonpath(tmp_path: Path) -> None:
    shadow_package = tmp_path / "shadow" / "research_machine"
    shadow_package.mkdir(parents=True)
    (shadow_package / "__init__.py").write_text(
        'raise RuntimeError("ambient shadow package imported")\n',
        encoding="utf-8",
    )

    completed = subprocess.run(
        [str(LAUNCHER), "--help"],
        cwd=tmp_path,
        env=_launcher_environment(
            path="",
            override=sys.executable,
            pythonpath=str(shadow_package.parent),
        ),
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "usage: research" in completed.stdout
    assert "ambient shadow package" not in completed.stderr

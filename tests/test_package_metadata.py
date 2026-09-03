from pathlib import Path
import tomllib

import research_machine


def test_package_version_has_one_authoritative_source() -> None:
    root = Path(__file__).resolve().parents[1]
    configuration = tomllib.loads((root / "pyproject.toml").read_text())

    assert "version" not in configuration["project"]
    assert "version" in configuration["project"]["dynamic"]
    assert configuration["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "research_machine.__version__"
    }
    assert configuration["project"]["scripts"]["research-notebook-preflight"] == (
        "research_machine.executors.notebook_preflight:main"
    )
    assert configuration["project"]["scripts"][
        "research-notebook-runtime-preflight"
    ] == "research_machine.executors.runtime_preflight:main"
    assert "jupyter-client>=8.6" in configuration["project"][
        "optional-dependencies"
    ]["notebook"]
    assert research_machine.__version__ == "0.2.8"

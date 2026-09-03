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
    assert research_machine.__version__ == "0.2.3"

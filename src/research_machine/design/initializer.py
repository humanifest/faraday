from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.commands import AddQuestion, CreateInquiry, ProposeHypothesis
from research_machine.application.service import ResearchService
from research_machine.domain.errors import ValidationError
from research_machine.design.scaffold import scaffold_design, validate_brief


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def initialize_experiment_repository(
    brief: dict[str, Any], output: Path, *, actor: str, initialize_git: bool = True
) -> dict[str, Any]:
    """Create an isolated local experiment repository without approving a study."""
    validate_brief(brief)
    root = output.expanduser().resolve()
    if root.exists():
        raise ValidationError(f"experiment repository path already exists: {root}")
    root.parent.mkdir(parents=True, exist_ok=True)
    scaffold = scaffold_design(brief)
    with tempfile.TemporaryDirectory(prefix=f".{root.name}-", dir=root.parent) as temporary:
        staging = Path(temporary) / root.name
        staging.mkdir()
        (staging / ".gitignore").write_text(
            ".research/artifacts/\nraw/\n*.key\n.env\n__pycache__/\n",
            encoding="utf-8",
        )
        (staging / "README.md").write_text(
            "# " + brief["title"] + "\n\n"
            "This is an isolated Research Machine experiment repository. Its draft "
            "artifacts are review material, not evidence or approval. Do not collect "
            "protected data until the canonical protocol is reviewed and frozen.\n",
            encoding="utf-8",
        )
        _write_json(staging / "inputs" / "design-brief.json", brief)
        for name, content in scaffold["artifacts"].items():
            path = staging / "drafts" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, str):
                path.write_text(content, encoding="utf-8")
            else:
                _write_json(path, content)

        service = ResearchService(FileSystemRepository(staging / ".research"), actor=actor)
        service.init_workspace()
        inquiry = service.create_inquiry(
            CreateInquiry(
                title=brief["title"],
                initial_statement=brief["question"],
                decision_to_support=brief["decision"],
                minimum_evidence="[REVIEW REQUIRED] Define the minimum decision-relevant evidence.",
                decision_change_criteria=["[REVIEW REQUIRED] Define what result changes the decision."],
                decision_owner="[REVIEW REQUIRED]",
            )
        )
        for finding in scaffold["findings"]:
            service.add_question(
                AddQuestion(
                    "[Design audit: "
                    + finding["severity"].upper()
                    + "] "
                    + finding["message"]
                    + " Next: "
                    + finding["remediation"]
                ),
                inquiry.inquiry_id,
            )
        proposal = scaffold["artifacts"]["hypothesis-proposal.json"]
        hypothesis = service.propose_hypothesis(
            ProposeHypothesis(
                statement=proposal["statement"],
                generated_by="guided_experiment_scaffold",
                scope=proposal["scope"],
                observable_prediction=proposal["observable_prediction"],
                null_model=proposal["null_model"],
                competing_models=proposal["competing_models"],
                primary_estimand=proposal["primary_estimand"],
                contrast_definition=proposal["contrast_definition"],
                contrast_groups=proposal["contrast_groups"],
                expected_effect_direction=proposal["expected_effect_direction"],
                falsification_conditions=proposal["falsification_conditions"],
            ),
            inquiry.inquiry_id,
        )
        _write_json(
            staging / "experiment-machine.json",
            {
                "status": scaffold["status"],
                "inquiry_id": inquiry.inquiry_id,
                "hypothesis_id": hypothesis.hypothesis_id,
                "hypothesis_state": hypothesis.workflow_state.value,
                "notice": "The hypothesis remains unreviewed. No protocol is frozen and no data are registered.",
            },
        )
        if initialize_git:
            try:
                completed = subprocess.run(
                    ["git", "init", "--quiet", "--initial-branch=main", str(staging)],
                    check=False,
                    capture_output=True,
                    text=True,
                )
            except OSError as exc:
                raise ValidationError(
                    "could not initialize local experiment Git repository: "
                    + str(exc)
                ) from exc
            if completed.returncode != 0:
                raise ValidationError(
                    "could not initialize local experiment Git repository: "
                    + completed.stderr.strip()
                )
        try:
            os.replace(staging, root)
        except OSError as exc:
            raise ValidationError(f"could not create experiment repository atomically: {exc}") from exc
    return {
        "path": str(root),
        "status": scaffold["status"],
        "inquiry_id": inquiry.inquiry_id,
        "hypothesis_id": hypothesis.hypothesis_id,
        "hypothesis_state": hypothesis.workflow_state.value,
        "git_initialized": initialize_git,
        "notice": "Created locally without a network service or LLM. Review drafts before activation, protocol freeze, or collection.",
    }

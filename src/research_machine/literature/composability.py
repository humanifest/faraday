"""Evaluate a typed, source-bound compatibility chain without granting authority."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from research_machine.domain.errors import ValidationError
from research_machine.domain.models import (
    SourceComposabilityArrow,
    SourceComposabilityContract,
    SourceComposabilityNode,
    SourceComposabilityScope,
    SourceComposabilitySourceKind,
    SourceComposabilitySourceReference,
    SourceComposabilityStatus,
)
from research_machine.literature.hashes import require_sha256
from research_machine.literature.json_loading import load_json_object


_CONTRACT_FIELDS = {
    "contract_version",
    "contract_id",
    "development_scope",
    "target_scope",
    "bounded_search_source_ref",
    "target_node_ids",
    "required_arrow_ids",
    "source_references",
    "nodes",
    "required_arrows",
}
_SCOPE_FIELDS = {"signature", "dimension", "carrier", "domain"}
_SOURCE_FIELDS = {
    "source_ref",
    "source_kind",
    "canonical_citation",
    "locator",
    "record_sha256",
}
_NODE_FIELDS = {"node_id", "statement", "scope", "status", "source_refs", "assessment"}
_ARROW_FIELDS = {
    "arrow_id",
    "source_node_id",
    "target_node_id",
    "compatibility_requirement",
    "scope",
    "status",
    "source_refs",
    "assessment",
}
_AUTHORITY_FIELDS = {
    "source_truth_established": False,
    "scientific_validity_established": False,
    "scientific_evidence_eligible": False,
    "replication_authority_established": False,
    "candidate_advancement_eligible": False,
    "runtime_promotion_authorized": False,
    "conclusion_authorized": False,
    "auditor_independence_established": False,
}
_LIMITATIONS = [
    "Statuses and source-to-requirement judgments are declared inputs; Faraday checks their typed structure and custody but does not establish their truth.",
    "A not-found status is limited to the cited bounded-search record and does not establish global absence.",
    "Exact support for individual nodes or arrows does not establish a scientific theory, empirical adequacy, independence, or replication.",
]
_CONCLUSION_CEILING = (
    "Public-development workflow description of declared source composability only; "
    "no scientific, evidence, replication, candidate-advancement, or runtime-promotion authority."
)


def _canonical_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValidationError(
            f"source composability {field} must be canonical non-empty text"
        )
    return value


def _exact_fields(value: Any, expected: set[str], field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValidationError(
            f"source composability {field} fields do not match the documented contract"
        )
    return value


def _canonical_ids(value: Any, field: str, *, minimum: int = 1) -> list[str]:
    if (
        not isinstance(value, list)
        or len(value) < minimum
        or any(not isinstance(item, str) or not item or item != item.strip() for item in value)
        or len(value) != len(set(value))
    ):
        raise ValidationError(
            f"source composability {field} must be a unique ordered array of canonical identifiers"
        )
    return list(value)


def _scope(value: Any, field: str) -> SourceComposabilityScope:
    item = _exact_fields(value, _SCOPE_FIELDS, field)
    return SourceComposabilityScope(
        signature=_canonical_text(item["signature"], f"{field}.signature"),
        dimension=_canonical_text(item["dimension"], f"{field}.dimension"),
        carrier=_canonical_text(item["carrier"], f"{field}.carrier"),
        domain=_canonical_text(item["domain"], f"{field}.domain"),
    )


def _status(value: Any, field: str) -> SourceComposabilityStatus:
    try:
        return SourceComposabilityStatus(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"invalid source composability {field}") from exc


def _source_kind(value: Any, field: str) -> SourceComposabilitySourceKind:
    try:
        return SourceComposabilitySourceKind(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"invalid source composability {field}") from exc


def _parse_contract(specification: dict[str, Any]) -> SourceComposabilityContract:
    value = _exact_fields(specification, _CONTRACT_FIELDS, "contract")
    if value["contract_version"] != 1:
        raise ValidationError("source composability contract_version must be 1")
    if value["development_scope"] != "exposed_evaluator_development":
        raise ValidationError(
            "source composability development_scope must be exposed_evaluator_development"
        )

    target_node_ids = _canonical_ids(value["target_node_ids"], "target_node_ids", minimum=2)
    required_arrow_ids = _canonical_ids(value["required_arrow_ids"], "required_arrow_ids")

    raw_sources = value["source_references"]
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ValidationError("source composability source_references must be a non-empty array")
    sources: list[SourceComposabilitySourceReference] = []
    for index, raw in enumerate(raw_sources):
        item = _exact_fields(raw, _SOURCE_FIELDS, f"source_references[{index}]")
        sources.append(
            SourceComposabilitySourceReference(
                source_ref=_canonical_text(item["source_ref"], f"source_references[{index}].source_ref"),
                source_kind=_source_kind(item["source_kind"], f"source_references[{index}].source_kind"),
                canonical_citation=_canonical_text(item["canonical_citation"], f"source_references[{index}].canonical_citation"),
                locator=_canonical_text(item["locator"], f"source_references[{index}].locator"),
                record_sha256=require_sha256(item["record_sha256"], f"source_references[{index}].record_sha256"),
            )
        )
    source_by_id = {item.source_ref: item for item in sources}
    if len(source_by_id) != len(sources):
        raise ValidationError("source composability source_ref values must be unique")
    bounded_search_source_ref = _canonical_text(
        value["bounded_search_source_ref"], "bounded_search_source_ref"
    )
    bounded_source = source_by_id.get(bounded_search_source_ref)
    if bounded_source is None or bounded_source.source_kind != SourceComposabilitySourceKind.BOUNDED_SEARCH_RECORD:
        raise ValidationError(
            "bounded_search_source_ref must name a bounded_search_record source"
        )

    raw_nodes = value["nodes"]
    if not isinstance(raw_nodes, list):
        raise ValidationError("source composability nodes must be an array")
    nodes: list[SourceComposabilityNode] = []
    for index, raw in enumerate(raw_nodes):
        item = _exact_fields(raw, _NODE_FIELDS, f"nodes[{index}]")
        nodes.append(
            SourceComposabilityNode(
                node_id=_canonical_text(item["node_id"], f"nodes[{index}].node_id"),
                statement=_canonical_text(item["statement"], f"nodes[{index}].statement"),
                scope=_scope(item["scope"], f"nodes[{index}].scope"),
                status=_status(item["status"], f"nodes[{index}].status"),
                source_refs=sorted(
                    _canonical_ids(item["source_refs"], f"nodes[{index}].source_refs")
                ),
                assessment=_canonical_text(item["assessment"], f"nodes[{index}].assessment"),
            )
        )
    node_by_id = {item.node_id: item for item in nodes}
    if len(node_by_id) != len(nodes) or set(node_by_id) != set(target_node_ids):
        raise ValidationError(
            "source composability nodes must define every target_node_id exactly once"
        )

    raw_arrows = value["required_arrows"]
    if not isinstance(raw_arrows, list):
        raise ValidationError("source composability required_arrows must be an array")
    arrows: list[SourceComposabilityArrow] = []
    for index, raw in enumerate(raw_arrows):
        item = _exact_fields(raw, _ARROW_FIELDS, f"required_arrows[{index}]")
        arrows.append(
            SourceComposabilityArrow(
                arrow_id=_canonical_text(item["arrow_id"], f"required_arrows[{index}].arrow_id"),
                source_node_id=_canonical_text(item["source_node_id"], f"required_arrows[{index}].source_node_id"),
                target_node_id=_canonical_text(item["target_node_id"], f"required_arrows[{index}].target_node_id"),
                compatibility_requirement=_canonical_text(item["compatibility_requirement"], f"required_arrows[{index}].compatibility_requirement"),
                scope=_scope(item["scope"], f"required_arrows[{index}].scope"),
                status=_status(item["status"], f"required_arrows[{index}].status"),
                source_refs=sorted(
                    _canonical_ids(
                        item["source_refs"], f"required_arrows[{index}].source_refs"
                    )
                ),
                assessment=_canonical_text(item["assessment"], f"required_arrows[{index}].assessment"),
            )
        )
    arrow_by_id = {item.arrow_id: item for item in arrows}
    if len(arrow_by_id) != len(arrows) or set(arrow_by_id) != set(required_arrow_ids):
        raise ValidationError(
            "source composability required_arrows must define every required_arrow_id exactly once"
        )

    used_nodes: set[str] = set()
    for arrow in arrows:
        if arrow.source_node_id not in node_by_id or arrow.target_node_id not in node_by_id:
            raise ValidationError("source composability arrow endpoints must name target nodes")
        if arrow.source_node_id == arrow.target_node_id:
            raise ValidationError("source composability arrows must connect distinct target nodes")
        used_nodes.update((arrow.source_node_id, arrow.target_node_id))
    if used_nodes != set(target_node_ids):
        raise ValidationError(
            "every source composability target node must participate in a required arrow"
        )

    for label, record in [
        *((f"node {item.node_id}", item) for item in nodes),
        *((f"arrow {item.arrow_id}", item) for item in arrows),
    ]:
        unknown = sorted(set(record.source_refs) - set(source_by_id))
        if unknown:
            raise ValidationError(f"source composability {label} cites unknown source refs: {', '.join(unknown)}")
        kinds = {source_by_id[source_ref].source_kind for source_ref in record.source_refs}
        if record.status == SourceComposabilityStatus.NOT_FOUND_IN_BOUNDED_SEARCH:
            if bounded_search_source_ref not in record.source_refs:
                raise ValidationError(
                    f"source composability {label} not-found status must cite bounded_search_source_ref"
                )
        elif record.status == SourceComposabilityStatus.EXACT_SUPPORT:
            if SourceComposabilitySourceKind.PRIMARY_SOURCE not in kinds:
                raise ValidationError(
                    f"source composability {label} exact support must cite a primary source"
                )
        elif not kinds.intersection(
            {
                SourceComposabilitySourceKind.PRIMARY_SOURCE,
                SourceComposabilitySourceKind.SECONDARY_SOURCE,
            }
        ):
            raise ValidationError(
                f"source composability {label} {record.status.value} must cite a literature source"
            )

    for arrow in arrows:
        if arrow.status == SourceComposabilityStatus.EXACT_SUPPORT and (
            node_by_id[arrow.source_node_id].status != SourceComposabilityStatus.EXACT_SUPPORT
            or node_by_id[arrow.target_node_id].status != SourceComposabilityStatus.EXACT_SUPPORT
        ):
            raise ValidationError(
                f"source composability arrow {arrow.arrow_id} cannot claim exact support when an endpoint is not exactly supported"
            )

    return SourceComposabilityContract(
        contract_version=1,
        contract_id=_canonical_text(value["contract_id"], "contract_id"),
        development_scope="exposed_evaluator_development",
        target_scope=_scope(value["target_scope"], "target_scope"),
        bounded_search_source_ref=bounded_search_source_ref,
        target_node_ids=target_node_ids,
        required_arrow_ids=required_arrow_ids,
        source_references=sorted(sources, key=lambda item: item.source_ref),
        nodes=[node_by_id[node_id] for node_id in target_node_ids],
        required_arrows=[arrow_by_id[arrow_id] for arrow_id in required_arrow_ids],
    )


def _canonical_digest(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _evaluate(contract: SourceComposabilityContract, specification_sha256: str) -> dict[str, Any]:
    exact_nodes = [
        item.to_dict()
        for item in contract.nodes
        if item.status == SourceComposabilityStatus.EXACT_SUPPORT
    ]
    unclosed_arrows = [
        item.to_dict()
        for item in contract.required_arrows
        if item.status != SourceComposabilityStatus.EXACT_SUPPORT
    ]
    chain_closed = not unclosed_arrows
    if chain_closed:
        verdict = "closed_under_declared_exact_support"
    elif exact_nodes:
        verdict = "unclosed_with_exact_local_support"
    else:
        verdict = "unclosed_without_exact_local_support"
    node_counts = Counter(item.status.value for item in contract.nodes)
    arrow_counts = Counter(item.status.value for item in contract.required_arrows)
    status_values = [item.value for item in SourceComposabilityStatus]
    first_unclosed = unclosed_arrows[0] if unclosed_arrows else None
    contract_payload = contract.to_dict()
    return {
        "source_composability_evaluation_version": 1,
        "status": "source_composability_evaluated",
        "development_scope": "exposed_evaluator_development",
        "specification_sha256": specification_sha256,
        "contract_sha256": _canonical_digest(contract_payload),
        "contract": contract_payload,
        "node_status_counts": {key: node_counts.get(key, 0) for key in status_values},
        "arrow_status_counts": {key: arrow_counts.get(key, 0) for key in status_values},
        "chain_closed_under_declared_exact_support": chain_closed,
        "verdict": verdict,
        "locally_supported_node_ids": [item["node_id"] for item in exact_nodes],
        "locally_supported_nodes": exact_nodes,
        "unclosed_required_arrow_ids": [item["arrow_id"] for item in unclosed_arrows],
        "unclosed_required_arrows": unclosed_arrows,
        "first_unclosed_required_arrow_id": first_unclosed["arrow_id"] if first_unclosed else None,
        "first_unclosed_required_arrow": first_unclosed,
        "generic_missing_formula_verdict_permitted": False,
        **_AUTHORITY_FIELDS,
        "limitations": list(_LIMITATIONS),
        "conclusion_ceiling": _CONCLUSION_CEILING,
    }


def validate_source_composability_boundary(evaluation: dict[str, Any]) -> None:
    """Replay every derived field and authority ceiling from the retained contract."""
    if not isinstance(evaluation, dict):
        raise ValidationError("source composability evaluation must be an object")
    specification_sha256 = require_sha256(
        evaluation.get("specification_sha256"), "specification_sha256"
    )
    contract_value = evaluation.get("contract")
    if not isinstance(contract_value, dict):
        raise ValidationError("source composability evaluation requires its retained contract")
    contract = _parse_contract(contract_value)
    expected = _evaluate(contract, specification_sha256)
    if evaluation != expected:
        raise ValidationError(
            "source composability evaluation does not replay from its retained contract"
        )


def create_source_composability_evaluation(
    specification_path: Path,
    expected_specification_sha256: str,
    output: Path,
) -> dict[str, Any]:
    """Create one write-once evaluation from an exact, caller-trusted spec hash."""
    expected = require_sha256(
        expected_specification_sha256, "expected_specification_sha256"
    )
    specification, digest = load_json_object(
        specification_path, "source composability specification"
    )
    if digest != expected:
        raise ValidationError(
            "source composability specification does not match the expected SHA-256"
        )
    contract = _parse_contract(specification)
    evaluation = _evaluate(contract, digest)
    validate_source_composability_boundary(evaluation)

    root = output.expanduser().resolve()
    if root.exists():
        raise ValidationError("source composability output already exists")
    root.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(evaluation, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        + "\n"
    ).encode("utf-8")
    with tempfile.TemporaryDirectory(prefix=".source-composability-", dir=root.parent) as temporary:
        staging = Path(temporary) / "source-composability"
        staging.mkdir()
        (staging / "source-composability-evaluation.json").write_bytes(encoded)
        os.replace(staging, root)
    return {
        "path": str(root),
        "evaluation_sha256": hashlib.sha256(encoded).hexdigest(),
        **evaluation,
    }


def verify_source_composability_evaluation(
    specification_path: Path,
    expected_specification_sha256: str,
    evaluation_path: Path,
    expected_evaluation_sha256: str,
) -> dict[str, Any]:
    """Replay a retained evaluation from the separately retained exact spec bytes."""
    expected_spec = require_sha256(
        expected_specification_sha256, "expected_specification_sha256"
    )
    specification, specification_digest = load_json_object(
        specification_path, "source composability specification"
    )
    if specification_digest != expected_spec:
        raise ValidationError(
            "source composability specification does not match the expected SHA-256"
        )
    expected_evaluation_hash = require_sha256(
        expected_evaluation_sha256, "expected_evaluation_sha256"
    )
    evaluation, evaluation_digest = load_json_object(
        evaluation_path, "source composability evaluation"
    )
    if evaluation_digest != expected_evaluation_hash:
        raise ValidationError(
            "source composability evaluation does not match the expected SHA-256"
        )
    expected_evaluation = _evaluate(_parse_contract(specification), specification_digest)
    validate_source_composability_boundary(evaluation)
    if evaluation != expected_evaluation:
        raise ValidationError(
            "source composability evaluation does not match the retained specification"
        )
    return {
        "status": "source_composability_evaluation_replayed",
        "specification_sha256": specification_digest,
        "evaluation_sha256": evaluation_digest,
        **_AUTHORITY_FIELDS,
        "limitations": list(_LIMITATIONS),
        "conclusion_ceiling": _CONCLUSION_CEILING,
    }

"""Evaluate a typed, source-bound compatibility graph without granting authority."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
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
_NODE_FIELDS = {
    "node_id",
    "statement",
    "scope",
    "status",
    "source_refs",
    "assessment",
}
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
    "source_semantics_established": False,
    "scientific_validity_established": False,
    "scientific_evidence_eligible": False,
    "replication_authority_established": False,
    "candidate_advancement_eligible": False,
    "runtime_promotion_authorized": False,
    "conclusion_authorized": False,
    "assessor_identity_authenticated": False,
    "auditor_independence_established": False,
}
_LIMITATIONS = [
    "Each local source artifact was observed as a regular non-symlink file whose bytes matched its declared SHA-256, but Faraday does not interpret those bytes or validate an internal source schema.",
    "Statuses and source-to-requirement judgments are declared inputs; matching source bytes do not establish those judgments or source semantics.",
    "A not-found status is limited to the cited bounded-search record; Faraday does not establish that the search was complete or exhaustive.",
    "Graph checks establish declared topology and exact signature/dimension equality only; carrier and domain transitions remain explicit human-reviewed arrow content and are not semantically validated.",
    "Exact support for graph members does not establish mathematical composability, assessor identity, a scientific theory, empirical adequacy, independence, or replication.",
]
_CONCLUSION_CEILING = (
    "Public-development workflow description of a declared source-composability graph "
    "with matched local source bytes only; no source-semantic, scientific, evidence, "
    "replication, candidate-advancement, or runtime-promotion authority."
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
        or any(
            not isinstance(item, str) or not item or item != item.strip()
            for item in value
        )
        or len(value) != len(set(value))
    ):
        raise ValidationError(
            f"source composability {field} must be a unique ordered array of "
            "canonical identifiers"
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


def _safe_relative_locator(value: Any, field: str) -> str:
    if isinstance(value, str) and any(
        ord(character) < 32 or ord(character) == 127 for character in value
    ):
        raise ValidationError(
            f"source composability {field} must not contain NUL, newline, or "
            "control characters"
        )
    locator = _canonical_text(value, field)
    if "\\" in locator:
        raise ValidationError(
            f"source composability {field} must use a safe relative POSIX locator"
        )
    path = PurePosixPath(locator)
    if (
        path.is_absolute()
        or path.as_posix() != locator
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValidationError(
            f"source composability {field} must use a safe relative POSIX locator"
        )
    return locator


def _validate_graph_topology(
    target_node_ids: list[str], arrows: list[SourceComposabilityArrow]
) -> None:
    successors = {node_id: [] for node_id in target_node_ids}
    undirected = {node_id: set() for node_id in target_node_ids}
    indegree = {node_id: 0 for node_id in target_node_ids}
    for arrow in arrows:
        successors[arrow.source_node_id].append(arrow.target_node_id)
        undirected[arrow.source_node_id].add(arrow.target_node_id)
        undirected[arrow.target_node_id].add(arrow.source_node_id)
        indegree[arrow.target_node_id] += 1

    visited: set[str] = set()
    pending = [target_node_ids[0]]
    while pending:
        node_id = pending.pop()
        if node_id in visited:
            continue
        visited.add(node_id)
        pending.extend(undirected[node_id] - visited)
    if visited != set(target_node_ids):
        raise ValidationError(
            "source composability required dependency graph must be weakly connected"
        )

    roots = [node_id for node_id in target_node_ids if indegree[node_id] == 0]
    processed = 0
    while roots:
        node_id = roots.pop()
        processed += 1
        for target_id in successors[node_id]:
            indegree[target_id] -= 1
            if indegree[target_id] == 0:
                roots.append(target_id)
    if processed != len(target_node_ids):
        raise ValidationError(
            "source composability required dependency graph must be acyclic"
        )

    position = {node_id: index for index, node_id in enumerate(target_node_ids)}
    if any(
        position[arrow.source_node_id] >= position[arrow.target_node_id]
        for arrow in arrows
    ):
        raise ValidationError(
            "source composability target_node_ids must be a topological order with "
            "each arrow source before its target"
        )


def _parse_contract(specification: dict[str, Any]) -> SourceComposabilityContract:
    value = _exact_fields(specification, _CONTRACT_FIELDS, "contract")
    if isinstance(value["contract_version"], bool) or value["contract_version"] != 1:
        raise ValidationError(
            "source composability contract_version must be integer 1, not Boolean"
        )
    if value["development_scope"] != "exposed_evaluator_development":
        raise ValidationError(
            "source composability development_scope must be "
            "exposed_evaluator_development"
        )

    target_scope = _scope(value["target_scope"], "target_scope")
    target_node_ids = _canonical_ids(
        value["target_node_ids"], "target_node_ids", minimum=2
    )
    required_arrow_ids = _canonical_ids(
        value["required_arrow_ids"], "required_arrow_ids"
    )

    raw_sources = value["source_references"]
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ValidationError(
            "source composability source_references must be a non-empty array"
        )
    sources: list[SourceComposabilitySourceReference] = []
    for index, raw in enumerate(raw_sources):
        item = _exact_fields(raw, _SOURCE_FIELDS, f"source_references[{index}]")
        sources.append(
            SourceComposabilitySourceReference(
                source_ref=_canonical_text(
                    item["source_ref"], f"source_references[{index}].source_ref"
                ),
                source_kind=_source_kind(
                    item["source_kind"], f"source_references[{index}].source_kind"
                ),
                canonical_citation=_canonical_text(
                    item["canonical_citation"],
                    f"source_references[{index}].canonical_citation",
                ),
                locator=_safe_relative_locator(
                    item["locator"], f"source_references[{index}].locator"
                ),
                record_sha256=require_sha256(
                    item["record_sha256"],
                    f"source_references[{index}].record_sha256",
                ),
            )
        )
    source_by_id = {item.source_ref: item for item in sources}
    if len(source_by_id) != len(sources):
        raise ValidationError("source composability source_ref values must be unique")
    bounded_search_source_ref = _canonical_text(
        value["bounded_search_source_ref"], "bounded_search_source_ref"
    )
    bounded_source = source_by_id.get(bounded_search_source_ref)
    if (
        bounded_source is None
        or bounded_source.source_kind
        != SourceComposabilitySourceKind.BOUNDED_SEARCH_RECORD
    ):
        raise ValidationError(
            "bounded_search_source_ref must name a bounded_search_record source"
        )

    raw_nodes = value["nodes"]
    if not isinstance(raw_nodes, list):
        raise ValidationError("source composability nodes must be an array")
    nodes: list[SourceComposabilityNode] = []
    for index, raw in enumerate(raw_nodes):
        item = _exact_fields(raw, _NODE_FIELDS, f"nodes[{index}]")
        node_scope = _scope(item["scope"], f"nodes[{index}].scope")
        if (
            node_scope.signature != target_scope.signature
            or node_scope.dimension != target_scope.dimension
        ):
            raise ValidationError(
                "source composability node signature and dimension must equal "
                "the target scope"
            )
        nodes.append(
            SourceComposabilityNode(
                node_id=_canonical_text(
                    item["node_id"], f"nodes[{index}].node_id"
                ),
                statement=_canonical_text(
                    item["statement"], f"nodes[{index}].statement"
                ),
                scope=node_scope,
                status=_status(item["status"], f"nodes[{index}].status"),
                source_refs=sorted(
                    _canonical_ids(
                        item["source_refs"], f"nodes[{index}].source_refs"
                    )
                ),
                assessment=_canonical_text(
                    item["assessment"], f"nodes[{index}].assessment"
                ),
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
        arrow_scope = _scope(item["scope"], f"required_arrows[{index}].scope")
        if (
            arrow_scope.signature != target_scope.signature
            or arrow_scope.dimension != target_scope.dimension
        ):
            raise ValidationError(
                "source composability arrow signature and dimension must equal "
                "the target scope"
            )
        arrows.append(
            SourceComposabilityArrow(
                arrow_id=_canonical_text(
                    item["arrow_id"], f"required_arrows[{index}].arrow_id"
                ),
                source_node_id=_canonical_text(
                    item["source_node_id"],
                    f"required_arrows[{index}].source_node_id",
                ),
                target_node_id=_canonical_text(
                    item["target_node_id"],
                    f"required_arrows[{index}].target_node_id",
                ),
                compatibility_requirement=_canonical_text(
                    item["compatibility_requirement"],
                    f"required_arrows[{index}].compatibility_requirement",
                ),
                scope=arrow_scope,
                status=_status(
                    item["status"], f"required_arrows[{index}].status"
                ),
                source_refs=sorted(
                    _canonical_ids(
                        item["source_refs"],
                        f"required_arrows[{index}].source_refs",
                    )
                ),
                assessment=_canonical_text(
                    item["assessment"], f"required_arrows[{index}].assessment"
                ),
            )
        )
    arrow_by_id = {item.arrow_id: item for item in arrows}
    if len(arrow_by_id) != len(arrows) or set(arrow_by_id) != set(
        required_arrow_ids
    ):
        raise ValidationError(
            "source composability required_arrows must define every "
            "required_arrow_id exactly once"
        )

    for arrow in arrows:
        if (
            arrow.source_node_id not in node_by_id
            or arrow.target_node_id not in node_by_id
        ):
            raise ValidationError(
                "source composability arrow endpoints must name target nodes"
            )
        if arrow.source_node_id == arrow.target_node_id:
            raise ValidationError(
                "source composability arrows must connect distinct target nodes"
            )
    _validate_graph_topology(target_node_ids, arrows)

    for label, record in [
        *((f"node {item.node_id}", item) for item in nodes),
        *((f"arrow {item.arrow_id}", item) for item in arrows),
    ]:
        unknown = sorted(set(record.source_refs) - set(source_by_id))
        if unknown:
            raise ValidationError(
                f"source composability {label} cites unknown source refs: "
                f"{', '.join(unknown)}"
            )
        kinds = {
            source_by_id[source_ref].source_kind for source_ref in record.source_refs
        }
        if record.status == SourceComposabilityStatus.NOT_FOUND_IN_BOUNDED_SEARCH:
            if bounded_search_source_ref not in record.source_refs:
                raise ValidationError(
                    f"source composability {label} not-found status must cite "
                    "bounded_search_source_ref"
                )
        elif record.status == SourceComposabilityStatus.EXACT_SUPPORT:
            if SourceComposabilitySourceKind.PRIMARY_SOURCE not in kinds:
                raise ValidationError(
                    f"source composability {label} exact support must cite a "
                    "primary source"
                )
        elif not kinds.intersection(
            {
                SourceComposabilitySourceKind.PRIMARY_SOURCE,
                SourceComposabilitySourceKind.SECONDARY_SOURCE,
            }
        ):
            raise ValidationError(
                f"source composability {label} {record.status.value} must cite "
                "a literature source"
            )

    for arrow in arrows:
        if arrow.status == SourceComposabilityStatus.EXACT_SUPPORT and (
            node_by_id[arrow.source_node_id].status
            != SourceComposabilityStatus.EXACT_SUPPORT
            or node_by_id[arrow.target_node_id].status
            != SourceComposabilityStatus.EXACT_SUPPORT
        ):
            raise ValidationError(
                f"source composability arrow {arrow.arrow_id} cannot claim exact "
                "support when an endpoint is not exactly supported"
            )

    return SourceComposabilityContract(
        contract_version=1,
        contract_id=_canonical_text(value["contract_id"], "contract_id"),
        development_scope="exposed_evaluator_development",
        target_scope=target_scope,
        bounded_search_source_ref=bounded_search_source_ref,
        target_node_ids=target_node_ids,
        required_arrow_ids=required_arrow_ids,
        source_references=sorted(sources, key=lambda item: item.source_ref),
        nodes=[node_by_id[node_id] for node_id in target_node_ids],
        required_arrows=[arrow_by_id[arrow_id] for arrow_id in required_arrow_ids],
    )


def _canonical_digest(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _required_open_flag(name: str) -> int:
    value = getattr(os, name, None)
    if not isinstance(value, int):
        raise ValidationError(
            f"source composability requires operating-system {name} support "
            "to enforce no-follow descriptor custody"
        )
    return value


def _open_trusted_source_root(source_artifact_root: Path) -> int:
    no_follow = _required_open_flag("O_NOFOLLOW")
    directory = _required_open_flag("O_DIRECTORY")
    candidate = source_artifact_root.expanduser()
    try:
        metadata = candidate.lstat()
    except OSError as exc:
        raise ValidationError(
            "source composability source artifact root is missing or unreadable"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValidationError(
            "source composability source artifact root must be a non-symlink directory"
        )
    flags = os.O_RDONLY | directory | no_follow
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        descriptor = os.open(candidate, flags)
    except OSError as exc:
        raise ValidationError(
            "source composability source artifact root could not be opened safely"
        ) from exc
    if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise ValidationError(
            "source composability source artifact root must be a non-symlink directory"
        )
    return descriptor


def _observe_source_file(
    root_descriptor: int, source: SourceComposabilitySourceReference
) -> dict[str, Any]:
    relative = PurePosixPath(source.locator)
    no_follow = _required_open_flag("O_NOFOLLOW")
    directory = _required_open_flag("O_DIRECTORY")
    directory_flags = os.O_RDONLY | directory | no_follow
    if hasattr(os, "O_CLOEXEC"):
        directory_flags |= os.O_CLOEXEC
    file_flags = os.O_RDONLY | no_follow
    if hasattr(os, "O_CLOEXEC"):
        file_flags |= os.O_CLOEXEC
    opened_directories: list[int] = []
    try:
        parent_descriptor = root_descriptor
        for part in relative.parts[:-1]:
            parent_descriptor = os.open(
                part, directory_flags, dir_fd=parent_descriptor
            )
            opened_directories.append(parent_descriptor)
        descriptor = os.open(
            relative.parts[-1], file_flags, dir_fd=parent_descriptor
        )
        with os.fdopen(descriptor, "rb") as handle:
            opened = os.fstat(handle.fileno())
            if not stat.S_ISREG(opened.st_mode):
                raise ValidationError(
                    f"source composability artifact must be a regular file: "
                    f"{source.locator}"
                )
            digest = hashlib.sha256()
            size = 0
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
            observed = digest.hexdigest()
            closed = os.fstat(handle.fileno())
    except ValidationError:
        raise
    except OSError as exc:
        raise ValidationError(
            "source composability artifact is missing, non-regular, symlinked, "
            f"or unreadable beneath its trusted root: {source.locator}"
        ) from exc
    finally:
        for directory_descriptor in reversed(opened_directories):
            os.close(directory_descriptor)
    if (
        opened.st_dev != closed.st_dev
        or opened.st_ino != closed.st_ino
        or opened.st_size != closed.st_size
        or opened.st_mtime_ns != closed.st_mtime_ns
        or opened.st_ctime_ns != closed.st_ctime_ns
    ):
        raise ValidationError(
            f"source composability artifact changed while hashing: {source.locator}"
        )
    if observed != source.record_sha256:
        raise ValidationError(
            f"source composability artifact SHA-256 mismatch: {source.locator}"
        )
    return {
        "source_ref": source.source_ref,
        "source_kind": source.source_kind.value,
        "locator": source.locator,
        "expected_sha256": source.record_sha256,
        "observed_sha256": observed,
        "observed_size_bytes": size,
        "status": "matched",
    }


def _observe_source_artifacts(
    contract: SourceComposabilityContract, source_artifact_root: Path
) -> list[dict[str, Any]]:
    root_descriptor = _open_trusted_source_root(source_artifact_root)
    try:
        return [
            _observe_source_file(root_descriptor, source)
            for source in contract.source_references
        ]
    finally:
        os.close(root_descriptor)


def _evaluate(
    contract: SourceComposabilityContract,
    specification_sha256: str,
    source_artifact_receipts: list[dict[str, Any]],
) -> dict[str, Any]:
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
    graph_fully_supported = not unclosed_arrows
    if graph_fully_supported:
        verdict = "required_graph_fully_supported_under_declared_exact_support"
    elif exact_nodes:
        verdict = "required_graph_has_unclosed_arrows_with_exact_node_support"
    else:
        verdict = "required_graph_has_unclosed_arrows_without_exact_node_support"
    node_counts = Counter(item.status.value for item in contract.nodes)
    arrow_counts = Counter(item.status.value for item in contract.required_arrows)
    status_values = [item.value for item in SourceComposabilityStatus]
    first_unclosed = unclosed_arrows[0] if unclosed_arrows else None
    contract_payload = contract.to_dict()
    return {
        "source_composability_evaluation_version": 2,
        "status": "source_composability_graph_evaluated",
        "development_scope": "exposed_evaluator_development",
        "specification_sha256": specification_sha256,
        "contract_sha256": _canonical_digest(contract_payload),
        "contract": contract_payload,
        "source_artifact_byte_custody_status": "all_declared_source_bytes_matched",
        "source_artifact_receipts": source_artifact_receipts,
        "graph_topology": {
            "weakly_connected": True,
            "acyclic": True,
            "target_node_ids_topological": True,
        },
        "node_status_counts": {
            key: node_counts.get(key, 0) for key in status_values
        },
        "arrow_status_counts": {
            key: arrow_counts.get(key, 0) for key in status_values
        },
        "required_graph_fully_supported_under_declared_exact_support": (
            graph_fully_supported
        ),
        "verdict": verdict,
        "exactly_supported_node_ids": [item["node_id"] for item in exact_nodes],
        "exactly_supported_nodes": exact_nodes,
        "unclosed_required_arrow_ids": [
            item["arrow_id"] for item in unclosed_arrows
        ],
        "unclosed_required_arrows": unclosed_arrows,
        "first_unclosed_required_arrow_id": (
            first_unclosed["arrow_id"] if first_unclosed else None
        ),
        "first_unclosed_required_arrow": first_unclosed,
        "generic_missing_formula_verdict_permitted": False,
        **_AUTHORITY_FIELDS,
        "limitations": list(_LIMITATIONS),
        "conclusion_ceiling": _CONCLUSION_CEILING,
    }


def validate_source_composability_boundary(
    evaluation: dict[str, Any], source_artifact_root: Path
) -> None:
    """Re-hash sources and replay every derived field and authority ceiling."""
    if not isinstance(evaluation, dict):
        raise ValidationError("source composability evaluation must be an object")
    specification_sha256 = require_sha256(
        evaluation.get("specification_sha256"), "specification_sha256"
    )
    contract_value = evaluation.get("contract")
    if not isinstance(contract_value, dict):
        raise ValidationError(
            "source composability evaluation requires its retained contract"
        )
    contract = _parse_contract(contract_value)
    receipts = _observe_source_artifacts(contract, source_artifact_root)
    expected = _evaluate(contract, specification_sha256, receipts)
    if evaluation != expected:
        raise ValidationError(
            "source composability evaluation does not replay from its retained "
            "contract and source artifacts"
        )


def _write_output_file(descriptor: int, encoded: bytes) -> None:
    """Write and sync bytes while the caller retains descriptor ownership."""
    with os.fdopen(descriptor, "wb", closefd=False) as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


def _parent_entry_matches_reservation(
    parent_descriptor: int, entry_name: str, reserved_metadata: os.stat_result
) -> bool:
    try:
        observed = os.stat(
            entry_name, dir_fd=parent_descriptor, follow_symlinks=False
        )
    except OSError:
        return False
    return (
        stat.S_ISDIR(observed.st_mode)
        and not stat.S_ISLNK(observed.st_mode)
        and observed.st_dev == reserved_metadata.st_dev
        and observed.st_ino == reserved_metadata.st_ino
    )


def _reserve_and_write_output(root: Path, encoded: bytes) -> None:
    no_follow = _required_open_flag("O_NOFOLLOW")
    directory = _required_open_flag("O_DIRECTORY")
    close_on_exec = getattr(os, "O_CLOEXEC", 0)
    root.parent.mkdir(parents=True, exist_ok=True)
    parent_descriptor: int | None = None
    reserved_descriptor: int | None = None
    output_descriptor: int | None = None
    try:
        parent_descriptor = os.open(
            root.parent,
            os.O_RDONLY | directory | no_follow | close_on_exec,
        )
        try:
            os.mkdir(root.name, dir_fd=parent_descriptor)
        except FileExistsError as exc:
            raise ValidationError(
                "source composability output already exists"
            ) from exc
        reserved_descriptor = os.open(
            root.name,
            os.O_RDONLY | directory | no_follow | close_on_exec,
            dir_fd=parent_descriptor,
        )
        reserved_metadata = os.fstat(reserved_descriptor)
        if not stat.S_ISDIR(reserved_metadata.st_mode):
            raise ValidationError(
                "source composability reserved output is not a directory"
            )
        os.fsync(parent_descriptor)

        output_descriptor = os.open(
            "source-composability-evaluation.json",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | no_follow | close_on_exec,
            0o644,
            dir_fd=reserved_descriptor,
        )
        _write_output_file(output_descriptor, encoded)
        os.close(output_descriptor)
        output_descriptor = None
        os.fsync(reserved_descriptor)
        os.fsync(parent_descriptor)

        if not _parent_entry_matches_reservation(
            parent_descriptor, root.name, reserved_metadata
        ):
            raise ValidationError(
                "source composability output parent entry no longer names the "
                "reserved non-symlink directory"
            )
    except ValidationError:
        raise
    except OSError as exc:
        raise ValidationError(
            "source composability output write failed after fail-closed reservation"
        ) from exc
    finally:
        if output_descriptor is not None:
            os.close(output_descriptor)
        if reserved_descriptor is not None:
            os.close(reserved_descriptor)
        if parent_descriptor is not None:
            os.close(parent_descriptor)


def create_source_composability_evaluation(
    specification_path: Path,
    expected_specification_sha256: str,
    source_artifact_root: Path,
    output: Path,
) -> dict[str, Any]:
    """Create one write-once evaluation from trusted spec and source paths."""
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
    receipts = _observe_source_artifacts(contract, source_artifact_root)
    evaluation = _evaluate(contract, digest, receipts)
    validate_source_composability_boundary(evaluation, source_artifact_root)

    root = Path(os.path.abspath(os.fspath(output.expanduser())))
    encoded = (
        json.dumps(
            evaluation,
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    _reserve_and_write_output(root, encoded)
    return {
        "path": str(root),
        "evaluation_sha256": hashlib.sha256(encoded).hexdigest(),
        **evaluation,
    }


def verify_source_composability_evaluation(
    specification_path: Path,
    expected_specification_sha256: str,
    source_artifact_root: Path,
    evaluation_path: Path,
    expected_evaluation_sha256: str,
) -> dict[str, Any]:
    """Re-hash sources and replay an evaluation from exact retained artifacts."""
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
    contract = _parse_contract(specification)
    receipts = _observe_source_artifacts(contract, source_artifact_root)
    expected_evaluation = _evaluate(contract, specification_digest, receipts)
    validate_source_composability_boundary(evaluation, source_artifact_root)
    if evaluation != expected_evaluation:
        raise ValidationError(
            "source composability evaluation does not match the retained "
            "specification and source artifacts"
        )
    return {
        "status": "source_composability_graph_evaluation_replayed",
        "specification_sha256": specification_digest,
        "evaluation_sha256": evaluation_digest,
        "source_artifact_byte_custody_status": (
            "all_declared_source_bytes_matched"
        ),
        "source_artifact_receipts": receipts,
        **_AUTHORITY_FIELDS,
        "limitations": list(_LIMITATIONS),
        "conclusion_ceiling": _CONCLUSION_CEILING,
    }

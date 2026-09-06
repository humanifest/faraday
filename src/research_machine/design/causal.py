"""Deterministic causal-DAG checks; graph assumptions remain researcher claims."""
from __future__ import annotations

from collections import deque
from itertools import combinations
from typing import Any

from research_machine.domain.errors import ValidationError

COMMON_CAUSAL_ASSUMPTIONS = {
    "positivity",
    "consistency",
    "interference",
    "temporal_order",
    "measurement_validity",
    "selection_bias",
}
ASSIGNMENT_CAUSAL_ASSUMPTIONS = {
    "observational": {"exchangeability"},
    "randomized": {"allocation_integrity"},
}
CAUSAL_ASSUMPTION_CATEGORIES = frozenset(
    COMMON_CAUSAL_ASSUMPTIONS | {"exchangeability", "allocation_integrity"}
)
CAUSAL_ASSESSMENT_KINDS = frozenset({
    "empirical_diagnostic", "design_record_review", "external_validation",
    "substantive_judgment",
})


def _node_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be non-blank text")
    return value.strip()


def audit_causal_identification(spec: dict[str, Any]) -> dict[str, Any]:
    """Audit one claimed DAG and adjustment set against the backdoor criterion."""
    if not isinstance(spec, dict):
        raise ValidationError("causal identification specification must be an object")
    allowed = {"nodes", "edges", "exposure", "outcome", "proposed_adjustment_set", "assignment_type", "assumptions", "causal_estimand"}
    unknown = sorted(set(spec) - allowed)
    if unknown:
        raise ValidationError("unknown causal identification fields: " + ", ".join(unknown))
    raw_nodes = spec.get("nodes")
    if not isinstance(raw_nodes, list) or len(raw_nodes) < 2:
        raise ValidationError("nodes must contain at least two node objects")
    observed: dict[str, bool] = {}
    for index, item in enumerate(raw_nodes):
        if not isinstance(item, dict) or set(item) != {"id", "observed"} or type(item.get("observed")) is not bool:
            raise ValidationError(f"nodes[{index}] must contain exactly id and boolean observed")
        identifier = _node_id(item["id"], f"nodes[{index}].id")
        if identifier in observed:
            raise ValidationError(f"duplicate causal node: {identifier}")
        observed[identifier] = item["observed"]
    exposure = _node_id(spec.get("exposure"), "exposure")
    outcome = _node_id(spec.get("outcome"), "outcome")
    if exposure == outcome or exposure not in observed or outcome not in observed:
        raise ValidationError("exposure and outcome must be distinct declared nodes")
    assignment = spec.get("assignment_type")
    if assignment not in {"observational", "randomized"}:
        raise ValidationError("assignment_type must be observational or randomized")
    raw_assumptions = spec.get("assumptions", [])
    if not isinstance(raw_assumptions, list):
        raise ValidationError("assumptions must be an array")
    assumptions: list[dict[str, str]] = []
    seen_assumptions: set[str] = set()
    for index, item in enumerate(raw_assumptions):
        required_fields = {"category", "statement", "assessment_kind", "assessment_plan", "failure_response", "assessment_gate_id"}
        if not isinstance(item, dict) or set(item) != required_fields:
            raise ValidationError(
                f"assumptions[{index}] must contain exactly category, statement, assessment_kind, assessment_plan, failure_response, and assessment_gate_id"
            )
        category = _node_id(item["category"], f"assumptions[{index}].category")
        if category not in CAUSAL_ASSUMPTION_CATEGORIES:
            raise ValidationError(f"unsupported causal assumption category: {category}")
        if category in seen_assumptions:
            raise ValidationError(f"duplicate causal assumption category: {category}")
        seen_assumptions.add(category)
        assessment_kind = _node_id(
            item["assessment_kind"], f"assumptions[{index}].assessment_kind"
        )
        if assessment_kind not in CAUSAL_ASSESSMENT_KINDS:
            raise ValidationError(
                f"unsupported causal assessment kind: {assessment_kind}"
            )
        assumptions.append({
            "category": category,
            "statement": _node_id(item["statement"], f"assumptions[{index}].statement"),
            "assessment_kind": assessment_kind,
            "assessment_plan": _node_id(item["assessment_plan"], f"assumptions[{index}].assessment_plan"),
            "failure_response": _node_id(item["failure_response"], f"assumptions[{index}].failure_response"),
            "assessment_gate_id": _node_id(item["assessment_gate_id"], f"assumptions[{index}].assessment_gate_id"),
        })
    raw_estimand = spec.get("causal_estimand")
    estimand_fields = {
        "target_hypothesis_id", "description", "population", "exposure_strategies",
        "outcome_variable", "time_zero", "outcome_time", "contrast",
        "summary_measure", "intercurrent_events_policy",
    }
    causal_estimand: dict[str, Any] | None = None
    if raw_estimand is not None:
        if not isinstance(raw_estimand, dict) or set(raw_estimand) != estimand_fields:
            raise ValidationError(
                "causal_estimand must contain exactly target_hypothesis_id, description, population, exposure_strategies, outcome_variable, time_zero, outcome_time, contrast, summary_measure, and intercurrent_events_policy"
            )
        strategies = raw_estimand["exposure_strategies"]
        if (
            not isinstance(strategies, list)
            or len(strategies) != 2
            or any(not isinstance(item, str) or not item.strip() for item in strategies)
            or len({item.strip() for item in strategies}) != 2
        ):
            raise ValidationError("causal_estimand.exposure_strategies must contain exactly two distinct non-blank strategies")
        causal_estimand = {
            field: _node_id(raw_estimand[field], f"causal_estimand.{field}")
            for field in estimand_fields - {"exposure_strategies"}
        }
        causal_estimand["exposure_strategies"] = [item.strip() for item in strategies]
    raw_edges = spec.get("edges")
    if not isinstance(raw_edges, list):
        raise ValidationError("edges must be an array")
    children = {node: set() for node in observed}
    parents = {node: set() for node in observed}
    edges: set[tuple[str, str]] = set()
    for index, item in enumerate(raw_edges):
        if not isinstance(item, dict) or set(item) != {"cause", "effect"}:
            raise ValidationError(f"edges[{index}] must contain exactly cause and effect")
        cause = _node_id(item["cause"], f"edges[{index}].cause")
        effect = _node_id(item["effect"], f"edges[{index}].effect")
        if cause not in observed or effect not in observed or cause == effect:
            raise ValidationError("every causal edge must connect two distinct declared nodes")
        if (cause, effect) in edges:
            raise ValidationError("causal edges must be unique")
        edges.add((cause, effect))
        children[cause].add(effect)
        parents[effect].add(cause)
    indegree = {node: len(parents[node]) for node in observed}
    queue = deque(sorted(node for node, degree in indegree.items() if degree == 0))
    visited = []
    while queue:
        node = queue.popleft()
        visited.append(node)
        for child in sorted(children[node]):
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    if len(visited) != len(observed):
        raise ValidationError("causal graph must be acyclic")
    adjustment = spec.get("proposed_adjustment_set", [])
    if not isinstance(adjustment, list):
        raise ValidationError("proposed_adjustment_set must be an array")
    adjustment = [_node_id(item, "proposed_adjustment_set item") for item in adjustment]
    if len(set(adjustment)) != len(adjustment) or any(item not in observed for item in adjustment):
        raise ValidationError("proposed_adjustment_set must contain unique declared nodes")
    if exposure in adjustment or outcome in adjustment:
        raise ValidationError("the exposure and outcome cannot be adjustment variables")
    unobserved = sorted(item for item in adjustment if not observed[item])

    descendants: set[str] = set()
    frontier = list(children[exposure])
    while frontier:
        node = frontier.pop()
        if node not in descendants:
            descendants.add(node)
            frontier.extend(children[node])
    post_treatment = sorted(set(adjustment) & descendants)

    # Backdoor graph G_X removes arrows out of X. D-separation is tested by
    # ancestral moralization, then deletion of the proposed conditioning set.
    backdoor_parents = {node: set(values) for node, values in parents.items()}
    for child in children[exposure]:
        backdoor_parents[child].discard(exposure)
    def open_path(conditioning: list[str]) -> list[str]:
        ancestors = {exposure, outcome, *conditioning}
        frontier = list(ancestors)
        while frontier:
            node = frontier.pop()
            for parent in backdoor_parents[node]:
                if parent not in ancestors:
                    ancestors.add(parent)
                    frontier.append(parent)
        moral = {node: set() for node in ancestors}
        for child in ancestors:
            ps = sorted(backdoor_parents[child] & ancestors)
            for parent in ps:
                moral[parent].add(child)
                moral[child].add(parent)
            for index, first in enumerate(ps):
                for second in ps[index + 1:]:
                    moral[first].add(second)
                    moral[second].add(first)
        blocked = set(conditioning)
        path: list[str] = []
        pending = deque([exposure])
        previous: dict[str, str | None] = {exposure: None}
        while pending and outcome not in previous:
            node = pending.popleft()
            for neighbor in sorted(moral[node] - blocked):
                if neighbor not in previous:
                    previous[neighbor] = node
                    pending.append(neighbor)
        if outcome in previous:
            cursor: str | None = outcome
            while cursor is not None:
                path.append(cursor)
                cursor = previous[cursor]
            path.reverse()
        return path

    path = open_path(adjustment)
    d_separated = not path
    violations = []
    if causal_estimand is None:
        violations.append({
            "code": "ESTIMAND_MISSING",
            "nodes": [],
            "message": "The causal target is not defined as a structured estimand.",
        })
    elif causal_estimand["outcome_variable"] != outcome:
        violations.append({
            "code": "ESTIMAND_OUTCOME_MISMATCH",
            "nodes": [causal_estimand["outcome_variable"], outcome],
            "message": "The causal estimand outcome_variable must exactly match the DAG outcome identifier.",
        })
    unobserved_targets = sorted(
        node for node in (exposure, outcome) if not observed[node]
    )
    if unobserved_targets:
        violations.append({
            "code": "UNOBSERVED_EXPOSURE_OR_OUTCOME",
            "nodes": unobserved_targets,
            "message": "The registered exposure and outcome must be observed for this estimable causal contrast.",
        })
    required_assumptions = COMMON_CAUSAL_ASSUMPTIONS | ASSIGNMENT_CAUSAL_ASSUMPTIONS[assignment]
    missing_assumptions = sorted(required_assumptions - seen_assumptions)
    if missing_assumptions:
        violations.append({
            "code": "ASSUMPTIONS_INCOMPLETE",
            "nodes": missing_assumptions,
            "message": "The causal assumption register is missing required categories: " + ", ".join(missing_assumptions) + ".",
        })
    inapplicable = sorted(
        ({"allocation_integrity"} if assignment == "observational" else {"exchangeability"})
        & seen_assumptions
    )
    if inapplicable:
        violations.append({
            "code": "ASSUMPTION_ASSIGNMENT_CONFLICT",
            "nodes": inapplicable,
            "message": "The assumption register contains a category inconsistent with the declared assignment type.",
        })
    if unobserved:
        violations.append({"code": "UNOBSERVED_ADJUSTMENT", "nodes": unobserved,
                           "message": "The proposed adjustment set contains variables declared unobserved."})
    if post_treatment:
        violations.append({"code": "POST_TREATMENT_ADJUSTMENT", "nodes": post_treatment,
                           "message": "The proposed set contains descendants of the exposure; mediation or collider bias requires review."})
    if assignment == "observational" and not d_separated:
        violations.append({"code": "OPEN_BACKDOOR_PATH", "nodes": path,
                           "message": "The proposed set does not d-separate exposure and outcome in the backdoor graph."})
    if assignment == "randomized" and parents[exposure]:
        violations.append({"code": "RANDOMIZATION_GRAPH_CONFLICT", "nodes": sorted(parents[exposure]),
                           "message": "The supplied DAG gives the randomized exposure causal parents; reconcile assignment and graph assumptions."})
    identified = (
        assignment == "observational"
        and d_separated
        and not unobserved
        and not post_treatment
    )
    candidate_nodes = sorted(
        node for node, is_observed in observed.items()
        if is_observed and node not in descendants | {exposure, outcome}
    )
    minimal_sets: list[list[str]] = []
    if assignment == "randomized":
        enumeration_status = "not_applicable_randomized"
    elif len(candidate_nodes) > 16:
        enumeration_status = "not_enumerated_more_than_16_observed_candidates"
    else:
        enumeration_status = "complete"
        stop = False
        for size in range(len(candidate_nodes) + 1):
            for candidate in combinations(candidate_nodes, size):
                candidate_set = set(candidate)
                if any(set(existing) <= candidate_set for existing in minimal_sets):
                    continue
                if not open_path(list(candidate)):
                    minimal_sets.append(list(candidate))
                    if len(minimal_sets) == 100:
                        enumeration_status = "truncated_at_100_minimal_sets"
                        stop = True
                        break
            if stop:
                break
    return {
        "status": "review_required" if not violations else "blocked",
        "assignment_type": assignment,
        "exposure": exposure,
        "outcome": outcome,
        "proposed_adjustment_set": adjustment,
        "assumption_register": assumptions,
        "causal_estimand": causal_estimand,
        "required_assumption_categories": sorted(required_assumptions),
        "missing_assumption_categories": missing_assumptions,
        "backdoor_criterion_satisfied": identified if assignment == "observational" else None,
        "open_backdoor_connectivity_witness": path,
        "minimal_observed_adjustment_sets": minimal_sets,
        "adjustment_set_enumeration_status": enumeration_status,
        "violations": violations,
        "topological_order": visited,
        "scientific_evidence_eligible": False,
        "claim_ceiling": (
            "Graph-internal identification audit only. Passing means the proposed set satisfies the backdoor criterion in the supplied DAG; "
            "it does not establish that the DAG or registered assumptions are true, variables are measured without error, positivity holds, assignment was randomized, or a causal effect was estimated."
        ),
    }

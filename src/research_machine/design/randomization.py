"""Deterministic assignment generation; never a substitute for concealment."""
from __future__ import annotations

import hashlib
import json
import random
from typing import Any

from research_machine.domain.errors import ValidationError


def generate_blocked_assignment(spec: dict[str, Any]) -> dict[str, Any]:
    allowed = {"unit_ids", "groups", "block_size", "seed", "strata"}
    unknown = sorted(set(spec) - allowed)
    if unknown:
        raise ValidationError("unknown randomization fields: " + ", ".join(unknown))
    units, groups = spec.get("unit_ids"), spec.get("groups")
    for value, name, minimum in ((units, "unit_ids", 2), (groups, "groups", 2)):
        if not isinstance(value, list) or len(value) < minimum or any(
            not isinstance(item, str) or not item.strip() for item in value
        ):
            raise ValidationError(f"{name} must be an array of at least {minimum} non-blank strings")
        normalized = [item.strip() for item in value]
        if len(set(normalized)) != len(normalized):
            raise ValidationError(f"{name} must be unique after trimming whitespace")
    units = [item.strip() for item in units]
    groups = [item.strip() for item in groups]
    block_size, seed = spec.get("block_size"), spec.get("seed")
    if type(block_size) is not int or block_size < len(groups) or block_size % len(groups):
        raise ValidationError("block_size must be an integer at least the group count and divisible by it")
    if type(seed) is not int:
        raise ValidationError("seed must be an integer")
    strata = spec.get("strata")
    if strata is None:
        units_by_stratum: list[tuple[str | None, list[str]]] = [(None, units)]
    else:
        if not isinstance(strata, dict) or set(strata) != set(units) or any(
            not isinstance(value, str) or not value.strip() for value in strata.values()
        ):
            raise ValidationError("strata must map every normalized unit_id exactly once to a non-blank stratum")
        units_by_stratum = []
        positions: dict[str, int] = {}
        for unit in units:
            stratum = strata[unit].strip()
            if stratum not in positions:
                positions[stratum] = len(units_by_stratum)
                units_by_stratum.append((stratum, []))
            units_by_stratum[positions[stratum]][1].append(unit)
    incomplete = [stratum or "unstratified" for stratum, members in units_by_stratum
                  if len(members) % block_size]
    if incomplete:
        raise ValidationError("each stratum's unit count must be divisible by block_size; unresolved strata: " + ", ".join(incomplete))
    rng = random.Random(seed)
    assignments = []
    repeats = block_size // len(groups)
    global_block = 0
    for stratum, members in units_by_stratum:
        for start in range(0, len(members), block_size):
            global_block += 1
            labels = groups * repeats
            rng.shuffle(labels)
            for unit, group in zip(members[start:start + block_size], labels):
                row = {"unit_id": unit, "group": group, "block": global_block}
                if stratum is not None:
                    row["stratum"] = stratum
                    row["block_within_stratum"] = start // block_size + 1
                assignments.append(row)
    canonical = json.dumps(assignments, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    allocation = sorted(
        ({"unit_id": item["unit_id"], "group": item["group"]} for item in assignments),
        key=lambda item: item["unit_id"],
    )
    allocation_bytes = json.dumps(allocation, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return {
        "method": "stratified_fixed_permuted_blocks" if strata is not None else "fixed_permuted_blocks",
        "seed": seed, "groups": groups,
        "block_size": block_size, "unit_count": len(units), "assignments": assignments,
        "assignment_sha256": hashlib.sha256(canonical).hexdigest(),
        "allocation_sha256": hashlib.sha256(allocation_bytes).hexdigest(),
        "balance": {group: sum(item["group"] == group for item in assignments) for group in groups},
        "balance_by_stratum": ({stratum: {group: sum(
            item["stratum"] == stratum and item["group"] == group for item in assignments
        ) for group in groups} for stratum, _ in units_by_stratum} if strata is not None else None),
        "scientific_evidence_eligible": False,
        "limitations": [
            "The supplied unit order is part of the assignment procedure and must be fixed before generation.",
            "A disclosed seed and fixed block size can make assignments predictable; this output does not establish allocation concealment or blinding.",
            "Stratification can balance supplied strata; it does not eliminate confounding within strata, validate stratum definitions, authenticate enrollment order, or prove adherence.",
        ],
    }

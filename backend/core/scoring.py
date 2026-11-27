"""Shared soft-constraint scoring for every scheduling method.

The scorer intentionally uses plain JSON-style mappings so classical solvers,
quantum solvers, and the API can all use the same function without adapters.
See ``docs/soft-scoring.md`` for the input contract and scoring policy.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import combinations
from typing import Any, Mapping, Sequence


DEFAULT_WEIGHTS: dict[str, float] = {"s1": 1.0, "s2": 1.0, "s3": 1.0}


@dataclass(frozen=True)
class SoftScore:
    """Visible score breakdown shared by all solver results."""

    same_day_pairs: int
    average_unused_seat_proportion: float
    teacher_preference_violations: int
    weighted_total: float
    weights: dict[str, float]

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-ready representation for API and solver responses."""
        return asdict(self)


def score_soft_constraints(
    case: Mapping[str, Any],
    timetable: Mapping[str, Mapping[str, Any]] | Sequence[Mapping[str, Any]],
    *,
    weights: Mapping[str, float] | None = None,
) -> SoftScore:
    """Score a complete timetable against the three shared soft constraints.

    ``case`` contains ``exams``, ``rooms``, and ``slots``.  A timetable may be
    either ``{exam_id: {slot_id, room_id}}`` or a list of assignment objects
    containing ``exam_id``, ``slot_id``, and ``room_id``.  Invalid or incomplete
    schedules are deliberately rejected here: hard-constraint validation belongs
    to the shared validator, while this scorer only evaluates valid schedules.
    """
    resolved_weights = _resolve_weights(weights)
    exams = _index_by_id(case.get("exams", []), "exam")
    rooms = _index_by_id(case.get("rooms", []), "room")
    slots = _index_by_id(case.get("slots", []), "slot")
    assignments = _normalise_assignments(timetable)

    if set(assignments) != set(exams):
        raise ValueError("timetable must contain exactly one assignment for every exam")

    _validate_assignment_references(assignments, rooms, slots)

    s1 = _same_day_pairs(exams, assignments, slots)
    s2 = _average_unused_seat_proportion(exams, assignments, rooms)
    s3 = _teacher_preference_violations(case, exams, assignments)
    total = (
        resolved_weights["s1"] * s1
        + resolved_weights["s2"] * s2
        + resolved_weights["s3"] * s3
    )
    return SoftScore(s1, s2, s3, total, resolved_weights)


def _resolve_weights(weights: Mapping[str, float] | None) -> dict[str, float]:
    resolved = dict(DEFAULT_WEIGHTS)
    if weights is not None:
        unknown = set(weights) - set(resolved)
        if unknown:
            raise ValueError(f"unknown soft-score weights: {sorted(unknown)}")
        resolved.update(weights)
    if any(value < 0 for value in resolved.values()):
        raise ValueError("soft-score weights must be non-negative")
    return resolved


def _index_by_id(items: Sequence[Any], item_name: str) -> dict[str, Mapping[str, Any]]:
    indexed: dict[str, Mapping[str, Any]] = {}
    for item in items:
        if isinstance(item, str):
            item = {"id": item}
        if not isinstance(item, Mapping) or not isinstance(item.get("id"), str):
            raise ValueError(f"each {item_name} must have a string id")
        if item["id"] in indexed:
            raise ValueError(f"duplicate {item_name} id: {item['id']}")
        indexed[item["id"]] = item
    return indexed


def _normalise_assignments(
    timetable: Mapping[str, Mapping[str, Any]] | Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    if isinstance(timetable, Mapping):
        return {exam_id: assignment for exam_id, assignment in timetable.items()}

    assignments: dict[str, Mapping[str, Any]] = {}
    for assignment in timetable:
        exam_id = assignment.get("exam_id")
        if not isinstance(exam_id, str) or exam_id in assignments:
            raise ValueError("each timetable assignment needs a unique exam_id")
        assignments[exam_id] = assignment
    return assignments


def _validate_assignment_references(
    assignments: Mapping[str, Mapping[str, Any]],
    rooms: Mapping[str, Mapping[str, Any]],
    slots: Mapping[str, Mapping[str, Any]],
) -> None:
    for exam_id, assignment in assignments.items():
        if assignment.get("slot_id") not in slots:
            raise ValueError(f"{exam_id} references an unknown slot")
        if assignment.get("room_id") not in rooms:
            raise ValueError(f"{exam_id} references an unknown room")


def _same_day_pairs(
    exams: Mapping[str, Mapping[str, Any]],
    assignments: Mapping[str, Mapping[str, Any]],
    slots: Mapping[str, Mapping[str, Any]],
) -> int:
    groups: dict[str, list[str]] = {}
    for exam_id, exam in exams.items():
        for group in exam.get("student_groups", []):
            groups.setdefault(group, []).append(exam_id)

    return sum(
        slots[assignments[left]["slot_id"]].get("day")
        == slots[assignments[right]["slot_id"]].get("day")
        for group_exams in groups.values()
        for left, right in combinations(group_exams, 2)
    )


def _average_unused_seat_proportion(
    exams: Mapping[str, Mapping[str, Any]],
    assignments: Mapping[str, Mapping[str, Any]],
    rooms: Mapping[str, Mapping[str, Any]],
) -> float:
    proportions: list[float] = []
    for exam_id, exam in exams.items():
        enrollment = exam.get("enrollment")
        room = rooms[assignments[exam_id]["room_id"]]
        capacity = room.get("capacity")
        if not isinstance(enrollment, int) or enrollment < 0:
            raise ValueError(f"{exam_id} needs a non-negative integer enrollment")
        if not isinstance(capacity, int) or capacity <= 0:
            raise ValueError(f"room {room['id']} needs a positive integer capacity")
        proportions.append((capacity - enrollment) / capacity)
    return sum(proportions) / len(proportions) if proportions else 0.0


def _teacher_preference_violations(
    case: Mapping[str, Any],
    exams: Mapping[str, Mapping[str, Any]],
    assignments: Mapping[str, Mapping[str, Any]],
) -> int:
    preferences = case.get("teacher_preferences", {})
    if not isinstance(preferences, Mapping):
        raise ValueError("teacher_preferences must map teachers to preferred slot ids")

    violations = 0
    for exam_id, exam in exams.items():
        preferred_slots = preferences.get(exam.get("teacher"))
        # Missing or an empty preference means the teacher has no preference.
        if preferred_slots and assignments[exam_id]["slot_id"] not in preferred_slots:
            violations += 1
    return violations

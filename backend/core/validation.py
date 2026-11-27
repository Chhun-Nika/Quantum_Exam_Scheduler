from collections import Counter
from collections.abc import Collection, Sequence
from itertools import combinations

from backend.core.case import ExamSession, SchedulingCase, TimeSlot
from backend.core.result import (
    ExamAssignment,
    HardRule,
    HardViolation,
    ResourceReference,
    ValidationDetails,
)


def validate_timetable(
    case: SchedulingCase, assignments: Sequence[ExamAssignment]
) -> ValidationDetails:
    """Check a solver candidate against the shared scheduling case."""
    exams = {exam.id: exam for exam in case.exams}
    rooms = {room.id: room for room in case.rooms}
    teachers = {teacher.id: teacher for teacher in case.teachers}
    slots = {slot.id: slot for slot in case.slots}
    counts = Counter(assignment.exam_id for assignment in assignments)
    violations: list[HardViolation] = []

    def add_violation(
        rule: HardRule, exam_id: str, message: str, *resources: ResourceReference
    ) -> None:
        violations.append(HardViolation(
            rule_id=rule, message=message, exam_ids=[exam_id], resources=list(resources)
        ))

    for exam_id in exams:
        count = counts[exam_id]
        if count != 1:
            add_violation("HC1", exam_id, f"Exam {exam_id} has {count} assignments and needs exactly one.")

    for assignment in assignments:
        exam_id, room_id, slot_id = assignment.exam_id, assignment.room_id, assignment.slot_id
        exam = exams.get(exam_id)
        room = rooms.get(room_id)
        known_slot = slot_id in slots
        room_ref = ResourceReference(kind="room", id=room_id)
        slot_ref = ResourceReference(kind="slot", id=slot_id)

        if exam is None:
            add_violation("HC1", exam_id, f"Assignment references unknown exam {exam_id}.")
        if room is None:
            add_violation("HC1", exam_id, f"Assignment references unknown room {room_id}.", room_ref)
        if not known_slot:
            add_violation("HC1", exam_id, f"Assignment references unknown slot {slot_id}.", slot_ref)

        # Check each restriction when its referenced entities are available.
        if exam is not None and room is not None:
            if exam.headcount > room.capacity:
                add_violation(
                    "HC5", exam_id,
                    f"Room {room_id} has {room.capacity} seats for {exam.headcount} students.",
                    room_ref,
                )
            if _is_disallowed(room_id, exam.allowed_room_ids):
                add_violation("HC6", exam_id, f"Room {room_id} is ineligible for exam {exam_id}.", room_ref)

        if known_slot and exam is not None:
            if _is_disallowed(slot_id, exam.allowed_slot_ids):
                add_violation("HC7", exam_id, f"Slot {slot_id} is ineligible for exam {exam_id}.", slot_ref)
            teacher = teachers[exam.teacher_id]
            if _is_disallowed(slot_id, teacher.available_slot_ids):
                add_violation(
                    "HC7", exam_id, f"Teacher {teacher.id} is unavailable in slot {slot_id}.",
                    ResourceReference(kind="teacher", id=teacher.id), slot_ref,
                )

        if known_slot and room is not None and _is_disallowed(slot_id, room.available_slot_ids):
            add_violation(
                "HC7", exam_id, f"Room {room_id} is unavailable in slot {slot_id}.",
                room_ref, slot_ref,
            )

    violations.extend(_overlap_violations(assignments, exams, slots, rooms))
    return ValidationDetails(hard_violation_count=len(violations), violations=violations)


def _is_disallowed(resource_id: str, allowed_ids: Sequence[str] | None) -> bool:
    return allowed_ids is not None and resource_id not in allowed_ids


def _overlap_violations(
    assignments: Sequence[ExamAssignment],
    exams: dict[str, ExamSession],
    slots: dict[str, TimeSlot],
    room_ids: Collection[str],
) -> list[HardViolation]:
    timed_assignments = [
        assignment for assignment in assignments
        if assignment.exam_id in exams and assignment.slot_id in slots
    ]
    rooms_by_overlapping_pair: dict[tuple[str, str], set[str]] = {}
    for left, right in combinations(timed_assignments, 2):
        if left.exam_id == right.exam_id:
            continue
        if not _slots_overlap(slots[left.slot_id], slots[right.slot_id]):
            continue

        # Group duplicate assignments by session pair so each rule is reported once.
        pair = (min(left.exam_id, right.exam_id), max(left.exam_id, right.exam_id))
        overlapping_rooms = rooms_by_overlapping_pair.setdefault(pair, set())
        if left.room_id == right.room_id and left.room_id in room_ids:
            overlapping_rooms.add(left.room_id)

    violations: list[HardViolation] = []
    for (left_id, right_id), overlapping_rooms in sorted(rooms_by_overlapping_pair.items()):
        left, right = exams[left_id], exams[right_id]
        exam_ids = [left_id, right_id]
        shared_groups = sorted(set(left.student_group_ids).intersection(right.student_group_ids))
        if shared_groups:
            violations.append(HardViolation(
                rule_id="HC2",
                message=f"Overlapping exams share student groups: {', '.join(shared_groups)}.",
                exam_ids=exam_ids,
                resources=[ResourceReference(kind="student_group", id=group) for group in shared_groups],
            ))
        if left.teacher_id == right.teacher_id:
            violations.append(HardViolation(
                rule_id="HC3",
                message=f"Teacher {left.teacher_id} supervises overlapping exams.",
                exam_ids=exam_ids,
                resources=[ResourceReference(kind="teacher", id=left.teacher_id)],
            ))
        if overlapping_rooms:
            ordered_rooms = sorted(overlapping_rooms)
            violations.append(HardViolation(
                rule_id="HC4",
                message=f"Overlapping exams are assigned to the same room: {', '.join(ordered_rooms)}.",
                exam_ids=exam_ids,
                resources=[ResourceReference(kind="room", id=room) for room in ordered_rooms],
            ))

    return violations


def _slots_overlap(left: TimeSlot, right: TimeSlot) -> bool:
    # Each slot is a half-open interval, so a shared endpoint is allowed.
    return (
        left.day == right.day
        and left.start_time < right.end_time
        and right.start_time < left.end_time
    )

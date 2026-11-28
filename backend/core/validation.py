"""Independent hard-constraint checks for complete timetable candidates."""

from itertools import combinations

from backend.core.case import SchedulingCase
from backend.core.result import ExamAssignment, HardViolation, ValidationDetails


def validate_timetable(case: SchedulingCase, assignments: list[ExamAssignment]) -> ValidationDetails:
    exams = {e.id: e for e in case.exams}
    rooms = {r.id: r for r in case.rooms}
    slots = {s.id: s for s in case.slots}
    teachers = {t.id: t for t in case.teachers}
    violations: list[HardViolation] = []

    def add(rule: str, message: str, ids: list[str]) -> None:
        violations.append(HardViolation(rule_id=rule, message=message, exam_ids=ids))

    for exam_id in exams:
        if sum(a.exam_id == exam_id for a in assignments) != 1:
            add("HC1", "Exam must have exactly one assignment", [exam_id])
    valid = []
    for a in assignments:
        if a.exam_id not in exams or a.room_id not in rooms or a.slot_id not in slots:
            add("HC1", "Assignment references an unknown exam, room, or slot", [a.exam_id])
            continue
        e, r = exams[a.exam_id], rooms[a.room_id]
        t = teachers[e.teacher_id]
        if r.capacity < e.headcount:
            add("HC5", "Room capacity is insufficient", [e.id])
        if e.allowed_room_ids is not None and r.id not in e.allowed_room_ids:
            add("HC6", "Room is not eligible", [e.id])
        if ((e.allowed_slot_ids is not None and a.slot_id not in e.allowed_slot_ids)
            or (r.available_slot_ids is not None and a.slot_id not in r.available_slot_ids)
            or (t.available_slot_ids is not None and a.slot_id not in t.available_slot_ids)):
            add("HC7", "Exam, room, or teacher is unavailable in this slot", [e.id])
        valid.append(a)

    for a, b in combinations(valid, 2):
        sa, sb = slots[a.slot_id], slots[b.slot_id]
        if sa.day != sb.day or sa.start_time >= sb.end_time or sb.start_time >= sa.end_time:
            continue
        ea, eb = exams[a.exam_id], exams[b.exam_id]
        ids = [a.exam_id, b.exam_id]
        if set(ea.student_group_ids) & set(eb.student_group_ids):
            add("HC2", "Student group has overlapping exams", ids)
        if ea.teacher_id == eb.teacher_id:
            add("HC3", "Teacher has overlapping exams", ids)
        if a.room_id == b.room_id:
            add("HC4", "Room has overlapping exams", ids)
    return ValidationDetails(hard_violation_count=len(violations), violations=violations)

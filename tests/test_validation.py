from pathlib import Path
from unittest import TestCase

from backend.core.case import SchedulingCase
from backend.core.result import ExamAssignment, ResourceReference, ValidationDetails
from backend.core.validation import validate_timetable

EXAMPLE_PATH = Path(__file__).resolve().parents[1] / "data" / "example.json"


class TimetableValidationTest(TestCase):
    def setUp(self) -> None:
        self.case = SchedulingCase.model_validate_json(EXAMPLE_PATH.read_bytes())
        self.assignments = [
            ExamAssignment(exam_id="QC_FINAL", slot_id="MON_09", room_id="R60"),
            ExamAssignment(exam_id="ML_FINAL", slot_id="MON_13", room_id="R60"),
            ExamAssignment(exam_id="DS_FINAL", slot_id="TUE_09", room_id="R60"),
        ]

    def test_reviewed_timetable_passes_all_hard_checks(self) -> None:
        details = validate_timetable(self.case, self.assignments)
        self.assertEqual(details, ValidationDetails(hard_violation_count=0, violations=[]))

    def test_missing_and_duplicate_assignments_identify_each_exam(self) -> None:
        assignments = [self.assignments[0], self.assignments[0], self.assignments[2]]
        details = validate_timetable(self.case, assignments)
        self.assertEqual(details.hard_violation_count, 2)
        self.assertEqual(
            [(violation.rule_id, violation.exam_ids) for violation in details.violations],
            [("HC1", ["QC_FINAL"]), ("HC1", ["ML_FINAL"])],
        )

    def test_unknown_references_preserve_diagnostics_for_other_checks(self) -> None:
        self.case.rooms[0].capacity = 59
        assignments = [
            self.assignments[0].model_copy(update={"slot_id": "UNKNOWN_SLOT"}),
            self.assignments[1].model_copy(update={"room_id": "UNKNOWN_ROOM"}),
            self.assignments[2],
            ExamAssignment(exam_id="UNKNOWN_EXAM", slot_id="MON_09", room_id="R60"),
        ]
        details = validate_timetable(self.case, assignments)
        self.assertEqual(details.hard_violation_count, 4)
        unknown_refs = [violation for violation in details.violations if violation.rule_id == "HC1"]
        self.assertEqual(
            [(violation.exam_ids, violation.resources) for violation in unknown_refs],
            [
                (["QC_FINAL"], [ResourceReference(kind="slot", id="UNKNOWN_SLOT")]),
                (["ML_FINAL"], [ResourceReference(kind="room", id="UNKNOWN_ROOM")]),
                (["UNKNOWN_EXAM"], []),
            ],
        )
        capacity = next(violation for violation in details.violations if violation.rule_id == "HC5")
        self.assertEqual(capacity.exam_ids, ["QC_FINAL"])
        self.assertEqual(capacity.resources, [ResourceReference(kind="room", id="R60")])
        self.assertIn("59 seats for 60 students", capacity.message)

    def test_room_eligibility_rejects_unlisted_rooms_and_empty_lists(self) -> None:
        for allowed_rooms in (["R75"], []):
            with self.subTest(allowed_rooms=allowed_rooms):
                self.case.exams[0].allowed_room_ids = allowed_rooms
                details = validate_timetable(self.case, self.assignments)
                self.assertEqual(details.hard_violation_count, 1)
                violation, = details.violations
                self.assertEqual(violation.rule_id, "HC6")
                self.assertEqual(violation.exam_ids, ["QC_FINAL"])
                self.assertEqual(violation.resources, [ResourceReference(kind="room", id="R60")])

    def test_slot_restrictions_identify_session_teacher_and_room(self) -> None:
        self.case.exams[0].allowed_slot_ids = ["TUE_09"]
        self.case.teachers[0].available_slot_ids = ["TUE_09"]
        self.case.rooms[0].available_slot_ids = ["MON_13", "TUE_09"]
        details = validate_timetable(self.case, self.assignments)
        self.assertEqual(details.hard_violation_count, 3)
        slot = ResourceReference(kind="slot", id="MON_09")
        self.assertEqual(
            [(violation.rule_id, violation.exam_ids, violation.resources) for violation in details.violations],
            [
                ("HC7", ["QC_FINAL"], [slot]),
                ("HC7", ["QC_FINAL"], [ResourceReference(kind="teacher", id="TA"), slot]),
                ("HC7", ["QC_FINAL"], [ResourceReference(kind="room", id="R60"), slot]),
            ],
        )

    def test_an_available_nonpreferred_slot_passes_hard_checks(self) -> None:
        self.case.teachers[0].preferred_slot_ids = ["TUE_09"]
        self.assertEqual(validate_timetable(self.case, self.assignments).hard_violation_count, 0)

    def test_group_conflict_uses_intervals_even_with_distinct_slot_ids(self) -> None:
        self.case.slots[1].start_time = "10:30"
        self.assignments[1] = self.assignments[1].model_copy(update={"room_id": "R75"})

        details = validate_timetable(self.case, self.assignments)

        self.assertEqual(details.hard_violation_count, 1)
        violation, = details.violations
        self.assertEqual(violation.rule_id, "HC2")
        self.assertEqual(violation.exam_ids, ["ML_FINAL", "QC_FINAL"])
        self.assertEqual(violation.resources, [ResourceReference(kind="student_group", id="G1")])

    def test_teacher_conflict_can_occur_in_different_rooms_with_different_groups(self) -> None:
        self.case.exams[0].student_group_ids = ["G1"]
        self.case.exams[0].headcount = 30
        self.assignments[2] = self.assignments[2].model_copy(update={"slot_id": "MON_09", "room_id": "R75"})

        details = validate_timetable(self.case, self.assignments)

        self.assertEqual(details.hard_violation_count, 1)
        violation, = details.violations
        self.assertEqual(violation.rule_id, "HC3")
        self.assertEqual(violation.exam_ids, ["DS_FINAL", "QC_FINAL"])
        self.assertEqual(violation.resources, [ResourceReference(kind="teacher", id="TA")])

    def test_room_conflict_can_occur_with_different_teachers_and_groups(self) -> None:
        self.assignments[2] = self.assignments[2].model_copy(update={"slot_id": "MON_13"})

        details = validate_timetable(self.case, self.assignments)

        self.assertEqual(details.hard_violation_count, 1)
        violation, = details.violations
        self.assertEqual(violation.rule_id, "HC4")
        self.assertEqual(violation.exam_ids, ["DS_FINAL", "ML_FINAL"])
        self.assertEqual(violation.resources, [ResourceReference(kind="room", id="R60")])

    def test_back_to_back_slots_and_same_times_on_different_days_are_allowed(self) -> None:
        self.case.slots[1].start_time = "11:00"
        self.case.exams[1].teacher_id = "TA"

        details = validate_timetable(self.case, self.assignments)

        self.assertEqual(details.hard_violation_count, 0)

    def test_overlap_is_reported_once_per_rule_and_pair(self) -> None:
        self.case.exams[2].student_group_ids = ["G2", "G1"]
        self.case.exams[2].headcount = 60
        self.assignments[2] = self.assignments[2].model_copy(update={"slot_id": "MON_09"})
        self.assignments.extend([
            self.assignments[0].model_copy(update={"room_id": "R75"}),
            self.assignments[2].model_copy(update={"room_id": "R75"}),
        ])

        details = validate_timetable(self.case, self.assignments)

        self.assertEqual(details.hard_violation_count, 5)
        overlaps = [violation for violation in details.violations if violation.rule_id != "HC1"]
        self.assertEqual([violation.rule_id for violation in overlaps], ["HC2", "HC3", "HC4"])
        self.assertTrue(all(violation.exam_ids == ["DS_FINAL", "QC_FINAL"] for violation in overlaps))
        self.assertEqual(overlaps[0].resources, [
            ResourceReference(kind="student_group", id="G1"),
            ResourceReference(kind="student_group", id="G2"),
        ])
        self.assertEqual(overlaps[2].resources, [
            ResourceReference(kind="room", id="R60"),
            ResourceReference(kind="room", id="R75"),
        ])

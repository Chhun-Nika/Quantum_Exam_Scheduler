from unittest import TestCase

from backend.core.scoring import score_soft_constraints


CASE = {
    "slots": [
        {"id": "MON_09", "day": "Monday", "start_time": "09:00", "end_time": "11:00"},
        {"id": "MON_13", "day": "Monday", "start_time": "13:00", "end_time": "15:00"},
        {"id": "TUE_09", "day": "Tuesday", "start_time": "09:00", "end_time": "11:00"},
    ],
    "rooms": [
        {"id": "SMALL", "capacity": 10},
        {"id": "LARGE", "capacity": 20},
    ],
    "exams": [
        {"id": "E1", "student_groups": ["G1"], "teacher": "A", "enrollment": 8},
        {"id": "E2", "student_groups": ["G1", "G2"], "teacher": "B", "enrollment": 10},
        {"id": "E3", "student_groups": ["G2"], "teacher": "A", "enrollment": 10},
    ],
    "teacher_preferences": {"B": ["TUE_09"]},
}


class SoftScoringTest(TestCase):
    def test_hand_calculated_component_scores_and_weighted_total(self) -> None:
        score = score_soft_constraints(
            CASE,
            {
                "E1": {"slot_id": "MON_09", "room_id": "SMALL"},
                "E2": {"slot_id": "MON_13", "room_id": "LARGE"},
                "E3": {"slot_id": "TUE_09", "room_id": "LARGE"},
            },
            weights={"s1": 2, "s2": 10, "s3": 3},
        )

        # S1: E1/E2 share G1 on Monday; E2/E3 are on different days.
        self.assertEqual(score.same_day_pairs, 1)
        # S2: ((10 - 8) / 10 + (20 - 10) / 20 + (20 - 10) / 20) / 3.
        self.assertAlmostEqual(score.average_unused_seat_proportion, 0.4)
        # S3: only E2 violates B's Tuesday preference; A has no preference.
        self.assertEqual(score.teacher_preference_violations, 1)
        self.assertAlmostEqual(score.weighted_total, 9.0)

    def test_same_day_pair_is_counted_for_each_shared_student_group(self) -> None:
        case = {
            **CASE,
            "exams": [
                {"id": "E1", "student_groups": ["G1", "G2"], "teacher": "A", "enrollment": 8},
                {"id": "E2", "student_groups": ["G1", "G2"], "teacher": "B", "enrollment": 10},
            ],
        }
        score = score_soft_constraints(
            case,
            {
                "E1": {"slot_id": "MON_09", "room_id": "SMALL"},
                "E2": {"slot_id": "MON_13", "room_id": "LARGE"},
            },
        )
        self.assertEqual(score.same_day_pairs, 2)

    def test_no_teacher_preference_has_no_penalty(self) -> None:
        case = {**CASE, "teacher_preferences": {}}
        score = score_soft_constraints(
            case,
            [
                {"exam_id": "E1", "slot_id": "MON_09", "room_id": "SMALL"},
                {"exam_id": "E2", "slot_id": "MON_13", "room_id": "LARGE"},
                {"exam_id": "E3", "slot_id": "TUE_09", "room_id": "LARGE"},
            ],
        )
        self.assertEqual(score.teacher_preference_violations, 0)

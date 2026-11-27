import json
from pathlib import Path
from unittest import TestCase

from backend.core.scoring import score_soft_constraints


REFERENCE_CASES = Path(__file__).resolve().parents[1] / "data" / "reference_cases"


def load_fixture(name: str) -> dict:
    return json.loads((REFERENCE_CASES / name).read_text(encoding="utf-8"))


class ReferenceCasesTest(TestCase):
    def test_feasible_case_has_the_documented_assignments_and_score(self) -> None:
        case = load_fixture("feasible-case.json")
        expected = load_fixture("feasible-expected-result.json")

        assignments = {item["exam_id"]: item for item in expected["assignments"]}
        rooms = {room["id"]: room for room in case["rooms"]}
        exams = {exam["id"]: exam for exam in case["exams"]}

        self.assertEqual(expected["outcome"], "feasible")
        self.assertEqual(expected["validation"]["hard_violation_count"], 0)
        self.assertEqual(set(assignments), set(exams))
        for exam_id, exam in exams.items():
            assignment = assignments[exam_id]
            self.assertIn(assignment["room_id"], exam["allowed_room_ids"])
            self.assertGreaterEqual(rooms[assignment["room_id"]]["capacity"], exam["headcount"])

        score = expected["score"]
        calculated_score = score_soft_constraints(case, assignments)
        self.assertEqual(score["components"]["s1"]["value"], 1)
        self.assertAlmostEqual(score["components"]["s2"]["value"], 0.225)
        self.assertEqual(score["components"]["s3"]["value"], 1)
        self.assertAlmostEqual(score["total"], 2.225)
        self.assertEqual(calculated_score.same_day_pairs, 1)
        self.assertAlmostEqual(calculated_score.average_unused_seat_proportion, 0.225)
        self.assertEqual(calculated_score.teacher_preference_violations, 1)
        self.assertAlmostEqual(calculated_score.weighted_total, 2.225)

    def test_infeasible_case_records_the_capacity_reason(self) -> None:
        case = load_fixture("infeasible-capacity-case.json")
        expected = load_fixture("infeasible-capacity-expected-result.json")
        exam = case["exams"][0]
        eligible_rooms = {
            room["id"]: room for room in case["rooms"] if room["id"] in exam["allowed_room_ids"]
        }

        self.assertEqual(expected["outcome"], "infeasible_proven")
        self.assertEqual(expected["reason"]["code"], "no_eligible_room_with_sufficient_capacity")
        self.assertTrue(all(room["capacity"] < exam["headcount"] for room in eligible_rooms.values()))

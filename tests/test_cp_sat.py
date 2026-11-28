import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from ortools.sat.python import cp_model

from backend.core.case import SchedulingCase
from backend.core.result import ExamAssignment, SolverRun
from backend.core.validation import validate_timetable
from backend.solvers.classical.cp_sat import solve_cp_sat, solve_cp_sat_feasibility

DATA = Path(__file__).resolve().parents[1] / "data"


def _load_reference(name: str) -> dict:
    return json.loads((DATA / "reference_cases" / name).read_text(encoding="utf-8"))


def _reference_case(name: str) -> SchedulingCase:
    payload = _load_reference(name)
    payload.pop("id", None)  # The reference file labels the fixture separately from the case fields.
    return SchedulingCase.model_validate(payload)


class CpSatFeasibilityTest(TestCase):
    def test_returns_the_reference_timetable(self) -> None:
        case = _reference_case("feasible-case.json")
        expected = _load_reference("feasible-expected-result.json")

        result = solve_cp_sat_feasibility(case)

        self.assertEqual(result.outcome, expected["outcome"])
        self.assertEqual(result.assignments, tuple(ExamAssignment(**row) for row in expected["assignments"]))
        self.assertEqual(validate_timetable(case, result.assignments).hard_violation_count, 0)

    def test_empty_capacity_domain_proves_infeasibility(self) -> None:
        case = _reference_case("infeasible-capacity-case.json")
        expected = _load_reference("infeasible-capacity-expected-result.json")

        result = solve_cp_sat_feasibility(case)

        self.assertEqual(result.outcome, expected["outcome"])
        self.assertIsNone(result.assignments)
        self.assertEqual(result.reason.code, expected["reason"]["code"])

    def test_overlapping_distinct_slots_can_make_group_or_teacher_infeasible(self) -> None:
        for resource in ("group", "teacher"):
            with self.subTest(resource=resource):
                case = _reference_case("feasible-case.json").model_dump()
                case["slots"][1]["start_time"] = "10:30"
                if resource == "group":
                    case["teachers"].append({"id": "T2"})
                    case["exams"][1]["teacher_id"] = "T2"
                else:
                    case["exams"][0]["student_group_ids"] = ["G2"]

                result = solve_cp_sat_feasibility(SchedulingCase.model_validate(case))

                self.assertEqual(result.outcome, "infeasible_proven")
                self.assertEqual(result.reason.code, "hard_constraints_infeasible")

    def test_unavoidable_room_overlap_with_different_teachers_and_groups(self) -> None:
        case = SchedulingCase.model_validate_json((DATA / "example.json").read_bytes()).model_dump()
        for exam, slot_id in zip(case["exams"], ("TUE_09", "MON_09", "MON_13"), strict=True):
            exam["allowed_slot_ids"] = [slot_id]
            exam["allowed_room_ids"] = ["R60"]
        case["slots"][1]["start_time"] = "10:30"

        result = solve_cp_sat_feasibility(SchedulingCase.model_validate(case))

        self.assertEqual(result.outcome, "infeasible_proven")
        self.assertEqual(result.reason.code, "hard_constraints_infeasible")

    def test_explicitly_empty_eligibility_or_availability_disallows_every_option(self) -> None:
        for collection, field in (
            ("exams", "allowed_slot_ids"),
            ("exams", "allowed_room_ids"),
            ("teachers", "available_slot_ids"),
            ("rooms", "available_slot_ids"),
        ):
            with self.subTest(field=field, collection=collection):
                payload = _reference_case("feasible-case.json").model_dump()
                payload[collection][0][field] = []

                result = solve_cp_sat_feasibility(SchedulingCase.model_validate(payload))

                self.assertEqual(result.outcome, "infeasible_proven")
                self.assertEqual(result.reason.code, "no_eligible_assignment")

    def test_stopped_search_preserves_unknown_feasibility(self) -> None:
        case = _reference_case("feasible-case.json")

        result = solve_cp_sat_feasibility(case, time_limit_seconds=0)

        self.assertEqual(result.outcome, "no_feasible_found")
        self.assertEqual(result.reason.code, "search_incomplete")
        self.assertIsNone(result.assignments)


class CpSatOptimizationTest(TestCase):
    def setUp(self) -> None:
        self.case = SchedulingCase.model_validate_json((DATA / "example.json").read_bytes())

    def test_proves_the_known_best_timetable_on_three_sessions(self) -> None:
        run = solve_cp_sat(self.case, run_id="example")

        self.assertEqual(run.run_id, "example")
        self.assertEqual(run.state, "completed")
        self.assertEqual(run.result.outcome, "feasible")
        self.assertTrue(run.result.optimality_proven)
        self.assertEqual(run.result.validation.hard_violation_count, 0)
        self.assertAlmostEqual(run.result.score.total, 1 / 3)
        self.assertEqual(run.result.score.components.s1.value, 0)
        self.assertEqual(run.result.score.components.s3.value, 0)
        self.assertEqual(SolverRun.model_validate_json(run.model_dump_json()), run)

    def test_matches_the_hand_checked_score_and_capacity_outcome(self) -> None:
        run = solve_cp_sat(_reference_case("feasible-case.json"))
        expected = _load_reference("feasible-expected-result.json")
        self.assertTrue(run.result.optimality_proven)
        self.assertEqual(run.result.score.model_dump(), expected["score"])

        run = solve_cp_sat(_reference_case("infeasible-capacity-case.json"))
        self.assertEqual(run.result.outcome, "infeasible_proven")
        self.assertIsNone(run.result.assignments)
        self.assertEqual(run.reason.code, "no_eligible_room_with_sufficient_capacity")

    def test_uses_decimal_weights_and_preserves_visible_disabled_settings(self) -> None:
        payload = _reference_case("feasible-case.json").model_dump()
        payload["soft_objectives"] = {
            "s1": {"enabled": False, "weight": 3},
            "s2": {"enabled": True, "weight": 0.2},
        }
        run = solve_cp_sat(SchedulingCase.model_validate(payload))

        components = run.result.score.components
        self.assertEqual(components.s1.model_dump(), {"value": 1, "enabled": False, "weight": 3})
        self.assertEqual(components.s3.weight, 1)
        self.assertAlmostEqual(run.result.score.total, 1.045)

    def test_changed_weights_choose_a_different_tradeoff(self) -> None:
        payload = self.case.model_dump()
        payload["teachers"][0]["preferred_slot_ids"] = ["MON_09", "MON_13"]
        payload["soft_objectives"]["s2"]["enabled"] = False

        for weight, expected in ((10, (2, 0, 2)), (0.25, (0, 1, 0.25))):
            with self.subTest(weight=weight):
                payload["soft_objectives"]["s3"]["weight"] = weight
                run = solve_cp_sat(SchedulingCase.model_validate(payload))

                self.assertTrue(run.result.optimality_proven)
                score = run.result.score
                self.assertEqual((score.components.s1.value, score.components.s3.value, score.total), expected)

    def test_rejects_an_objective_that_cannot_fit_as_exact_integers(self) -> None:
        payload = self.case.model_dump()
        payload["soft_objectives"]["s1"]["weight"] = 1e-30

        run = solve_cp_sat(SchedulingCase.model_validate(payload))

        self.assertEqual(run.state, "failed")
        self.assertEqual(run.reason.code, "objective_out_of_range")
        self.assertIsNone(run.result)

    def test_zero_time_limit_keeps_feasibility_unknown(self) -> None:
        run = solve_cp_sat(self.case, time_limit_seconds=0)

        self.assertEqual(run.state, "timed_out")
        self.assertEqual(run.reason.code, "time_limit")
        self.assertEqual(run.result.outcome, "no_feasible_found")
        self.assertIsNone(run.result.optimality_proven)

    def test_feasible_status_does_not_claim_optimality(self) -> None:
        original_solve = cp_model.CpSolver.solve

        def solve_without_proof(solver, model):
            self.assertEqual(original_solve(solver, model), cp_model.OPTIMAL)
            return cp_model.FEASIBLE

        with patch.object(cp_model.CpSolver, "solve", solve_without_proof):
            run = solve_cp_sat(self.case)

        self.assertEqual(run.result.outcome, "feasible")
        self.assertEqual(run.result.validation.hard_violation_count, 0)
        self.assertFalse(run.result.optimality_proven)

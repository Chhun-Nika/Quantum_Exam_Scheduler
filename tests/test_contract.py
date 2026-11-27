from pathlib import Path
from unittest import TestCase

from pydantic import ValidationError

from backend.core.case import SchedulingCase
from backend.core.result import EligibilityReport, SolverRun

EXAMPLE_PATH = Path(__file__).resolve().parents[1] / "data" / "example.json"
QUANTUM_LIMIT = {
    "code": "quantum_qubit_budget_exceeded",
    "message": "This case requires 18 logical qubits and the budget is 16.",
}


class CaseContractTest(TestCase):
    def setUp(self) -> None:
        self.case = SchedulingCase.model_validate_json(EXAMPLE_PATH.read_bytes()).model_dump()

    def test_empty_eligibility_is_distinct_from_unrestricted(self) -> None:
        self.case["exams"][0]["allowed_room_ids"] = []
        case = SchedulingCase.model_validate(self.case)
        self.assertEqual(case.exams[0].allowed_room_ids, [])
        self.assertIsNone(case.exams[1].allowed_room_ids)

    def test_unknown_room_is_an_input_error(self) -> None:
        self.case["exams"][0]["allowed_room_ids"] = ["unknown"]
        with self.assertRaisesRegex(ValidationError, "QC_FINAL.allowed_room_ids.*unknown"):
            SchedulingCase.model_validate(self.case)

    def test_invalid_slot_interval_is_an_input_error(self) -> None:
        self.case["slots"][0]["end_time"] = "09:00"
        with self.assertRaisesRegex(ValidationError, "start_time must be before end_time"):
            SchedulingCase.model_validate(self.case)


class ResultContractTest(TestCase):
    def test_quantum_eligibility_respects_the_budget(self) -> None:
        methods = {
            "exact_search": {"eligible": True},
            "cp_sat": {"eligible": True},
            "qaoa": {"eligible": False, "reason": QUANTUM_LIMIT},
            "vqe": {"eligible": False, "reason": QUANTUM_LIMIT},
        }
        report = EligibilityReport(logical_qubits=18, quantum_qubit_budget=16, methods=methods)
        self.assertFalse(report.methods["vqe"].eligible)
        methods["vqe"] = {"eligible": True}
        with self.assertRaisesRegex(ValidationError, "above the qubit budget"):
            EligibilityReport(logical_qubits=18, quantum_qubit_budget=16, methods=methods)

    def test_timed_out_run_can_return_a_feasible_timetable(self) -> None:
        run = SolverRun.model_validate({
            "run_id": "example-cp-sat",
            "method": "cp_sat",
            "state": "timed_out",
            "elapsed_ms": 100,
            "reason": {"code": "time_limit", "message": "The solver reached its time limit."},
            "result": {
                "outcome": "feasible",
                "optimality_proven": False,
                "assignments": [
                    {"exam_id": "QC_FINAL", "slot_id": "MON_09", "room_id": "R60"},
                    {"exam_id": "ML_FINAL", "slot_id": "MON_13", "room_id": "R60"},
                    {"exam_id": "DS_FINAL", "slot_id": "TUE_09", "room_id": "R60"},
                ],
                "validation": {"hard_violation_count": 0, "violations": []},
                "score": {
                    "total": 4 / 3,
                    "components": {
                        "s1": {"value": 1, "enabled": True, "weight": 1},
                        "s2": {"value": 1 / 3, "enabled": True, "weight": 1},
                        "s3": {"value": 0, "enabled": True, "weight": 1},
                    },
                },
            },
        })
        self.assertEqual(run.result.outcome, "feasible")
        self.assertFalse(run.result.optimality_proven)
        self.assertEqual(SolverRun.model_validate_json(run.model_dump_json()), run)

    def test_outcomes_without_a_timetable_remain_distinct(self) -> None:
        for method, outcome in (("cp_sat", "infeasible_proven"), ("qaoa", "no_feasible_found")):
            with self.subTest(outcome=outcome):
                run = SolverRun.model_validate({
                    "run_id": "example-completed",
                    "method": method,
                    "state": "completed",
                    "elapsed_ms": 10,
                    "result": {"outcome": outcome},
                })
                self.assertEqual(run.result.outcome, outcome)
                self.assertIsNone(run.result.assignments)

        run = SolverRun.model_validate({
            "run_id": "example-skipped",
            "method": "vqe",
            "state": "skipped",
            "elapsed_ms": None,
            "reason": QUANTUM_LIMIT,
            "result": None,
        })
        self.assertEqual(run.state, "skipped")
        self.assertIsNone(run.result)

import json
from pathlib import Path
from unittest import TestCase

from backend.core.case import SchedulingCase
from backend.solvers.classical.brute_force import solve_brute_force


def fixture(name):
    path = Path(__file__).resolve().parents[1] / "data" / "reference_cases" / name
    data = json.loads(path.read_text(encoding="utf-8"))
    data.pop("id", None)
    return SchedulingCase.model_validate(data)


class BruteForceTest(TestCase):
    def test_feasible_reference_optimum(self):
        run = solve_brute_force(fixture("feasible-case.json"))
        self.assertEqual(run.state, "completed")
        self.assertEqual(run.result.outcome, "feasible")
        self.assertTrue(run.result.optimality_proven)
        self.assertAlmostEqual(run.result.score.total, 2.225)
        stats = run.search_statistics
        self.assertEqual((stats.total_candidates, stats.checked_candidates, stats.feasible_candidates, stats.infeasible_candidates), (4, 4, 1, 3))
        self.assertTrue(stats.search_completed)
        self.assertIsNotNone(stats.search_elapsed_ms)
        self.assertGreaterEqual(stats.search_elapsed_ms, 0)
        self.assertEqual({(a.exam_id, a.slot_id, a.room_id) for a in run.result.assignments},
                         {("E1", "MON_09", "R1"), ("E2", "MON_11", "R2")})

    def test_infeasible_reference(self):
        run = solve_brute_force(fixture("infeasible-capacity-case.json"))
        self.assertEqual(run.result.outcome, "infeasible_proven")

    def test_size_limit_and_interruption(self):
        case = fixture("feasible-case.json")
        skipped = solve_brute_force(case, max_candidates=1)
        self.assertEqual(skipped.state, "skipped")
        self.assertEqual(skipped.search_statistics.checked_candidates, 0)
        self.assertFalse(skipped.search_statistics.search_completed)
        self.assertIsNone(skipped.search_statistics.search_elapsed_ms)
        run = solve_brute_force(case, cancelled=lambda: True)
        self.assertEqual(run.state, "cancelled")
        self.assertEqual(run.reason.code, "search_cancelled")
        self.assertEqual(run.result.outcome, "no_feasible_found")
        timed_out = solve_brute_force(case, time_limit_seconds=0)
        self.assertEqual(timed_out.state, "timed_out")
        self.assertEqual(timed_out.reason.code, "time_limit_exceeded")

    def test_search_selects_best_not_first_valid(self):
        case = fixture("feasible-case.json")
        case.exams = case.exams[:1]
        case.exams[0].allowed_room_ids = None
        case.rooms[1].capacity = 30
        case.rooms[1].available_slot_ids = ["MON_09"]
        run = solve_brute_force(case)
        self.assertEqual(run.result.outcome, "feasible")
        self.assertTrue(run.result.optimality_proven)
        self.assertEqual(run.result.assignments[0].room_id, "R2")
        self.assertAlmostEqual(run.result.score.total, 0)

    def test_interrupted_incumbent_is_not_proven_optimal(self):
        calls = iter([False, False, True])
        case = fixture("feasible-case.json")
        case.rooms[0].available_slot_ids = None
        case.rooms[1].available_slot_ids = None
        # The first candidate conflicts, the second is valid, then search stops.
        run = solve_brute_force(case, cancelled=lambda: next(calls))
        self.assertEqual(run.state, "cancelled")
        self.assertEqual(run.result.outcome, "feasible")
        self.assertFalse(run.result.optimality_proven)
        self.assertEqual(run.search_statistics.checked_candidates, 2)
        self.assertEqual(run.search_statistics.feasible_candidates, 1)
        self.assertFalse(run.search_statistics.search_completed)

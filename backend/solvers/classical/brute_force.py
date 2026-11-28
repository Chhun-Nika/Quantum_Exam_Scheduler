"""Exhaustive reference solver for small scheduling cases."""

from itertools import product
from math import prod
from time import perf_counter
from typing import Callable
from uuid import uuid4

from backend.core.case import SchedulingCase
from backend.core.result import ExamAssignment, SolverRun
from backend.core.scoring import score_soft_constraints
from backend.core.validation import validate_timetable


def solve_brute_force(case: SchedulingCase, *, max_candidates: int = 100_000,
                      time_limit_seconds: float | None = None,
                      cancelled: Callable[[], bool] | None = None) -> SolverRun:
    """Check every candidate, or report a size limit or interrupted search."""
    if max_candidates < 1 or (time_limit_seconds is not None and time_limit_seconds < 0):
        raise ValueError("max_candidates must be positive and time_limit_seconds non-negative")
    run_id = str(uuid4())
    # Build each exam's allowed slot-room choices before combining them.
    choices = [
        [ExamAssignment(exam_id=e.id, slot_id=s.id, room_id=r.id)
         for s in case.slots for r in case.rooms
         if (e.allowed_slot_ids is None or s.id in e.allowed_slot_ids)
         and (e.allowed_room_ids is None or r.id in e.allowed_room_ids)]
        for e in case.exams
    ]
    count = prod(len(options) for options in choices)
    checked = feasible = 0
    if count > max_candidates:
        return SolverRun(run_id=run_id, method="exact_search", state="skipped", elapsed_ms=None,
                         result=None, reason={"code": "candidate_limit_exceeded",
                         "message": f"{count} candidates exceed the limit of {max_candidates}"},
                         search_statistics=_statistics(count, checked, feasible, False))

    start = perf_counter()
    settings = {key: case.soft_objectives.get(key) for key in ("s1", "s2", "s3")}
    weights = {key: (setting.weight if setting.enabled else 0.0) if setting else 1.0
               for key, setting in settings.items()}
    case_data = case.model_dump()
    best = None
    # Each product contains exactly one assignment for every exam session.
    for candidate in product(*choices):
        if cancelled is not None and cancelled():
            return _result(run_id, start, best, settings, count, checked, feasible, state="cancelled")
        if time_limit_seconds is not None and perf_counter() - start >= time_limit_seconds:
            return _result(run_id, start, best, settings, count, checked, feasible, state="timed_out")
        assignments = list(candidate)
        validation = validate_timetable(case, assignments)
        checked += 1
        # Only hard-valid timetables are eligible for soft scoring.
        if validation.hard_violation_count:
            continue
        feasible += 1
        score = score_soft_constraints(case_data, [a.model_dump() for a in assignments], weights=weights)
        if best is None or score.weighted_total < best[0].weighted_total:
            best = (score, assignments, validation)
    # Exhausting all candidates proves optimality or infeasibility.
    return _result(run_id, start, best, settings, count, checked, feasible, state="completed")


def _statistics(total, checked, feasible, completed, elapsed_ms=None):
    return {"total_candidates": total, "checked_candidates": checked,
            "feasible_candidates": feasible, "infeasible_candidates": checked - feasible,
            "search_completed": completed, "search_elapsed_ms": elapsed_ms}


def _result(run_id, start, best, settings, total, checked, feasible, *, state):
    interrupted = state != "completed"
    if best is None:
        result = {"outcome": "no_feasible_found" if interrupted else "infeasible_proven"}
    else:
        score, assignments, validation = best
        values = {"s1": score.same_day_pairs, "s2": score.average_unused_seat_proportion,
                  "s3": score.teacher_preference_violations}
        components = {key: {"value": value, "enabled": setting.enabled if setting else True,
                            "weight": setting.weight if setting else 1.0}
                      for (key, setting), value in zip(settings.items(), values.values())}
        result = {"outcome": "feasible", "assignments": assignments,
                  "optimality_proven": not interrupted, "validation": validation,
                  "score": {"total": score.weighted_total, "components": components}}
    elapsed_ms = (perf_counter() - start) * 1000
    return SolverRun(run_id=run_id, method="exact_search", state=state,
                     elapsed_ms=int(elapsed_ms), result=result,
                     reason={"code": "search_cancelled" if state == "cancelled" else "time_limit_exceeded",
                             "message": "Search stopped before all candidates were checked"} if interrupted else None,
                     search_statistics=_statistics(total, checked, feasible, not interrupted, elapsed_ms))

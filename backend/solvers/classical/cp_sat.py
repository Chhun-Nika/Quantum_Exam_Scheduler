from collections import defaultdict
from dataclasses import dataclass
from fractions import Fraction
from itertools import combinations
from math import gcd, isfinite, lcm
from time import perf_counter_ns
from typing import Literal
from uuid import uuid4

from ortools.sat.python import cp_model

from backend.core.case import Objective, ObjectiveSetting, SchedulingCase, TimeSlot
from backend.core.result import (
    CountComponent,
    ExamAssignment,
    ProportionComponent,
    RunReason,
    RunState,
    SchedulingOutcome,
    ScoreComponents,
    SoftScore,
    SolverResult,
    SolverRun,
    ValidationDetails,
)
from backend.core.scoring import DEFAULT_WEIGHTS, score_soft_constraints
from backend.core.validation import validate_timetable

DAY_INDEX = {
    day: index for index, day in enumerate(
        ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
    )
}
MINUTES_PER_DAY = 24 * 60

@dataclass(frozen=True)
class FeasibilityResult:
    outcome: SchedulingOutcome | Literal["failed"]
    assignments: tuple[ExamAssignment, ...] | None = None
    reason: RunReason | None = None

@dataclass(frozen=True)
class _SearchResult:
    feasibility: FeasibilityResult
    validation: ValidationDetails | None = None
    optimality_proven: bool = False
    timed_out: bool = False


type AssignmentVariables = list[tuple[ExamAssignment, cp_model.IntVar]]


# Find a timetable that satisfies all hard rules and check it with the validator.
# Return the timetable if found, or explain why the search ended.
def solve_cp_sat_feasibility(
    case: SchedulingCase, *, time_limit_seconds: float | None = None
) -> FeasibilityResult:
    _check_time_limit(time_limit_seconds)
    model, variables, empty_domain = _build_feasibility_model(case)
    if empty_domain is not None:
        return FeasibilityResult("infeasible_proven", reason=empty_domain)
    return _search(case, model, variables, time_limit_seconds).feasibility


# Search for a valid timetable with the lowest weighted S1–S3 penalty.
# Return the checked timetable, score, and whether the solver proved it optimal.
# The time limit covers search. Reported time also includes setup and checks.
def solve_cp_sat(
    case: SchedulingCase, *, time_limit_seconds: float | None = None, run_id: str | None = None
) -> SolverRun:
    _check_time_limit(time_limit_seconds)
    started = perf_counter_ns()
    run_id = str(uuid4()) if run_id is None else run_id

    # Use the same run ID and timer for every result, even when the solver stops early.
    def run(
        state: RunState, result: SolverResult | None, reason: RunReason | None = None
    ) -> SolverRun:
        return SolverRun(
            run_id=run_id, method="cp_sat", state=state,
            elapsed_ms=(perf_counter_ns() - started) // 1_000_000, result=result, reason=reason,
        )

    model, variables, empty_domain = _build_feasibility_model(case)
    if empty_domain is not None:
        return run("completed", SolverResult(outcome="infeasible_proven"), empty_domain)

    settings = _objective_settings(case)
    # Use zero for disabled objectives and keep their configured weights for display.
    weights = {name: setting.weight if setting.enabled else 0.0 for name, setting in settings.items()}
    # Read weights as decimal text so values like 0.2 become exact fractions like 1/5.
    exact_weights = {name: Fraction(str(weight)) for name, weight in weights.items()}
    terms = _objective_terms(model, case, variables, exact_weights)
    try:
        coefficients = _integer_coefficients([cost for _, cost in terms])
    except OverflowError:
        return run("failed", None, _objective_range_error())
    if terms:
        expression = cp_model.LinearExpr.weighted_sum([variable for variable, _ in terms], coefficients)
        model.minimize(expression)
        if "overflow" in model.validate().lower():
            return run("failed", None, _objective_range_error())

    search = _search(case, model, variables, time_limit_seconds)
    outcome = search.feasibility
    if outcome.outcome == "failed":
        return run("failed", None, outcome.reason)
    state = "timed_out" if search.timed_out else "completed"
    reason = outcome.reason
    if search.timed_out:
        reason = RunReason(code="time_limit", message="CP-SAT reached its search time limit.")
    if outcome.assignments is None:
        return run(state, SolverResult(outcome=outcome.outcome), reason)

    assignments = list(outcome.assignments)
    # Use the shared scorer to report the penalty in its original units.
    score = score_soft_constraints(
        case.model_dump(), [assignment.model_dump() for assignment in assignments], weights=weights,
    )
    if not isfinite(score.weighted_total):
        return run("failed", None, _objective_range_error())
    return run(state, SolverResult(
        outcome="feasible", assignments=assignments, optimality_proven=search.optimality_proven,
        validation=search.validation,
        score=SoftScore(total=score.weighted_total, components=ScoreComponents(
            s1=CountComponent(value=score.same_day_pairs, **settings["s1"].model_dump()),
            s2=ProportionComponent(value=score.average_unused_seat_proportion, **settings["s2"].model_dump()),
            s3=CountComponent(value=score.teacher_preference_violations, **settings["s3"].model_dump()),
        )),
    ), reason)


# None leaves the time limit unset. Zero gives the solver no time to search.
# Reject negative or nonfinite limits.
def _check_time_limit(time_limit_seconds: float | None) -> None:
    if time_limit_seconds is not None and (
        not isfinite(time_limit_seconds) or time_limit_seconds < 0
    ):
        raise ValueError("time_limit_seconds must be finite and nonnegative")


# Run CP-SAT and check any timetable it finds against the hard rules.
# Return the checked result, whether it is proven optimal, and whether time ran out.
def _search(
    case: SchedulingCase, model: cp_model.CpModel, variables: AssignmentVariables,
    time_limit_seconds: float | None,
) -> _SearchResult:
    solver = cp_model.CpSolver()
    if time_limit_seconds is not None:
        solver.parameters.max_time_in_seconds = time_limit_seconds
    status = solver.solve(model)
    # Mark a timeout only if the search is unfinished and reached its time limit.
    timed_out = (
        status in (cp_model.FEASIBLE, cp_model.UNKNOWN)
        and time_limit_seconds is not None
        and solver.wall_time >= time_limit_seconds
    )

    if status == cp_model.INFEASIBLE:
        return _SearchResult(FeasibilityResult("infeasible_proven", reason=RunReason(
            code="hard_constraints_infeasible",
            message="The hard constraints cannot all be satisfied.",
        )))
    if status == cp_model.UNKNOWN:
        return _SearchResult(FeasibilityResult("no_feasible_found", reason=RunReason(
            code="search_incomplete",
            message="The search ended before finding a timetable or proving infeasibility.",
        )), timed_out=timed_out)
    if status not in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        return _SearchResult(FeasibilityResult("failed", reason=RunReason(
            code="cp_sat_model_error",
            message=model.validate() or f"CP-SAT returned {solver.status_name(status)}.",
        )))

    assignments = tuple(assignment for assignment, variable in variables if solver.boolean_value(variable))
    validation = validate_timetable(case, assignments)
    if validation.hard_violation_count:
        return _SearchResult(FeasibilityResult("failed", reason=RunReason(
            code="invalid_timetable",
            message=f"The solver candidate failed validation. {validation.violations[0].message}",
        )))
    return _SearchResult(
        FeasibilityResult("feasible", assignments=assignments), validation=validation,
        optimality_proven=status == cp_model.OPTIMAL, timed_out=timed_out,
    )


# Turn eligible exam, slot, and room choices into yes/no variables.
# Return the model and its choices, or give a reason if an exam has no choices.
def _build_feasibility_model(
    case: SchedulingCase,
) -> tuple[cp_model.CpModel, AssignmentVariables, RunReason | None]:
    model = cp_model.CpModel()
    variables: AssignmentVariables = []
    resource_intervals: dict[tuple[str, str], list[cp_model.IntervalVar]] = defaultdict(list)
    teachers = {teacher.id: teacher for teacher in case.teachers}
    timings = {slot.id: _slot_timing(slot) for slot in case.slots}

    for exam in case.exams:
        eligible_rooms = [room for room in case.rooms if _allows(exam.allowed_room_ids, room.id)]
        rooms_that_fit = [room for room in eligible_rooms if room.capacity >= exam.headcount]
        teacher = teachers[exam.teacher_id]
        exam_variables: list[cp_model.IntVar] = []

        for slot in case.slots:
            if not _allows(exam.allowed_slot_ids, slot.id) or not _allows(teacher.available_slot_ids, slot.id):
                continue
            start, duration = timings[slot.id]
            slot_variables: list[cp_model.IntVar] = []
            for room in rooms_that_fit:
                if not _allows(room.available_slot_ids, slot.id):
                    continue
                name = f"{exam.id}/{slot.id}/{room.id}"
                selected = model.new_bool_var(f"assign/{name}")
                slot_variables.append(selected)
                variables.append((ExamAssignment(exam_id=exam.id, slot_id=slot.id, room_id=room.id), selected))
                resource_intervals["room", room.id].append(
                    model.new_optional_fixed_size_interval_var(start, duration, selected, f"room/{name}")
                )

            if slot_variables:
                exam_variables.extend(slot_variables)
                # Picking any room books this slot for the exam's teacher and groups.
                slot_selected = model.new_bool_var(f"slot/{exam.id}/{slot.id}")
                model.add(slot_selected == sum(slot_variables))
                interval = model.new_optional_fixed_size_interval_var(
                    start, duration, slot_selected, f"exam/{exam.id}/{slot.id}"
                )
                resource_intervals["teacher", teacher.id].append(interval)
                for group_id in exam.student_group_ids:
                    resource_intervals["group", group_id].append(interval)

        if not exam_variables:
            if eligible_rooms and not rooms_that_fit:
                reason = RunReason(
                    code="no_eligible_room_with_sufficient_capacity",
                    message=f"No eligible room seats all {exam.headcount} students for exam {exam.id}.",
                )
            else:
                reason = RunReason(
                    code="no_eligible_assignment",
                    message=f"Exam {exam.id} has no eligible room and slot combination.",
                )
            return model, variables, reason
        # Each exam must use exactly one of its eligible choices.
        model.add_exactly_one(exam_variables)

    # A room, teacher, or group can use only one active interval at a time.
    for intervals in resource_intervals.values():
        if len(intervals) > 1:
            model.add_no_overlap(intervals)
    return model, variables, None


# Use the case's S1–S3 settings and fill in missing ones with the scorer's defaults.
def _objective_settings(case: SchedulingCase) -> dict[Objective, ObjectiveSetting]:
    names: tuple[Objective, ...] = ("s1", "s2", "s3")
    return {
        name: case.soft_objectives.get(name) or ObjectiveSetting(enabled=True, weight=DEFAULT_WEIGHTS[name])
        for name in names
    }


# Return the costs CP-SAT will add up. S2 and S3 depend on each assignment.
# S1 counts each group shared by two exams on the same day.
def _objective_terms(
    model: cp_model.CpModel, case: SchedulingCase, variables: AssignmentVariables,
    weights: dict[Objective, Fraction],
) -> list[tuple[cp_model.IntVar, Fraction]]:
    exams = {exam.id: exam for exam in case.exams}
    capacities = {room.id: room.capacity for room in case.rooms}
    preferences = {teacher.id: set(teacher.preferred_slot_ids or []) for teacher in case.teachers}
    days = {slot.id: slot.day for slot in case.slots}
    day_choices: dict[tuple[str, str], list[cp_model.IntVar]] = defaultdict(list)
    terms: list[tuple[cp_model.IntVar, Fraction]] = []

    for assignment, variable in variables:
        exam = exams[assignment.exam_id]
        capacity = capacities[assignment.room_id]
        preferred = preferences[exam.teacher_id]
        # Divide by the number of exams to get this assignment's share of the average.
        unused_seats = Fraction(capacity - exam.headcount, capacity * len(exams))
        preference_violation = bool(preferred) and assignment.slot_id not in preferred
        cost = weights["s2"] * unused_seats + weights["s3"] * preference_violation
        if cost:
            terms.append((variable, cost))
        if weights["s1"]:
            day_choices[exam.id, days[assignment.slot_id]].append(variable)

    if not weights["s1"]:
        return terms

    for left, right in combinations(case.exams, 2):
        shared_groups = len(set(left.student_group_ids).intersection(right.student_group_ids))
        if not shared_groups:
            continue
        for day in DAY_INDEX:
            left_choices = day_choices.get((left.id, day))
            right_choices = day_choices.get((right.id, day))
            if not left_choices or not right_choices:
                continue
            # same_day is 1 exactly when both exams are assigned to this day.
            left_on_day, right_on_day = sum(left_choices), sum(right_choices)
            same_day = model.new_bool_var(f"same_day/{left.id}/{right.id}/{day}")
            model.add(same_day <= left_on_day)
            model.add(same_day <= right_on_day)
            model.add(same_day >= left_on_day + right_on_day - 1)
            terms.append((same_day, weights["s1"] * shared_groups))

    return terms


# Turn fractions into whole numbers without rounding. Multiplying every cost
# by the same positive factor keeps the same best timetable.
def _integer_coefficients(costs: list[Fraction]) -> list[int]:
    if not costs:
        return []
    scale = lcm(*(cost.denominator for cost in costs))
    coefficients = [cost.numerator * (scale // cost.denominator) for cost in costs]
    divisor = gcd(*coefficients)
    coefficients = [coefficient // divisor for coefficient in coefficients]
    # Check the largest total the model could represent if every term were active.
    if sum(coefficients) > cp_model.INT_MAX:
        raise OverflowError("Integer objective exceeds the supported range")
    return coefficients


# Use the same error when the model's cost or the reported score is too large.
def _objective_range_error() -> RunReason:
    return RunReason(
        code="objective_out_of_range",
        message="The exact weighted objective exceeds the supported numeric range.",
    )


# An unset list allows every option. An empty list allows none.
def _allows(allowed_ids: list[str] | None, resource_id: str) -> bool:
    return allowed_ids is None or resource_id in allowed_ids


# Return the start minute in the week and the duration. This keeps the same
# clock time on different days separate when checking for clashes.
def _slot_timing(slot: TimeSlot) -> tuple[int, int]:
    start_hour, start_minute = map(int, slot.start_time.split(":"))
    end_hour, end_minute = map(int, slot.end_time.split(":"))
    start = start_hour * 60 + start_minute
    end = end_hour * 60 + end_minute
    return DAY_INDEX[slot.day] * MINUTES_PER_DAY + start, end - start

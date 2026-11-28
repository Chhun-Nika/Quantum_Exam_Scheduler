from typing import Annotated, Literal, Self

from pydantic import Field, JsonValue, StrictBool, StringConstraints, model_validator

from backend.core.case import ContractModel, Identifier, NonnegativeWeight, ObjectiveSetting, PositiveCount

SolverMethod = Literal["exact_search", "cp_sat", "qaoa", "vqe"]
RunState = Literal["queued", "running", "completed", "timed_out", "cancelled", "failed", "skipped"]
SchedulingOutcome = Literal["feasible", "infeasible_proven", "no_feasible_found"]
HardRule = Literal["HC1", "HC2", "HC3", "HC4", "HC5", "HC6", "HC7"]
NonnegativeCount = Annotated[int, Field(strict=True, ge=0)]
Proportion = Annotated[float, Field(strict=True, ge=0, le=1)]
FiniteNumber = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Bitstring = Annotated[str, StringConstraints(pattern=r"^[01]+$")]


class RunReason(ContractModel):
    code: Identifier
    message: Identifier


class MethodEligibility(ContractModel):
    eligible: StrictBool
    reason: RunReason | None = None

    @model_validator(mode="after")
    def check_reason(self) -> Self:
        if self.eligible == (self.reason is not None):
            raise ValueError("An eligibility reason is required only for an ineligible method")
        return self


class EligibilityReport(ContractModel):
    logical_qubits: NonnegativeCount
    quantum_qubit_budget: PositiveCount
    methods: dict[SolverMethod, MethodEligibility]

    @model_validator(mode="after")
    def check_methods(self) -> Self:
        if set(self.methods) != {"exact_search", "cp_sat", "qaoa", "vqe"}:
            raise ValueError("Report eligibility for all four solver methods")
        if self.logical_qubits > self.quantum_qubit_budget and (
            self.methods["qaoa"].eligible or self.methods["vqe"].eligible
        ):
            raise ValueError("Quantum methods are ineligible above the qubit budget")
        return self


class ExamAssignment(ContractModel):
    exam_id: Identifier
    slot_id: Identifier
    room_id: Identifier


class ResourceReference(ContractModel):
    kind: Literal["student_group", "teacher", "room", "slot"]
    id: Identifier


class HardViolation(ContractModel):
    rule_id: HardRule
    message: Identifier
    exam_ids: list[Identifier] = Field(default_factory=list)
    resources: list[ResourceReference] = Field(default_factory=list)


class ValidationDetails(ContractModel):
    hard_violation_count: NonnegativeCount
    violations: list[HardViolation]

    @model_validator(mode="after")
    def check_count(self) -> Self:
        if self.hard_violation_count != len(self.violations):
            raise ValueError("hard_violation_count must match the number of violations")
        return self


class CountComponent(ObjectiveSetting):
    value: NonnegativeCount


class ProportionComponent(ObjectiveSetting):
    value: Proportion


class ScoreComponents(ContractModel):
    s1: CountComponent
    s2: ProportionComponent
    s3: CountComponent


class SoftScore(ContractModel):
    total: NonnegativeWeight
    components: ScoreComponents


class QuantumMetrics(ContractModel):
    simulator: Identifier | None = None
    noise_settings: dict[str, JsonValue] | None = None
    logical_qubits: NonnegativeCount | None = None
    circuit_depth: NonnegativeCount | None = None
    optimizer_iterations: NonnegativeCount | None = None
    measurement_shots: PositiveCount | None = None
    measurement_counts: dict[Bitstring, NonnegativeCount] | None = None
    best_measured_energy: FiniteNumber | None = None


class SolverResult(ContractModel):
    outcome: SchedulingOutcome
    assignments: Annotated[list[ExamAssignment], Field(min_length=1)] | None = None
    optimality_proven: StrictBool | None = None
    score: SoftScore | None = None
    validation: ValidationDetails | None = None
    candidate_validation: ValidationDetails | None = None
    quantum: QuantumMetrics | None = None

    @model_validator(mode="after")
    def check_timetable_fields(self) -> Self:
        timetable_fields = (self.assignments, self.optimality_proven, self.score, self.validation)
        if self.outcome == "feasible":
            if any(value is None for value in timetable_fields):
                raise ValueError("A feasible result requires assignments, proof status, score, and validation")
            if self.validation is not None and self.validation.hard_violation_count:
                raise ValueError("A feasible timetable must have zero hard violations")
        elif any(value is not None for value in timetable_fields):
            raise ValueError("Timetable fields must be null when no feasible result was found")
        return self


class RunProgress(ContractModel):
    current_iteration: NonnegativeCount
    max_iterations: PositiveCount | None = None


class SearchStatistics(ContractModel):
    total_candidates: NonnegativeCount
    checked_candidates: NonnegativeCount
    feasible_candidates: NonnegativeCount
    infeasible_candidates: NonnegativeCount
    search_completed: StrictBool
    search_elapsed_ms: NonnegativeWeight | None = None

    @model_validator(mode="after")
    def check_counts(self) -> Self:
        if self.checked_candidates != self.feasible_candidates + self.infeasible_candidates:
            raise ValueError("Checked candidates must equal feasible plus infeasible candidates")
        if self.checked_candidates > self.total_candidates:
            raise ValueError("Checked candidates cannot exceed total candidates")
        if self.search_completed and self.checked_candidates != self.total_candidates:
            raise ValueError("A completed search must check every candidate")
        return self


class SolverRun(ContractModel):
    run_id: Identifier
    method: SolverMethod
    state: RunState
    elapsed_ms: NonnegativeCount | None
    result: SolverResult | None
    progress: RunProgress | None = None
    reason: RunReason | None = None
    search_statistics: SearchStatistics | None = None

    @model_validator(mode="after")
    def check_state(self) -> Self:
        if (self.state in {"queued", "skipped"}) != (self.elapsed_ms is None):
            raise ValueError("Elapsed time must be null only for queued or skipped runs")
        if (self.state in {"completed", "timed_out", "cancelled"}) != (self.result is not None):
            raise ValueError("A result is required only for completed, timed-out or cancelled runs")
        if self.state in {"failed", "skipped", "timed_out", "cancelled"} and self.reason is None:
            raise ValueError("A reason is required for failed, skipped, timed-out or cancelled runs")
        return self

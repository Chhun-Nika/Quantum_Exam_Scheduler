# Project documentation

The [implementation plan](../../docs/IMPLEMENTATION_PLAN.md) records the selected structure, constraints, and planned work. The [project record](../../docs/PROJECT.md) tracks decisions and progress. The [report contents](../../docs/report/README.md) link to the report sections.

## Shared scheduling contract

[`SchedulingCase`](../backend/core/case.py) describes fixed exam sessions and their resources. The [three-session example](../data/example.json) is validated and served at `GET /api/cases/example`. An omitted or `null` eligibility or availability list means unrestricted. An empty list means no options. An omitted or empty teacher preference list means no preference.

[`EligibilityReport` and `SolverRun`](../backend/core/result.py) describe preflight and per-method results. Run state is separate from the scheduling outcome, so a timeout can still carry a feasible timetable. Omitted objective settings stay unset until the shared scorer applies its defaults.

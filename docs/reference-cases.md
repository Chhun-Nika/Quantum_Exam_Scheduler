# Hand-checked scheduling reference cases

These small fixtures give every solver and the web app known outcomes to use
for correctness checks. They use the shared case and result format described in
`07-shared-case-and-solver-result-formats.md`.

## Feasible two-session case

Files:

- `data/reference_cases/feasible-case.json`
- `data/reference_cases/feasible-expected-result.json`

The only valid assignments are E1 in R1 at `MON_09` and E2 in R2 at
`MON_11`. The two slots meet at 11:00 but do not overlap, so shared teacher T1
and group G1 have no hard conflict. Both room capacities are sufficient.

The hand-checked soft score is:

| Component | Calculation | Value |
| --- | --- | ---: |
| S1 | G1 has E1 and E2 on Monday: one unordered pair. | 1 |
| S2 | `((40 - 30) / 40 + (25 - 20) / 25) / 2` | 0.225 |
| S3 | T1 prefers `MON_09`; E2 is at `MON_11`. | 1 |
| Total | `1 * 1 + 1 * 0.225 + 1 * 1` | 2.225 |

## Infeasible capacity case

Files:

- `data/reference_cases/infeasible-capacity-case.json`
- `data/reference_cases/infeasible-capacity-expected-result.json`

E1 has 35 students. Its only eligible room, R1, has capacity 30. Although the
teacher and room are available in both slots, no assignment can satisfy the
room-capacity hard constraint. The expected outcome is `infeasible_proven`
with reason code `no_eligible_room_with_sufficient_capacity`.

This fixture demonstrates the kind of clear explanation that the web app can
show a scheduler: the input cannot be scheduled unless they choose a larger
eligible room, reduce the session headcount, or change the session setup.

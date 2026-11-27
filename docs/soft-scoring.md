# Shared soft-constraint score

Every classical and quantum solver must return the four values produced by
`backend.core.scoring.score_soft_constraints`. Keeping the score in one module
means that solver-specific objectives can be compared fairly.

## Input contract

The scorer takes JSON-style `case` and `timetable` values. Each exam needs an
`id`, `student_groups`, `teacher`, and non-negative integer `enrollment`. Each
room needs an `id` and positive integer `capacity`; each slot needs an `id`,
`day`, `start_time`, and `end_time` (for example `"09:00"` and `"11:00"`).
`teacher_preferences` is a mapping from a teacher name to preferred slot IDs.
A timetable is either a mapping from exam ID to `{ "slot_id", "room_id" }` or a
list of objects that also include `exam_id`.

The timetable must assign every exam exactly once and refer only to known rooms
and slots. Hard validity (clashes, capacity, eligibility, and availability) is
checked separately by the shared validator.

## Components and agreed defaults

- **S1 — `same_day_pairs`**: for each student group, count every unordered pair
  of that group's exams that occur on the same calendar day. A pair shared by
  two groups counts once for each group, because it burdens both groups.
  The exact start and end times do not alter S1; they remain available for the
  hard-constraint validator to detect overlapping exams and for preferences to
  select a particular slot.
- **S2 — `average_unused_seat_proportion`**: for each assigned exam, calculate
  `(room capacity - enrollment) / room capacity`, then take the arithmetic mean
  across all exams. This makes S2 independent of the number of exams and keeps
  it in the `[0, 1]` range for a hard-valid timetable.
- **S3 — `teacher_preference_violations`**: count one violation for each exam
  placed outside its teacher's listed preferred slots. A missing or empty
  preference list means *no preference*, so it adds zero violations.

The default relative weights are **S1:S2:S3 = 1:1:1**. They are deliberately
neutral and are returned with every score. Callers may supply non-negative
`s1`, `s2`, and `s3` overrides for an experiment, but must record them with the
result. The total is `s1 * S1 + s2 * S2 + s3 * S3`.

## Hand-calculated example

For the test case in `tests/test_scoring.py`, E1 and E2 share G1 and are both
on Monday, so S1 is `1`. Their unused-seat proportions are `(10 - 8)/10 = 0.2`,
`(20 - 10)/20 = 0.5`, and `(20 - 10)/20 = 0.5`, so S2 is
`(0.2 + 0.5 + 0.5)/3 = 0.4`. E2 is outside Teacher B's preferred slot, so S3
is `1`; Teacher A has no preference and adds zero. With weights S1=2, S2=10,
S3=3, the total is `2(1) + 10(0.4) + 3(1) = 9`.

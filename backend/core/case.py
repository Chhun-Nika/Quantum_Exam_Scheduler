from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints, model_validator

Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
PositiveCount = Annotated[int, Field(strict=True, gt=0)]
NonnegativeWeight = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
ClockTime = Annotated[str, StringConstraints(pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")]
Weekday = Literal["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
Objective = Literal["s1", "s2", "s3"]


class ContractModel(BaseModel):
    # Catch misspelled fields when loading a case or solver result.
    model_config = ConfigDict(extra="forbid")


class StudentGroup(ContractModel):
    id: Identifier
    student_count: PositiveCount
    name: Identifier | None = None


class Teacher(ContractModel):
    id: Identifier
    name: Identifier | None = None
    # Availability is a hard restriction. Preferences affect the soft score.
    available_slot_ids: list[Identifier] | None = None
    preferred_slot_ids: list[Identifier] | None = None


class Room(ContractModel):
    id: Identifier
    capacity: PositiveCount
    name: Identifier | None = None
    room_type: Identifier | None = None
    available_slot_ids: list[Identifier] | None = None


class TimeSlot(ContractModel):
    id: Identifier
    day: Weekday
    start_time: ClockTime
    end_time: ClockTime
    name: Identifier | None = None

    @model_validator(mode="after")
    def check_interval(self) -> Self:
        # Zero-padded 24-hour strings sort in chronological order within a day.
        if self.start_time >= self.end_time:
            raise ValueError("start_time must be before end_time on the same day")
        return self


class ExamSession(ContractModel):
    id: Identifier
    subject: Identifier
    # Each session already has its groups, teacher, and total enrollment.
    student_group_ids: Annotated[list[Identifier], Field(min_length=1)]
    teacher_id: Identifier
    headcount: PositiveCount
    # None allows all options at this stage. An empty list allows none.
    allowed_room_ids: list[Identifier] | None = None
    allowed_slot_ids: list[Identifier] | None = None


class ObjectiveSetting(ContractModel):
    enabled: StrictBool
    weight: NonnegativeWeight


def unique_ids(ids: list[str], field: str) -> set[str]:
    unique = set(ids)
    if len(unique) != len(ids):
        raise ValueError(f"{field} contains duplicate IDs")
    return unique


def validate_references(ids: list[str] | None, known: set[str], field: str) -> None:
    if ids is None:
        return
    unknown = unique_ids(ids, field) - known
    if unknown:
        raise ValueError(f"{field} references unknown IDs: {', '.join(sorted(unknown))}")


class SchedulingCase(ContractModel):
    exams: Annotated[list[ExamSession], Field(min_length=1)]
    student_groups: Annotated[list[StudentGroup], Field(min_length=1)]
    teachers: Annotated[list[Teacher], Field(min_length=1)]
    rooms: Annotated[list[Room], Field(min_length=1)]
    slots: Annotated[list[TimeSlot], Field(min_length=1)]
    soft_objectives: dict[Objective, ObjectiveSetting] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_references(self) -> Self:
        # Check IDs across the case once all five collections have been parsed.
        unique_ids([exam.id for exam in self.exams], "exams")
        group_ids = unique_ids([group.id for group in self.student_groups], "student_groups")
        teacher_ids = unique_ids([teacher.id for teacher in self.teachers], "teachers")
        room_ids = unique_ids([room.id for room in self.rooms], "rooms")
        slot_ids = unique_ids([slot.id for slot in self.slots], "slots")

        for exam in self.exams:
            field = f"exam {exam.id}"
            validate_references(exam.student_group_ids, group_ids, f"{field}.student_group_ids")
            validate_references([exam.teacher_id], teacher_ids, f"{field}.teacher_id")
            validate_references(exam.allowed_room_ids, room_ids, f"{field}.allowed_room_ids")
            validate_references(exam.allowed_slot_ids, slot_ids, f"{field}.allowed_slot_ids")
        for teacher in self.teachers:
            validate_references(teacher.available_slot_ids, slot_ids, f"teacher {teacher.id}.available_slot_ids")
            validate_references(teacher.preferred_slot_ids, slot_ids, f"teacher {teacher.id}.preferred_slot_ids")
        for room in self.rooms:
            validate_references(room.available_slot_ids, slot_ids, f"room {room.id}.available_slot_ids")
        return self

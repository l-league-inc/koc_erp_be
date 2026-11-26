from typing import Literal, Optional

from ninja import Field, Schema


class AttendanceActionSchema(Schema):
    workspace_id: int = Field(description="워크스페이스 id")


class AttendanceStatusSchema(Schema):
    state: Literal["none", "in", "out"] = Field(
        description="none은 출근 전, in은 출근만 됨, out은 퇴근까지 됨"
    )
    record_id: Optional[int] = Field(None, description="오늘 근무 기록 id")
    title: str = Field("", description="근무 기록 제목")
    work_date: str = Field(description="근무일 YYYY-MM-DD")
    check_in: Optional[str] = Field(None, description="출근시각 YYYY-MM-DDTHH:MM:SS")
    check_out: Optional[str] = Field(None, description="퇴근시각 YYYY-MM-DDTHH:MM:SS")
    employee_id: int = Field(description="임직원 레코드 id")
    employee_title: str = Field(description="임직원 이름")

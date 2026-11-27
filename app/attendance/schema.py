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
    overtime_minutes: Optional[int] = Field(None, description="신청한 야근 시간(분). 없으면 null")
    overtime_reason: Optional[str] = Field(None, description="야근 사유")
    overtime_status: Optional[str] = Field(None, description="대기, 승인, 반려. 없으면 null")
    employee_id: int = Field(description="임직원 레코드 id")
    employee_title: str = Field(description="임직원 이름")


class OvertimeRequestSchema(Schema):
    workspace_id: int = Field(description="워크스페이스 id")
    minutes: int = Field(description="야근 시간(분). 1 이상 720 이하")
    reason: str = Field("", description="야근 사유")


class OvertimeDecisionSchema(Schema):
    workspace_id: int = Field(description="워크스페이스 id")
    record_id: int = Field(description="근무 기록 id")
    decision: Literal["승인", "반려"] = Field(description="승인 또는 반려")

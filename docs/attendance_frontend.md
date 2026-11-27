---
title: 출근·퇴근·야근
audience: frontend
---

# 출근·퇴근·야근

홈이나 근태 화면에 출근 버튼과 퇴근 버튼을 둡니다. 시각 입력란은 없습니다. 버튼을 누르면 서버가 지금 시각을 근무 기록에 넣습니다. 야근은 분 단위로 신청하고, 관리자가 승인하기 전에는 근무 시간에 포함하지 않습니다. 인증은 기존 JWT입니다.

기록은 워크스페이스 `attendance` 데이터베이스의 오늘 행입니다. 출근시각은 `check_in`, 퇴근시각은 `check_out`, 근무일은 `work_date`입니다. 야근 시간은 `overtime_minutes`, 사유는 `overtime_reason`, 승인 상태는 `overtime_status`입니다. 임직원은 로그인 계정의 이메일과 같은 행을 먼저 쓰고, 없으면 계정 이름과 제목이 같은 행을 씁니다.

## 유저 플로우

1. 워크스페이스를 연 뒤 `GET /api/v1/attendance/today?workspace_id=`로 오늘 상태를 가져옵니다.
2. `state`가 `none`이면 출근 버튼을 보여 줍니다. `in`이면 퇴근 버튼을 보여 줍니다. `out`이면 버튼을 끄고 출근시각과 퇴근시각을 보여 줍니다.
3. 출근은 `POST /api/v1/attendance/clock-in`에 `workspace_id`만 보냅니다. 응답 `check_in`이 저장된 출근시각입니다.
4. 퇴근은 `POST /api/v1/attendance/clock-out`에 `workspace_id`만 보냅니다. 응답 `check_out`이 저장된 퇴근시각입니다.
5. 출근한 뒤에만 야근을 신청합니다. `POST /api/v1/attendance/overtime`에 `workspace_id`, `minutes`, `reason`을 보냅니다. 응답 `overtime_status`는 `대기`입니다.
6. 관리자 화면은 `overtime_status`가 `대기`인 행에 승인·반려 버튼을 둡니다. `POST /api/v1/attendance/overtime/decide`에 `workspace_id`, `record_id`, `decision`(`승인` 또는 `반려`)을 보냅니다.
7. `승인`이면 그 분을 야근 시간으로 보여 줍니다. `대기`와 `반려`는 야근 시간에 넣지 않습니다.
8. 409는 이미 출근했거나 이미 퇴근한 경우입니다. 문구를 보여 주고 `GET /today`로 버튼을 다시 맞춥니다.
9. 400은 임직원을 한 명으로 정하지 못했거나, 오늘 출근 없이 퇴근·야근을 했거나, 근무 기록이 없는 경우입니다.
10. 403은 멤버가 시각을 고치거나, 승인된 야근을 고치거나, 멤버가 승인 버튼을 누른 경우입니다.

## API

기본 경로는 `/api/v1/attendance`입니다.

- `GET /today?workspace_id=` 오늘 상태
- `POST /clock-in` 출근. 본문은 `workspace_id`만
- `POST /clock-out` 퇴근. 본문은 `workspace_id`만
- `POST /overtime` 야근 신청. 본문은 `workspace_id`, `minutes`, `reason`
- `POST /overtime/decide` 야근 승인·반려. 관리자만

출퇴근 시각 필드는 요청에 없습니다.

### 출퇴근 요청

```json
{ "workspace_id": 1 }
```

### 야근 신청

`minutes`는 1 이상 720 이하의 정수입니다. 12시간을 넘기면 400입니다. `reason`은 비워도 되고 500자 이하입니다.

```json
{ "workspace_id": 1, "minutes": 120, "reason": "납품 마감" }
```

오늘 출근 행이 없으면 400 `출근 기록이 없습니다.` 이미 `승인`된 야근을 다시 신청하면 403 `승인된 야근 시간은 수정할 수 없습니다.`

### 야근 승인

```json
{ "workspace_id": 1, "record_id": 10, "decision": "승인" }
```

`decision`은 `승인` 또는 `반려`입니다. 멤버가 호출하면 403 `관리자만 야근을 승인할 수 있습니다.` 신청 분이 없으면 400 `야근 신청이 없습니다.` 승인하면 가능하면 `confirmed_by`에 승인한 관리자의 임직원 행을 넣습니다.

### 응답

다섯 API의 200 응답은 같습니다.

```json
{
  "state": "in",
  "record_id": 10,
  "title": "2026-11-26 출근",
  "work_date": "2026-11-26",
  "check_in": "2026-11-26T09:01:02",
  "check_out": null,
  "overtime_minutes": 120,
  "overtime_reason": "납품 마감",
  "overtime_status": "대기",
  "employee_id": 3,
  "employee_title": "김근무"
}
```

- `state`: `none` 출근 전, `in` 출근만 됨, `out` 퇴근까지 됨
- `record_id`: 오늘 행. 없으면 `null`. `none`인데 `record_id`가 있으면 출근 버튼이 그 행의 출근시각을 채웁니다.
- `work_date`: `YYYY-MM-DD`
- `check_in`, `check_out`: `YYYY-MM-DDTHH:MM:SS`. 없으면 `null`
- `overtime_minutes`: 신청한 분. 없으면 `null`. `승인`일 때만 야근 시간으로 셉니다.
- `overtime_status`: `대기`, `승인`, `반려`. 신청이 없으면 `null`
- 제목은 `{근무일} 출근`입니다.

### 알림

야근 신청이 접수되면 소유자와 관리자에게 알림이 갑니다. 신청한 사람 자신에게는 가지 않습니다. 메시지는 `{이름}님이 야근 {분}분을 신청했습니다.` 입니다.

```json
{
  "kind": "overtime",
  "workspace_id": 1,
  "record_id": 10,
  "database_slug": "attendance"
}
```

`record_id`로 근무 기록을 엽니다.

### 표에서 직접 수정

근무 기록 표의 저장은 `PATCH /api/v1/workspace/record/{record_id}`입니다.

- 멤버는 `check_in`, `check_out`, `registered_at`을 바꾸지 못합니다. 403 `출근·퇴근 시각은 직접 수정할 수 없습니다.`
- 멤버는 지난 근무일이나 다른 임직원으로 행을 만들지 못합니다. 403 `근무일과 임직원은 본인 오늘 기록만 만들 수 있습니다.`
- 멤버는 이미 있는 근무일과 임직원을 바꾸지 못합니다.
- 멤버가 `overtime_minutes`를 저장하면 상태는 `대기`가 됩니다. `overtime_status`를 `승인`이나 `반려`로 저장하면 403입니다.
- `승인`된 야근의 시간과 사유는 멤버가 고치지 못합니다.
- 멤버는 다른 사람 행에 야근을 넣지 못합니다. 403 `본인 근무 기록에만 야근을 신청할 수 있습니다.`
- 멤버는 근무 기록을 삭제하지 못합니다. 403 `근무 기록은 직접 삭제할 수 없습니다.`
- 관리자는 표에서 시각을 고치고 야근을 승인할 수 있습니다. 대화와 MCP로 시각을 넣는 것은 관리자도 거절됩니다.

### 오류

- 401 로그인 필요
- 403 워크스페이스 멤버가 아님, 또는 위의 수정 제한
- 404 워크스페이스 없음, 또는 `근무 기록을 찾을 수 없습니다.`
- 400 `임직원 기록이 없습니다.` 또는 `임직원 기록이 여러 건입니다.`
- 400 `근무 기록 데이터베이스가 없습니다.` 또는 `근무 기록에 필요한 속성이 없습니다.`
- 400 `출근 기록이 없습니다.` 퇴근만 누르거나 출근 없이 야근을 신청한 경우
- 400 `야근 시간은 1분 이상 720분 이하입니다.`
- 400 `야근 사유는 500자 이하입니다.`
- 400 `야근 신청이 없습니다.`
- 409 `오늘 출근은 이미 있습니다.` 또는 `오늘 퇴근은 이미 있습니다.`

본문은 `{ "detail": "오늘 출근은 이미 있습니다." }`입니다.

## 구현 체크리스트

- 화면을 열면 `GET /today`로 `state`를 그린다.
- `none`이면 출근 버튼, `in`이면 퇴근 버튼, `out`이면 두 버튼을 끈다.
- 요청 본문에는 출퇴근 때 `workspace_id`만 넣는다. 시각 입력란을 만들지 않는다.
- 성공 응답의 `check_in`, `check_out`을 그대로 보여 준다.
- 출근 뒤에 야근 분과 사유를 보내고, `overtime_status`가 `승인`일 때만 야근 시간으로 보여 준다.
- 관리자에게 `대기` 목록과 승인·반려 버튼을 둔다.
- `metadata.kind`가 `overtime`인 알림을 누르면 그 `record_id`의 근무 기록을 연다.
- 409, 400, 403의 `detail`을 안내 문구로 보여 주고, 필요하면 `GET /today`를 다시 호출한다.
- 채팅으로 만든 오늘 행은 같은 `record_id`를 쓴다. 버튼이 새 행을 만들지 않는다.

## 비범위

- 자정을 넘긴 퇴근. 퇴근은 오늘 행만 갱신합니다.
- 멤버가 시각을 고치거나 과거 시각으로 출근하는 기능.
- 다른 사람 대신 출근·퇴근·야근 신청.
- 휴가, 출장, 근태상태, 근무형태 변경. 그 칸은 비워 둡니다.

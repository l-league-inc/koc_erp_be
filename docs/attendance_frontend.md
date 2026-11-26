---
title: 출근·퇴근
audience: frontend
---

# 출근·퇴근

홈이나 근태 화면에 출근 버튼과 퇴근 버튼을 둡니다. 시각 입력란은 없습니다. 버튼을 누르면 서버가 지금 시각을 근무 기록에 넣습니다. 인증은 기존 JWT입니다.

기록은 워크스페이스 `attendance` 데이터베이스의 오늘 행입니다. 출근시각은 `check_in`, 퇴근시각은 `check_out`, 근무일은 `work_date`입니다. 임직원은 로그인 계정의 이메일과 같은 행을 먼저 쓰고, 없으면 계정 이름과 제목이 같은 행을 씁니다.

## 유저 플로우

1. 워크스페이스를 연 뒤 `GET /api/v1/attendance/today?workspace_id=`로 오늘 상태를 가져옵니다.
2. `state`가 `none`이면 출근 버튼을 보여 줍니다. `in`이면 퇴근 버튼을 보여 줍니다. `out`이면 버튼을 끄고 출근시각과 퇴근시각을 보여 줍니다.
3. 출근은 `POST /api/v1/attendance/clock-in`에 `workspace_id`만 보냅니다. 응답 `check_in`이 저장된 출근시각입니다.
4. 퇴근은 `POST /api/v1/attendance/clock-out`에 `workspace_id`만 보냅니다. 응답 `check_out`이 저장된 퇴근시각입니다.
5. 409는 이미 출근했거나 이미 퇴근한 경우입니다. 문구를 보여 주고 `GET /today`로 버튼을 다시 맞춥니다.
6. 400은 임직원을 한 명으로 정하지 못했거나, 오늘 출근 없이 퇴근했거나, 근무 기록이 없는 경우입니다.

## API

기본 경로는 `/api/v1/attendance`입니다.

- `GET /today?workspace_id=` 오늘 상태
- `POST /clock-in` 출근. 본문은 `workspace_id`만
- `POST /clock-out` 퇴근. 본문은 `workspace_id`만

시각 필드는 요청에 없습니다.

### 요청

```json
{ "workspace_id": 1 }
```

### 응답

세 API의 200 응답은 같습니다.

```json
{
  "state": "in",
  "record_id": 10,
  "title": "2026-11-26 출근",
  "work_date": "2026-11-26",
  "check_in": "2026-11-26T09:01:02",
  "check_out": null,
  "employee_id": 3,
  "employee_title": "김근무"
}
```

- `state`: `none` 출근 전, `in` 출근만 됨, `out` 퇴근까지 됨
- `record_id`: 오늘 행. 없으면 `null`. `none`인데 `record_id`가 있으면 출근 버튼이 그 행의 출근시각을 채웁니다.
- `work_date`: `YYYY-MM-DD`
- `check_in`, `check_out`: `YYYY-MM-DDTHH:MM:SS`. 없으면 `null`
- 제목은 `{근무일} 출근`입니다.

### 오류

- 401 로그인 필요
- 403 워크스페이스 멤버가 아님
- 404 워크스페이스 없음
- 400 `임직원 기록이 없습니다.` 또는 `임직원 기록이 여러 건입니다.`
- 400 `근무 기록 데이터베이스가 없습니다.` 또는 `근무 기록에 필요한 속성이 없습니다.`
- 400 `출근 기록이 없습니다.` 퇴근만 누른 경우
- 409 `오늘 출근은 이미 있습니다.` 또는 `오늘 퇴근은 이미 있습니다.`

본문은 `{ "detail": "오늘 출근은 이미 있습니다." }`입니다.

## 구현 체크리스트

- 화면을 열면 `GET /today`로 `state`를 그린다.
- `none`이면 출근 버튼, `in`이면 퇴근 버튼, `out`이면 두 버튼을 끈다.
- 요청 본문에는 `workspace_id`만 넣는다. 시각 입력란을 만들지 않는다.
- 성공 응답의 `check_in`, `check_out`을 그대로 보여 준다.
- 409와 400의 `detail`을 안내 문구로 보여 주고, 필요하면 `GET /today`를 다시 호출한다.
- 채팅으로 만든 오늘 행은 같은 `record_id`를 쓴다. 버튼이 새 행을 만들지 않는다.

## 비범위

- 자정을 넘긴 퇴근. 퇴근은 오늘 행만 갱신합니다.
- 시각을 고치거나 과거 시각으로 출근하는 기능.
- 다른 사람 대신 출근·퇴근.
- 휴가, 출장, 근태상태, 근무형태 변경. 그 칸은 비워 둡니다.

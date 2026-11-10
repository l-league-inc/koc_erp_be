---
title: 워크봇 API
audience: frontend
---

# 워크봇 API

자동화 워크봇 화면의 목록, 켜기, 실행 이력, 통계를 다룹니다. 인증은 기존 JWT입니다. `notify`와 `create_record`는 저장된 spec대로만 실행하고 모델을 부르지 않습니다. `agent`는 일정 시각마다 저장된 지시(`instruction`)를 모델이 도구로 수행하므로 그때마다 모델을 씁니다. 초안 작성도 모델을 사용합니다.

## 예약 실행

서버가 30초마다 `enabled`이고 `next_run_at`이 지난 봇을 찾아 실행합니다. 봇을 만들거나 켜면 `next_run_at`이 채워지고, 실행이 시작되면 바로 다음 일정으로 넘어가므로 같은 일정이 두 번 실행되지 않습니다. 서버가 잠시 내려가 있어 놓친 일정은 올라온 뒤 한 번만 실행합니다. 시각은 서버 시간대(Asia/Seoul) 기준입니다. 일정으로 실행된 봇이 실패하면 만든 사용자에게 알림이 갑니다(`실행 실패: 사유`). 지금 실행으로 실패한 경우는 응답의 `failed`만 있습니다.

## 유저 플로우

1. `GET /api/v1/workbot`으로 내 워크봇을 그립니다. `enabled`가 켜진 봇만 일정에 실행됩니다.
2. `GET /api/v1/workbot/stats`로 활성 수, 이번 달 실행, 성공률, 절약 시간을 채웁니다.
3. `GET /api/v1/workbot/run`으로 최근 실행을 그립니다. `success`는 반영된 실행, `waiting`은 확인 대기, `failed`는 실패입니다.
4. 새 봇은 `POST /api/v1/workbot/draft`에 문장을 보내 초안을 받은 뒤, 사용자가 저장할 때 `POST /api/v1/workbot`으로 만듭니다. 초안의 이름, 설명, 알림 문구, 레코드 제목과 값은 요청 문장을 따른 한국어입니다. 날짜 기간은 `period`처럼 스키마에 있는 date 속성에 `{start, end}`로 들어옵니다. 초안 모델은 `GET /api/v1/agent/model`의 선택과 같고, 이번 초안만 바꾸려면 `model`을 함께 보냅니다.
5. 스위치는 `PATCH /api/v1/workbot/{workbot_id}`의 `enabled`입니다.
6. `waiting` 실행은 `POST /api/v1/workbot/run/{run_id}/confirm`으로 반영합니다.

## spec

```json
{
  "filters": [{"property": "status", "op": "eq", "value": "대기"}],
  "action": "notify",
  "notify_user_ids": [1],
  "message": "미작성 업무가 있습니다",
  "requires_confirmation": false,
  "record": null
}
```

`action`은 세 가지입니다.

- `notify`: `filters`에 맞는 레코드가 있으면 알림만 보냅니다.
- `create_record`: 매번 같은 제목·값·`record.blocks`로 레코드를 만듭니다. 본문 `blocks`를 넣지 않으면 빈 페이지가 만들어집니다.
- `agent`: 실행 때마다 모델이 `instruction`대로 레코드를 조회하고 본문이 채워진 페이지를 만들거나 고칩니다. 주간·일일 보고서처럼 내용이 매번 달라지는 문서는 이 동작입니다. `message`는 알림 앞머리이고, 알림 문구는 `message: 모델 요약`(200자 이내)입니다. `requires_confirmation`이 true이면 쓰기는 대기열(`payload.pending`)에 쌓이고, 확인 API를 부를 때 반영됩니다. 초안은 이 동작을 고르면 `spec.filters`를 비웁니다.

`agent` 예:

```json
{
  "action": "agent",
  "filters": [],
  "notify_user_ids": [],
  "message": "주간 근태 보고서",
  "requires_confirmation": false,
  "record": null
}
```

`action`이 `create_record`이면 `record.title`이 필요합니다. `notify_user_ids`가 비어 있으면 봇을 만든 사용자에게 알립니다. `schedule`은 `분 시 일 월 요일` 크론입니다. 예: 매일 09:30은 `30 9 * * *`, 매주 월요일 10:00은 `0 10 * * 1`.

알림은 기존 알림 API에 쌓입니다. `metadata`는 `workbot_id`, `run_id`입니다.

## API

기본 경로는 `/api/v1/workbot`입니다.

- `GET /` 목록
- `POST /` 생성. 201
- `PATCH /{workbot_id}` 수정
- `DELETE /{workbot_id}` 소프트 삭제. 204
- `GET /stats` `active_count`, `month_run_count`, `success_rate`, `saved_minutes`
- `GET /run` 최근 50건. `workbot_id` 쿼리로 한 봇만 볼 수 있습니다.
- `POST /draft` 초안. 저장하지 않습니다.
- `POST /{workbot_id}/run` 지금 실행
- `POST /run/{run_id}/confirm` 확인 대기 반영

봇 항목은 `id`, `workspace_id`, `owner_id`, `name`, `description`, `instruction`, `spec`, `schedule`, `enabled`, `database_slug`, `estimated_minutes`, `next_run_at`, `last_run_at`, `created_at`, `updated_at`입니다. 생성 본문도 같은 필드에서 `id`와 실행 시각을 뺍니다. `workspace_id`와 `database_slug`는 생성에 필요합니다. 초안 요청은 `workspace_id`, `instruction`, `model`입니다. `model`을 비우면 `GET /api/v1/agent/model`에 저장된 선택을 쓰고, 값을 넣으면 그 초안에 쓰며 선택도 바꿉니다. 초안 응답은 `name`, `description`, `instruction`, `database_slug`, `schedule`, `estimated_minutes`, `spec`이고 저장되지 않습니다.

실행 항목은 `id`, `workbot_id`, `status`(`success`/`waiting`/`failed`), `summary`, `record_ids`, `payload`, `created_at`입니다. 통계는 `active_count`, `month_run_count`, `success_rate`, `saved_minutes`입니다.

절약 시간은 봇의 `estimated_minutes`에 이번 달 성공 횟수를 곱한 값입니다. 사이드바 뱃지는 `active_count`입니다. 알림의 읽지 않은 개수와는 다릅니다.

없는 봇은 404, 다른 워크스페이스는 403, 일정 형식이 다르면 400입니다.

## 구현 체크리스트

- 목록의 스위치는 `enabled`만 보냅니다.
- 최근 실행의 점은 `success`와 그 외를 구분합니다.
- AI 요청은 draft 응답을 미리보기로 보여주고, 만들기 버튼을 누를 때 생성 API를 호출합니다.
- `waiting` 항목에 확인 동작을 붙입니다.
- `spec.action`이 `agent`인 봇도 목록·편집에서 그대로 보여 줍니다. `record`는 null일 수 있습니다.
- 실행 실패 알림은 일반 알림과 같은 API로 오고 `metadata`에 `workbot_id`, `run_id`가 있습니다.

## 비범위

- 워크봇 삭제, 멤버 변경, 스키마 변경을 MCP 도구로 여는 것
- `agent`가 레코드 삭제, 멤버 변경, 스키마 변경을 하는 것(레코드 생성·수정과 조회만 합니다)

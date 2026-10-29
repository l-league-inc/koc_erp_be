---
title: 워크봇 API
audience: frontend
---

# 워크봇 API

자동화 워크봇 화면의 목록, 켜기, 실행 이력, 통계를 다룹니다. 인증은 기존 JWT입니다. 실행은 저장된 spec을 따르고, 매번 언어 모델을 부르지 않습니다. 초안 작성만 모델을 사용합니다.

## 유저 플로우

1. `GET /api/v1/workbot`으로 내 워크봇을 그립니다. `enabled`가 켜진 봇만 일정에 실행됩니다.
2. `GET /api/v1/workbot/stats`로 활성 수, 이번 달 실행, 성공률, 절약 시간을 채웁니다.
3. `GET /api/v1/workbot/run`으로 최근 실행을 그립니다. `success`는 반영된 실행, `waiting`은 확인 대기, `failed`는 실패입니다.
4. 새 봇은 `POST /api/v1/workbot/draft`에 문장을 보내 초안을 받은 뒤, 사용자가 저장할 때 `POST /api/v1/workbot`으로 만듭니다.
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

절약 시간은 봇의 `estimated_minutes`에 이번 달 성공 횟수를 곱한 값입니다. 사이드바 뱃지는 `active_count`입니다. 알림의 읽지 않은 개수와는 다릅니다.

없는 봇은 404, 다른 워크스페이스는 403, 일정 형식이 다르면 400입니다.

## 구현 체크리스트

- 목록의 스위치는 `enabled`만 보냅니다.
- 최근 실행의 점은 `success`와 그 외를 구분합니다.
- AI 요청은 draft 응답을 미리보기로 보여주고, 만들기 버튼을 누를 때 생성 API를 호출합니다.
- `waiting` 항목에 확인 동작을 붙입니다.

## 비범위

- 워크봇 삭제, 멤버 변경, 스키마 변경을 MCP 도구로 여는 것
- 실행할 때마다 문장을 다시 모델에 보내는 것

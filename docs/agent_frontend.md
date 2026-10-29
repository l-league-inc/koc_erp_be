---
title: 업무 대화 API
audience: frontend
---

# 업무 대화 API

홈 입력창과 출근, 일정, 견적, 출장, A/S 단축은 같은 API를 씁니다. 단축은 프롬프트 문장만 다릅니다. 인증은 기존 JWT입니다.

모델 호출은 서버가 합니다. 생성과 수정은 초안으로 돌아오고, 사용자가 확정한 뒤에만 워크스페이스에 저장됩니다.

## 유저 플로우

1. 화면을 다시 열면 `GET /api/v1/agent/session`으로 최근 대화를 가져옵니다. `preview`는 마지막 메시지입니다.
2. 대화를 누르면 `GET /api/v1/agent/session/{session_id}`의 `messages`를 시간순으로 그립니다. `proposed_actions` 중 `pending`만 확정 버튼에 연결합니다.
3. 새 대화는 `POST /api/v1/agent/session`에 `workspace_id`를 보냅니다. 한 영역만 다루면 `database_slug`를 넣습니다. 비우면 전체입니다.
4. `POST /api/v1/agent/session/{session_id}/message`에 사용자 문장을 보냅니다.
5. 응답 `proposed_actions`가 비어 있으면 안내 문장만 보여 줍니다.
6. 초안이 있으면 내용을 보여주고, 확인 후 `POST /api/v1/agent/session/{session_id}/confirm`에 `action_ids`를 보냅니다.
7. 확정 응답의 `records`로 만들어진 행을 엽니다.

## API

- `GET /session` 내 최근 대화 50개. `workspace_id` 쿼리면 그 공간만. 항목은 `preview`, `updated_at`
- `GET /session/{session_id}` 메시지와 초안 전체. 메시지는 오래된 순
- `POST /session` 대화 시작. 201
- `POST /session/{session_id}/message` 메시지. 조회는 바로 실행되고 생성·수정은 `pending` 초안입니다.
- `POST /session/{session_id}/confirm` 초안 확정

메시지 본문:

```json
{"content": "오늘 출근 등록해줘"}
```

확정 본문:

```json
{"action_ids": [1]}
```

초안 `kind`는 `create_record` 또는 `update_record`입니다. `payload`는 워크스페이스 레코드 생성·수정과 같은 모양이고, 생성은 `database_slug`를 포함합니다. 담당 값은 `GET /api/v1/workspace/{workspace_id}/member`의 `user_id`입니다.

없는 대화는 404, 멤버가 아니면 403, 빈 문장은 400입니다.

## 구현 체크리스트

- 보내기 전에 문장이 비었는지 확인한다.
- 응답 문구는 초안일 수 있다는 안내와 함께 보여 준다.
- 같은 `session_id`로 이어서 보내고, 재진입 때는 상세 조회로 메시지를 복원한다.
- `proposed_actions`가 `pending`일 때만 확정 버튼을 띄운다.
- 확정에 성공하면 해당 영역의 표 조회를 다시 불러온다.

## 비범위

- 브라우저에서 OpenAI를 직접 호출
- 대화 목록과 메시지 조회를 MCP로 여는 것. 앱 대화 기록은 호출자 화면에만 보여 줍니다.
- 삭제, 멤버 변경, 스키마 변경
- 워크봇 저장. 워크봇은 [workbot_frontend.md](workbot_frontend.md)입니다.

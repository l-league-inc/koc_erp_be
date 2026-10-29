---
title: 업무 대화 API
audience: frontend
---

# 업무 대화 API

홈 입력창과 출근, 일정, 견적, 출장, A/S 단축은 같은 API를 씁니다. 단축은 프롬프트 문장만 다릅니다. 인증은 기존 JWT입니다.

모델 호출은 서버가 합니다. 생성과 수정은 초안으로 돌아오고, 사용자가 확정한 뒤에만 워크스페이스에 저장됩니다.

## 유저 플로우

1. `POST /api/v1/agent/session`에 `workspace_id`를 보냅니다. 한 영역만 다루면 `database_slug`를 넣습니다. 비우면 전체입니다.
2. `POST /api/v1/agent/session/{session_id}/message`에 사용자 문장을 보냅니다.
3. 응답 `proposed_actions`가 비어 있으면 안내 문장만 보여 줍니다.
4. 초안이 있으면 내용을 보여주고, 확인 후 `POST /api/v1/agent/session/{session_id}/confirm`에 `action_ids`를 보냅니다.
5. 확정 응답의 `records`로 만들어진 행을 엽니다.

## API

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
- `proposed_actions`가 있을 때만 확정 버튼을 띄운다.
- 확정에 성공하면 해당 영역의 표 조회를 다시 불러온다.

## 비범위

- 브라우저에서 OpenAI를 직접 호출
- 삭제, 멤버 변경, 스키마 변경
- 워크봇 저장. 워크봇은 [workbot_frontend.md](workbot_frontend.md)입니다.

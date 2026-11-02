---
title: 업무 대화 API
audience: frontend
---

# 업무 대화 API

홈 입력창과 출근, 일정, 견적, 출장, A/S 단축은 같은 API를 씁니다. 단축도 같은 대화로 들어가고, 서버가 고정 스킬을 골라 처리합니다. 인증은 기존 JWT입니다.

모델 호출은 서버가 합니다. 프롬프트에는 스킬 이름과 설명만 들어가고, 맞는 스킬의 절차는 그때 읽습니다. 레코드와 스킬의 생성·수정은 초안으로 돌아오고, 사용자가 확정한 뒤에만 저장됩니다.

고정 스킬이 만드는 레코드 초안의 `database_slug`는 출근 `attendance`, 일정 `tasks`, 견적 `quotes`, 출장 `trip`, A/S `after_service`입니다. 임직원·거래처 칸은 그 레코드 id 배열입니다. 대화 `database_slug`가 한 영역이면 조회는 그 영역의 관계 대상까지 되고, 생성 초안은 그 영역만 됩니다.

## 유저 플로우

1. 화면을 다시 열면 `GET /api/v1/agent/session`으로 최근 대화를 가져옵니다. `preview`는 마지막 메시지입니다.
2. 대화를 누르면 `GET /api/v1/agent/session/{session_id}`의 `messages`를 시간순으로 그립니다. `proposed_actions` 중 `pending`만 확정 버튼에 연결합니다.
3. 새 대화는 `POST /api/v1/agent/session`에 `workspace_id`를 보냅니다. 한 영역만 다루면 `database_slug`를 넣습니다. 비우면 전체입니다.
4. `POST /api/v1/agent/session/{session_id}/message`에 사용자 문장을 보냅니다.
5. 응답 `proposed_actions`가 비어 있으면 안내 문장만 보여 줍니다.
6. 초안이 있으면 내용을 보여주고, 확인 후 `POST /api/v1/agent/session/{session_id}/confirm`에 `action_ids`를 보냅니다.
7. 확정 응답의 `records`로 만들어진 행을 엽니다. 스킬 초안이면 `skills`의 `name`으로 스킬 목록을 다시 불러옵니다.

## API

- `GET /session` 내 최근 대화 50개. `workspace_id` 쿼리면 그 공간만. 항목은 `preview`, `updated_at`
- `GET /session/{session_id}` 메시지와 초안 전체. 메시지는 오래된 순
- `POST /session` 대화 시작. 201
- `POST /session/{session_id}/message` 메시지. 조회는 바로 실행되고 생성·수정은 `pending` 초안입니다.
- `POST /session/{session_id}/confirm` 초안 확정
- `GET /skill?workspace_id=` 고정 스킬과 그 공간의 스킬. 고정 스킬은 `source`가 `bundled`이고 `id`가 `null`
- `POST /skill` 스킬 생성. 201
- `PATCH /skill/{skill_id}` `description`, `body`, `enabled`
- `DELETE /skill/{skill_id}` 소프트 삭제. 204

메시지 본문:

```json
{"content": "오늘 출근 등록해줘"}
```

확정 본문:

```json
{"action_ids": [1]}
```

초안 `kind`는 `create_record`, `update_record`, `create_skill`, `update_skill`입니다. 레코드 `payload`는 워크스페이스 레코드 생성·수정과 같은 쓰기 모양이고, 생성은 `database_slug`를 포함합니다. 관계 값은 레코드 id 배열입니다. 서버가 조회 도구로 읽는 관계 값은 `{id, title, database_id, database_slug}`이지만, 이 조회 결과는 화면 초안에 실리지 않습니다. 확정 뒤 레코드를 다시 조회하면 읽기 모양이 나옵니다. 페이지 데이터베이스의 임직원·거래처 칸도 레코드 id 배열입니다. `seed_koc_workspace` 여섯 영역의 `owner`만 `GET /api/v1/workspace/{workspace_id}/member`의 `user_id` 배열입니다.

스킬 생성 `payload`는 `name`, `description`, `body`, `enabled`입니다. 수정 `payload`는 `name`과 바뀐 `description`, `body`, `enabled`입니다. `name`은 영문 소문자로 시작하고 숫자와 `_`만 씁니다. 고정 스킬 이름 `attendance`, `schedule`, `quote`, `travel`, `after_service`는 만들거나 고칠 수 없습니다.

대화 목록 항목은 `id`, `workspace_id`, `database_slug`, `preview`, `created_at`, `updated_at`입니다. 상세는 여기에 `messages`, `proposed_actions`가 있습니다. 메시지는 `id`, `role`(`user`/`assistant`), `content`, `created_at`입니다. 초안은 `id`, `kind`, `status`(`pending`/`confirmed`/`rejected`), `payload`, `result`입니다. 메시지 전송 응답은 `message`, `proposed_actions`입니다. 확정 응답은 `proposed_actions`, `records`, `skills`입니다. `records` 항목은 `action_id`, `record_id`, `title`입니다. `skills` 항목은 `action_id`, `skill_id`, `name`입니다. 레코드 초안만 확정하면 `skills`는 빈 배열입니다.

스킬 목록 항목은 `id`, `workspace_id`, `name`, `description`, `body`, `source`(`bundled`/`user`), `enabled`, `created_at`, `updated_at`입니다. 고정 스킬은 `enabled`가 true이고 시각은 `null`입니다. 생성 본문은 `workspace_id`, `name`, `description`, `body`, `enabled`입니다.

없는 대화나 스킬은 404, 멤버가 아니면 403, 빈 문장·빈 이름·빈 본문은 400입니다.

## 구현 체크리스트

- 보내기 전에 문장이 비었는지 확인한다.
- 응답 문구는 초안일 수 있다는 안내와 함께 보여 준다.
- 같은 `session_id`로 이어서 보내고, 재진입 때는 상세 조회로 메시지를 복원한다.
- `proposed_actions`가 `pending`일 때만 확정 버튼을 띄운다.
- 확정에 성공하면 해당 영역의 표 조회를 다시 불러온다. 스킬 초안이면 스킬 목록을 다시 불러온다.
- 고정 스킬은 목록에만 보여주고 수정·삭제 버튼을 만들지 않는다. `id`가 `null`이다.

## 비범위

- 브라우저에서 OpenAI를 직접 호출
- 대화 목록과 메시지 조회를 MCP로 여는 것. 앱 대화 기록은 호출자 화면에만 보여 줍니다.
- 고정 스킬 수정·삭제
- 대화 안에서 스킬 삭제. 삭제는 `DELETE /skill/{skill_id}`만 가능합니다.
- 레코드 삭제, 멤버 변경, 스키마 변경
- 워크봇 저장. 워크봇은 [workbot_frontend.md](workbot_frontend.md)입니다.

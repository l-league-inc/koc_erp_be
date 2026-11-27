---
title: 업무 대화 API
audience: frontend
---

# 업무 대화 API

홈 입력창과 출근, 휴가, 일정, 견적, 출장, A/S, 메일, 외부 검색 단축은 같은 API를 씁니다. 단축도 같은 대화로 들어가고, 서버가 고정 스킬을 골라 처리합니다. 인증은 기존 JWT입니다.

모델 호출은 서버가 합니다. 사용자는 OpenAI 3개와 Anthropic 3개 중에서 고르고, 그 선택은 업무 대화와 워크봇 초안에 함께 쓰입니다. 프롬프트에는 스킬 이름과 설명만 들어가고, 맞는 스킬의 절차는 그때 읽습니다. 출근(`attendance`) 레코드 생성·수정은 메시지 처리 중에 바로 저장됩니다. `출근`처럼 본인 출근만 말하는 문장은 서버가 로그인 계정으로 바로 저장합니다. `check_in` 속성이 있으면 그 칸에 현재 시각을 넣습니다. 임직원은 사내 이메일이 계정 이메일과 같은 행을 먼저 쓰고, 없으면 계정 이름과 제목이 같은 행을 씁니다. 오늘 출근이 이미 있으면 새로 만들지 않고 그 행을 안내합니다. 응답 `proposed_actions`는 `confirmed`이고 `result.record_id`가 있으며, 도우미 문장은 저장된 사실을 말합니다. 그 외 레코드와 스킬의 생성·수정, 메일 발송과 견적서 파일은 초안으로 돌아오고, 사용자가 확정한 뒤에만 저장·발송·생성됩니다.

고정 스킬이 만드는 레코드 초안의 `database_slug`는 출근 `attendance`, 휴가 `leave`, 일정 `tasks`, 견적 `quotes`, 출장 `trip`, A/S `after_service`입니다. 휴가 신청을 고칠 때 그 초안이 아직 `pending`이면 새 초안을 만들지 않고, 같은 `id`의 `payload`가 바뀐 채 메시지 응답에 다시 옵니다. 화면은 그 id의 초안 내용을 갱신합니다. `confirmed`로 `record_id`가 있는 휴가만 수정 초안(`update_record`)이 새로 생깁니다. 메일 고정 스킬 이름은 `mail`이며 레코드가 아니라 Daum 메일을 읽고 발송 초안을 만듭니다. 견적서 파일 고정 스킬 이름은 `estimate`이며 레코드가 아니라 양식 docx 초안을 만듭니다. 외부 검색 고정 스킬 이름은 `web_search`이며 레코드를 만들지 않고 웹 결과와 출처 URL을 안내합니다. 보고 페이지가 필요하면 생성 초안입니다. 임직원·거래처 칸은 그 레코드 id 배열입니다. 대화 `database_slug`가 한 영역이면 조회는 그 영역의 관계 대상까지 되고, 생성 초안은 그 영역만 됩니다.

## 유저 플로우

1. 화면을 다시 열면 `GET /api/v1/agent/model`로 모델 목록과 `selected`를 그립니다. 바꾸면 `PUT /api/v1/agent/model`에 `model`을 보냅니다.
2. `GET /api/v1/agent/session`으로 최근 대화를 가져옵니다. `preview`는 마지막 메시지입니다.
3. 대화를 누르면 `GET /api/v1/agent/session/{session_id}`의 `messages`를 시간순으로 그립니다. `proposed_actions` 중 `pending`만 확정 버튼에 연결합니다.
4. 새 대화는 `POST /api/v1/agent/session`에 `workspace_id`를 보냅니다. 한 영역만 다루면 `database_slug`를 넣습니다. 비우면 전체입니다. 대화를 지우면 `DELETE /api/v1/agent/session/{session_id}`입니다.
5. `POST /api/v1/agent/session/{session_id}/message`에 사용자 문장을 보냅니다. 이번 문장만 다른 모델을 쓰려면 `model`을 함께 보냅니다. 비우면 저장된 선택을 씁니다.
6. 응답 `proposed_actions`가 비어 있으면 안내 문장만 보여 줍니다.
7. `pending` 초안이 있으면 내용을 보여주고, 확인 후 `POST /api/v1/agent/session/{session_id}/confirm`에 `action_ids`를 보냅니다. 출근 생성·수정은 이미 `confirmed`이므로 확정 API를 다시 호출하지 않습니다.
8. 확정 응답의 `message`를 대화 끝에 붙입니다. 이 문장이 확정 사실이며, 다음 사용자 문장에서 서버가 초안 상태를 모델에 함께 넣습니다. `records`로 만들어진 행을 엽니다. 스킬 초안이면 `skills`의 `name`으로 스킬 목록을 다시 불러옵니다. 메일 발송 초안이면 `mails`로 발송 결과를 보여 줍니다. 견적서 초안이면 `estimates`의 `draft`로 편집 폼을 열고 `docx_base64`를 미리보기로 둡니다. PDF와 메일은 [estimate_frontend.md](estimate_frontend.md)의 API로 이어 갑니다.

## API

- `GET /model` 선택 가능한 모델과 현재 `selected`. 항목은 `id`, `provider`(`openai`/`anthropic`), `name`, `description`
- `PUT /model` `{model}` 저장. 응답은 목록과 같습니다. 없는 id는 400
- `GET /session` 내 최근 대화 50개. `workspace_id` 쿼리면 그 공간만. 항목은 `preview`, `updated_at`
- `GET /session/{session_id}` 메시지와 초안 전체. 메시지는 오래된 순
- `POST /session` 대화 시작. 201
- `DELETE /session/{session_id}` 대화 소프트 삭제. 204. 목록과 상세에서 빠집니다.
- `POST /session/{session_id}/message` 메시지. 조회는 바로 실행됩니다. 출근(`attendance`) 생성·수정은 이 응답에서 저장되고 `confirmed`입니다. 그 외 생성·수정은 `pending` 초안입니다.
- `POST /session/{session_id}/confirm` 초안 확정
- `GET /skill?workspace_id=` 고정 스킬과 그 공간의 스킬. 고정 스킬은 `source`가 `bundled`이고 `id`가 `null`
- `POST /skill` 스킬 생성. 201
- `PATCH /skill/{skill_id}` `description`, `body`, `enabled`
- `DELETE /skill/{skill_id}` 소프트 삭제. 204

메시지 본문:

```json
{"content": "오늘 출근 등록해줘", "model": "claude-sonnet-5-5"}
```

`model`을 비우면 저장된 선택을 씁니다. 값을 넣으면 그 문장에 쓰고 선택도 바꿉니다. 기본값은 `gpt-6-luna`입니다.

| id | provider | 이름 |
|----|----------|------|
| `gpt-6-luna` | openai | GPT-6 Luna |
| `gpt-6.1-terra` | openai | GPT-6.1 Terra |
| `gpt-6.1-sol` | openai | GPT-6.1 Sol |
| `claude-haiku-5-5` | anthropic | Claude Haiku 5.5 |
| `claude-sonnet-5-5` | anthropic | Claude Sonnet 5.5 |
| `claude-opus-5-5` | anthropic | Claude Opus 5.5 |

확정 본문:

```json
{"action_ids": [1]}
```

초안 `kind`는 `create_record`, `update_record`, `create_skill`, `update_skill`, `send_mail`, `create_estimate`입니다. 레코드 `payload`는 워크스페이스 레코드 생성·수정과 같은 쓰기 모양이고, 생성은 `database_slug`를 포함합니다. 재고 `inventory`의 `quantity`를 0 미만으로 확정하면 400 `보유 재고를 초과하는 출고입니다`이고 그 레코드는 그대로입니다. 확정한 품목을 다른 품목으로 정정하면 응답 `proposed_actions`에 새 품목 초안과, 잘못 반영한 품목의 현재고를 확정 전 값으로 되돌리는 초안이 함께 있습니다. 둘 다 확정해야 재고가 옮겨집니다. 선택·상태 값은 옵션 이름 또는 id입니다. 이름 안의 공백·밑줄 차이(`진행중`과 `진행 중`)는 같은 옵션으로 맞춥니다. 스키마에 없는 값은 초안을 만들 때와 확정할 때 그 칸만 빠지고, 나머지 값은 저장됩니다. 상태 값이 옵션과 달라도 확정 전체가 400으로 막히지 않습니다. 관계 값은 레코드 id 배열입니다. 서버가 조회 도구로 읽는 관계 값은 `{id, title, database_id, database_slug}`이지만, 이 조회 결과는 화면 초안에 실리지 않습니다. 확정 뒤 레코드를 다시 조회하면 읽기 모양이 나옵니다. 페이지 데이터베이스의 임직원·거래처 칸도 레코드 id 배열입니다. `seed_koc_workspace` 여섯 영역의 `owner`만 `GET /api/v1/workspace/{workspace_id}/member`의 `user_id` 배열입니다.

스킬 생성 `payload`는 `name`, `description`, `body`, `enabled`입니다. 수정 `payload`는 `name`과 바뀐 `description`, `body`, `enabled`입니다. `name`은 영문 소문자로 시작하고 숫자와 `_`만 씁니다. 고정 스킬 이름 `attendance`, `leave`, `schedule`, `quote`, `estimate`, `travel`, `after_service`, `mail`, `web_search`는 만들거나 고칠 수 없습니다.

견적서 `payload`는 `client`, `department`, `contact`, `issued_on`, `product_name`, `devices`, 선택 `shipping_qty`, `shipping_unit_price`입니다. `devices` 항목은 `serial`, `part_name`, `part_qty`, `part_unit_price`, `labor_level`(`상`/`하`), `labor_hours`, `labor_unit_price`이고 선택 `part_unit`입니다. 금액 키는 없습니다. 확정 전 `result`는 비어 있습니다.

메일 발송 `payload`는 `to`(이메일 배열), `subject`, `body`이고, 선택으로 `cc`, `bcc`입니다. 메일 계정 연결은 `/api/v1/mail`을 씁니다.

외부 검색은 `POST /api/v1/search`입니다. 본문은 `query`가 필수이고, 선택으로 `max_results`(1–8, 기본 5), `time_range`(`day`/`week`/`month`/`year`), `include_domains`(도메인 배열), `topic`(`general`/`news`)입니다. 응답은 `query`와 `results`이고, 항목은 `title`, `url`, `content`, `score`입니다. 워크스페이스에 저장하지 않습니다. 같은 API가 MCP 도구로도 열립니다. 업무 대화에서는 고정 스킬 `web_search`가 `web_search` 도구로 이 검색을 하고, 페이지가 필요하면 생성 초안을 만듭니다.

대화 목록 항목은 `id`, `workspace_id`, `database_slug`, `preview`, `created_at`, `updated_at`입니다. 상세는 여기에 `messages`, `proposed_actions`가 있습니다. 메시지는 `id`, `role`(`user`/`assistant`), `content`, `created_at`입니다. 초안은 `id`, `kind`, `status`(`pending`/`confirmed`/`rejected`), `payload`, `result`입니다. 메시지 전송 응답은 `message`, `proposed_actions`입니다. 확정 응답은 `message`, `proposed_actions`, `records`, `skills`, `mails`, `estimates`입니다. `message`는 확정 사실을 적은 도우미 문장이고, 대화 기록과 목록 `preview`에 남습니다. `records` 항목은 `action_id`, `record_id`, `database_id`, `title`입니다. `database_id`로 해당 데이터베이스의 레코드 목록 캐시만 무효화할 수 있습니다. `skills` 항목은 `action_id`, `skill_id`, `name`입니다. `mails` 항목은 `action_id`, `sender`, `to`, `cc`, `bcc`, `subject`입니다. `estimates` 항목은 `action_id`, `filename`, `content_type`, `supply_amount`, `vat`, `total`, `draft`, `docx_base64`입니다. `draft`는 견적서 편집 폼에 다시 넣는 초안입니다. 해당 종류가 없으면 빈 배열입니다. 확정된 견적서의 같은 값은 초안 `result`에도 남습니다.

스킬 목록 항목은 `id`, `workspace_id`, `name`, `description`, `body`, `source`(`bundled`/`user`), `enabled`, `created_at`, `updated_at`입니다. 고정 스킬은 `enabled`가 true이고 시각은 `null`입니다. 생성 본문은 `workspace_id`, `name`, `description`, `body`, `enabled`입니다.

없는 대화나 스킬은 404, 멤버가 아니면 403, 빈 문장·빈 이름·빈 본문은 400입니다.

## 구현 체크리스트

- 모델 선택은 `GET /model`의 `selected`를 보여주고, 바꾸면 `PUT /model`을 호출한다.
- 보내기 전에 문장이 비었는지 확인한다.
- 출근 생성·수정 응답은 저장된 사실로 보여 준다. 그 외 응답 문구는 초안일 수 있다는 안내와 함께 보여 준다.
- 같은 `session_id`로 이어서 보내고, 재진입 때는 상세 조회로 메시지를 복원한다.
- 대화 삭제는 `DELETE /session/{session_id}`만 호출하고, 204이면 목록에서 뺀다.
- `proposed_actions`가 `pending`일 때만 확정 버튼을 띄운다. 출근 생성·수정은 `confirmed`로 오므로 버튼을 띄우거나 confirm을 다시 호출하지 않는다. 문장은 응답 `message`를 그대로 쓴다.
- 확정에 성공하면 응답 `message`를 대화 끝에 붙이고, 해당 영역의 표 조회를 다시 불러온다. 스킬 초안이면 스킬 목록을 다시 불러온다. 메일 발송 초안이면 `mails` 결과를 보여 준다. 견적서 초안이면 `estimates`의 `draft`와 `docx_base64`로 미리보기 편집을 연다. 확정 전에는 파일이 없다고 보여 준다. PDF 다운로드와 메일 보내기는 견적서 API를 사용자가 누를 때만 호출한다.
- 고정 스킬은 목록에만 보여주고 수정·삭제 버튼을 만들지 않는다. `id`가 `null`이다.

## 비범위

- 브라우저에서 OpenAI를 직접 호출
- 대화 목록과 메시지 조회를 MCP로 여는 것. 앱 대화 기록은 호출자 화면에만 보여 줍니다.
- 고정 스킬 수정·삭제
- 대화 안에서 스킬 삭제. 삭제는 `DELETE /skill/{skill_id}`만 가능합니다.
- 레코드 삭제, 멤버 변경, 스키마 변경
- 워크봇 저장. 워크봇은 [workbot_frontend.md](workbot_frontend.md)입니다.

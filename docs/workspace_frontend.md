---
title: 워크스페이스 API
audience: frontend
---

# 워크스페이스 API

KOC 워크스페이스의 업무 데이터는 `api/v1/workspace`에 있습니다. 화면의 영역은 데이터베이스 slug와 같습니다. 인증은 기존 JWT입니다.

## 유저 플로우

1. 로그인 후 `GET /api/v1/workspace`로 속한 공간을 가져옵니다. 시드 공간의 slug는 `koc`입니다.
2. `GET /api/v1/workspace/database`로 사이드바 영역을 그립니다.
3. 영역을 열면 `GET /api/v1/workspace/database/{database_id}`의 `properties`와 `views`로 표 머리와 탭을 만듭니다.
4. 탭의 `filters`를 `POST /api/v1/workspace/query`에 넣어 행을 가져옵니다. `내 담당` 보기는 `owner = me`라서 서버가 로그인 사용자로 바꿉니다.
5. 행을 누르면 `GET /api/v1/workspace/record/{record_id}`로 값과 블록을 엽니다.
6. 저장은 `POST .../record` 또는 `PATCH /api/v1/workspace/record/{record_id}`입니다. 수정 요청에 없는 키는 유지됩니다. `blocks`를 보내면 본문 전체를 바꿉니다.
7. 통합대장은 데이터베이스를 비운 `POST /api/v1/workspace/query`입니다. 각 행의 `database_slug`로 영역을 구분합니다.

## 영역

| slug | 화면 | 주요 속성 |
|------|------|-----------|
| `hr` | 인사 / 근태관리 | `status`, `kind`(출근/휴가/출장), `due_date`, `owner`, `memo` |
| `daily` | 일일 업무 관리 | `status`, `owner`, `due_date`, `memo` |
| `gov` | 정부과제 및 거래처 | `status`, `kind`(과제/거래처), `owner`, `due_date`, `memo` |
| `purchase` | 구매 / 발주 / 재고 | `quantity`, `safety_stock`, `status`, `owner`, `due_date` |
| `sales` | 영업 / 견적 / A/S | `kind`(견적/A/S), `status`, `owner`, `due_date`, `amount` |
| `docs` | 문서 및 사내규정 | `status`, `category`, `owner`, `due_date`, 블록 본문 |

`title`은 모든 데이터베이스의 제목 속성입니다. 응답 `title`과 `values.title`은 같습니다. 상태 이름은 `진행 중`, `완료`, `대기`, `접수`처럼 옵션 `name`입니다. 담당 `owner`는 사용자 id 배열입니다.

## API

기본 경로는 `/api/v1/workspace`입니다.

- `GET /` 워크스페이스 목록. `role`은 `owner`, `admin`, `member`
- `GET /{workspace_id}/member` 멤버 목록. `user_id`, `name`, `role`
- `GET /database` 데이터베이스 목록
- `GET /database/{database_id}` 스키마. `properties`, `views`
- `POST /query` 레코드 조회
- `POST /database/{database_id}/record` 레코드 생성
- `GET /record/{record_id}` 레코드 상세
- `PATCH /record/{record_id}` 레코드 수정
- `DELETE /record/{record_id}` 소프트 삭제

속성, 보기, 블록도 같은 접두사 아래 목록/생성/수정/삭제가 있습니다. 속성 생성 본문은 `name`, `slug`, `type`, `config`입니다. `select`, `multi_select`, `status`의 `config.options`는 `{id, name, color}` 배열입니다.

## 페이로드

레코드 생성:

```json
{
  "title": "A/S 접수",
  "values": {
    "status": "접수",
    "kind": "A/S",
    "owner": [1],
    "due_date": "2026-04-30",
    "amount": "120000"
  },
  "blocks": [
    {
      "type": "paragraph",
      "content": {"text": "방문 요청"},
      "position": 0,
      "children": []
    }
  ]
}
```

조회:

```json
{
  "database_slug": "sales",
  "view_id": null,
  "q": "",
  "filters": [{"property": "status", "op": "eq", "value": "접수"}],
  "sorts": [{"property": "due_date", "direction": "asc"}],
  "page": 1,
  "page_size": 20
}
```

조회 응답은 `count`, `page`, `page_size`, `data`입니다. `data` 항목은 `id`, `database_id`, `database_slug`, `database_name`, `title`, `values`, `created_by_id`, `last_edited_by_id`, `created_at`, `updated_at`입니다. 상세에만 `blocks`가 있습니다.

날짜 하루는 ISO 문자열, 기간은 `{start, end}`입니다. 숫자는 문자열입니다. 체크박스는 boolean입니다. 파일은 `{name, url}` 배열입니다. relation은 레코드 id 배열입니다.

필터 연산: `eq`, `neq`, `contains`, `in`, `gt`, `gte`, `lt`, `lte`, `is_empty`.

블록 타입: `paragraph`, `heading_1`, `heading_2`, `heading_3`, `bulleted_list`, `numbered_list`, `to_do`, `quote`, `divider`.

없는 데이터는 404, 멤버가 아니면 403, 옵션에 없는 값은 400입니다.

## 구현 체크리스트

- 사이드바 영역을 `GET /database` slug로 연결한다.
- 표 헤더는 `properties`의 `name`, `slug`, `type`, `config.options`를 쓴다.
- 탭은 `views`다. 탭을 누르면 `filters`를 조회 본문에 넣는다.
- 통합대장은 `database_slug` 없이 조회하고 `database_name`으로 분류 칸을 채운다.
- 새 행은 `title`과 `values`를 함께 보낸다.
- 수정 요청에는 바뀐 slug만 넣는다. 본문을 저장할 때만 `blocks`를 넣는다.
- 담당자 선택 목록은 `GET /{workspace_id}/member`의 `user_id`만 보낸다. 화면 이름은 `name`으로 붙인다.

## 비범위

- Notion.com 동기화, 수식, 롤업, 버튼
- MCP로 삭제, 멤버 변경, 스키마 변경. 워크스페이스 레코드 도구는 조회, 생성, 수정만 한다.
- 화면의 자동화 워크봇. 계약은 [workbot_frontend.md](workbot_frontend.md)입니다.
- 앱 안 업무 대화. 계약은 [agent_frontend.md](agent_frontend.md)입니다.

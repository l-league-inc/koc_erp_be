---
title: 워크스페이스 API
audience: frontend
---

# 워크스페이스 API

KOC 워크스페이스의 업무 데이터는 `api/v1/workspace`에 있습니다. 화면의 영역은 데이터베이스 slug와 같습니다. 인증은 기존 JWT입니다. 페이지 아이콘, 서식 블록, 댓글, 활동, 보드·캘린더·갤러리, 템플릿, 휴지통은 [workspace_page_frontend.md](workspace_page_frontend.md)입니다.

## 유저 플로우

1. 로그인 후 `GET /api/v1/workspace`로 속한 공간을 가져옵니다. 시드 공간의 slug는 `koc`입니다.
2. `GET /api/v1/workspace/database`로 사이드바 영역을 그립니다. `position` 오름차순입니다.
3. 영역을 열면 `GET /api/v1/workspace/database/{database_id}`의 `properties`와 `views`로 표 머리와 탭을 만듭니다.
4. 탭의 `filters`와 `sorts`를 `POST /api/v1/workspace/query`에 넣거나, `view_id`만 넣습니다. `내 담당` 보기는 `owner = me`라서 서버가 로그인 사용자로 바꿉니다.
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

## 공통

없는 id는 404, 멤버가 아니면 403, 값이 스키마와 다르면 400입니다. 삭제는 소프트 삭제이고 응답은 204입니다. 워크스페이스 수정은 `owner`와 `admin`, 삭제는 `owner`만 가능합니다. 데이터베이스, 속성, 레코드, 블록, 보기는 멤버라면 읽고 쓸 수 있습니다. 제목 속성은 지우거나 타입을 바꿀 수 없습니다. 값이 있는 속성은 타입을 바꿀 수 없습니다.

슬러그는 영문 소문자로 시작하고 숫자와 `_`만 씁니다.

## 워크스페이스

`GET /` 목록. 항목은 `id`, `name`, `slug`, `role`(`owner`/`admin`/`member`), `created_at`, `updated_at`.

`POST /` 생성. 201. 호출자가 소유자가 됩니다.

```json
{"name": "KOC", "slug": "koc"}
```

`GET /{workspace_id}` 상세. 목록 항목과 같은 필드입니다.

`PATCH /{workspace_id}` 이름 또는 슬러그. 보낸 키만 바꿉니다.

`DELETE /{workspace_id}` 소유자만.

`GET /{workspace_id}/member` 멤버. `user_id`, `name`, `role`. 담당자 선택 목록은 이 `user_id`만 보냅니다.

## 데이터베이스

`GET /database` 목록. `id`, `workspace_id`, `name`, `slug`, `description`, `icon`, `position`, `created_at`, `updated_at`.

`POST /database` 생성. 201. 제목 속성을 함께 만듭니다. 상세 응답에 `properties`, `views`가 있습니다.

```json
{
  "workspace_id": 1,
  "name": "영업",
  "slug": "sales",
  "description": "",
  "icon": "briefcase",
  "position": 0
}
```

`GET /database/{database_id}` 스키마. 목록 필드에 `properties`, `views`가 더 있습니다.

`PATCH /database/{database_id}` `name`, `slug`, `description`, `icon`, `position`.

`DELETE /database/{database_id}` 데이터베이스와 속한 레코드를 지웁니다. 이 삭제는 휴지통 목록에 나오지 않습니다.

## 속성

`GET /database/{database_id}/property` 목록.

`POST /database/{database_id}/property` 생성. 201.

```json
{
  "name": "상태",
  "slug": "status",
  "type": "status",
  "position": 1,
  "config": {
    "options": [{"id": "waiting", "name": "대기", "color": "gray"}]
  }
}
```

속성 응답은 `id`, `database_id`, `name`, `slug`, `type`, `config`, `position`, `created_at`, `updated_at`입니다.

`PATCH /property/{property_id}` `name`, `slug`, `type`, `config`, `position`.

`DELETE /property/{property_id}` 제목 속성은 400입니다.

타입은 `title`, `text`, `number`, `select`, `multi_select`, `status`, `date`, `checkbox`, `url`, `email`, `phone`, `people`, `files`, `relation`입니다. `select`, `multi_select`, `status`는 `config.options`가 필수이고 항목은 `{id, name, color}`입니다. `relation`의 `config`는 `{database_id}`이고 같은 워크스페이스의 데이터베이스 id입니다.

## 값 모양

쓰기는 `values`의 키가 속성 slug입니다.

| 타입 | 쓰기 | 읽기 |
|------|------|------|
| `title`, `text`, `url`, `email`, `phone` | 문자열 | 문자열 |
| `select`, `status` | 옵션 `id` 또는 `name` | 옵션 `name` |
| `number` | 숫자 또는 숫자 문자열 | 문자열 |
| `date` | `YYYY-MM-DD` 또는 `{start, end}` | 하루는 ISO 문자열, 기간은 `{start, end}` |
| `checkbox` | boolean | boolean |
| `multi_select` | 옵션 이름 또는 id 배열 | 옵션 `name` 배열 |
| `people` | 사용자 id 배열 | 사용자 id 배열 |
| `files` | `{name, url}` 배열 | 같은 모양 |
| `relation` | 레코드 id 배열 | `{id, title, database_id, database_slug}` 배열 |

관계로 지운 레코드는 읽기 목록에서 빠집니다. 사람 이름은 `GET /{workspace_id}/member`로 붙입니다. URL은 `http://` 또는 `https://`로 시작해야 합니다. 빈 값(`null`, `""`, `[]`)을 보내면 그 속성을 지웁니다. 제목은 비울 수 없습니다.

## 보기

`GET /database/{database_id}/view` 목록.

`POST /database/{database_id}/view` 생성. 201.

```json
{
  "name": "진행중",
  "type": "table",
  "filters": [{"property": "status", "op": "eq", "value": "진행 중"}],
  "sorts": [{"property": "due_date", "direction": "asc"}],
  "config": {},
  "position": 1
}
```

응답은 `id`, `database_id`, `name`, `type`, `filters`, `sorts`, `config`, `position`, `created_at`, `updated_at`입니다. `type`은 `table`, `board`, `list`, `calendar`, `gallery`입니다. 보드·캘린더·갤러리의 `config`는 [workspace_page_frontend.md](workspace_page_frontend.md)에 있습니다.

`PATCH /view/{view_id}` 보낸 키만 바꿉니다. `DELETE /view/{view_id}`.

시드 보기는 모두 `table`입니다. 이름은 `전체`, `진행중`, `내 담당`, `완료`입니다.

## 조회

`POST /query`

```json
{
  "database_slug": "sales",
  "database_id": null,
  "view_id": null,
  "q": "",
  "filters": [{"property": "status", "op": "eq", "value": "접수"}],
  "sorts": [{"property": "due_date", "direction": "asc"}],
  "page": 1,
  "page_size": 20
}
```

`database_slug`, `database_id`, `view_id`를 비우면 멤버인 모든 영역의 행입니다. `view_id`가 있으면 그 데이터베이스로 좁히고, 보기 필터를 요청 필터보다 먼저 적용합니다. 둘 다 AND입니다. 요청 `sorts`가 있으면 보기 정렬 대신 그 정렬을 씁니다. `q`는 제목만 찾습니다. `page_size` 상한은 100입니다.

연산은 `eq`, `neq`, `contains`, `in`, `gt`, `gte`, `lt`, `lte`, `is_empty`입니다. 사람 속성의 `"me"`는 호출자 id로 바뀝니다. `in`의 값은 배열입니다. `is_empty`는 `value`가 없어도 됩니다.

응답은 `count`, `page`, `page_size`, `data`입니다. `data` 항목은 `id`, `database_id`, `database_slug`, `database_name`, `title`, `icon`, `values`, `created_by_id`, `last_edited_by_id`, `created_at`, `updated_at`입니다. 목록에는 `blocks`가 없습니다.

## 레코드와 블록

`POST /database/{database_id}/record` 생성. 201.

```json
{
  "title": "A/S 접수",
  "icon": "",
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

`GET /record/{record_id}` 상세. 목록 필드에 `blocks`가 있습니다.

`PATCH /record/{record_id}` `title`, `icon`, `values`, `blocks`. 없는 키는 유지됩니다. `values` 안의 없는 slug도 유지됩니다.

`DELETE /record/{record_id}` 휴지통으로 옮깁니다. 값과 블록은 남겨 둡니다. 복원은 페이지 문서의 `POST /record/{record_id}/restore`입니다.

블록 조회는 평탄 목록입니다. `parent_id`로 트리를 만듭니다. 생성 본문의 `children`은 저장 후 각 블록의 `parent_id`가 됩니다.

`GET /record/{record_id}/block`

`POST /record/{record_id}/block`

```json
{"type": "paragraph", "content": {"text": "추가 문단"}, "position": 1, "parent_id": null}
```

`PATCH /block/{block_id}` `type`, `content`, `position`, `parent_id`.

`DELETE /block/{block_id}` 그 블록과 하위 블록만 지웁니다. 휴지통에 들어가지 않습니다.

블록 응답은 `id`, `record_id`, `parent_id`, `type`, `content`, `position`, `created_at`, `updated_at`입니다.

기본 블록 타입은 `paragraph`, `heading_1`, `heading_2`, `heading_3`, `bulleted_list`, `numbered_list`, `to_do`, `quote`, `divider`입니다. `content.text` 문자열을 그대로 쓸 수 있습니다. 서식과 `toggle`, `callout`, `code`, `image`는 페이지 문서에 있습니다.

## 구현 체크리스트

- 사이드바 영역을 `GET /database` slug로 연결한다.
- 표 헤더는 `properties`의 `name`, `slug`, `type`, `config.options`를 쓴다.
- 탭은 `views`다. 탭을 누르면 `view_id` 또는 그 `filters`를 조회 본문에 넣는다.
- 통합대장은 `database_slug` 없이 조회하고 `database_name`으로 분류 칸을 채운다.
- 새 행은 `title`과 `values`를 함께 보낸다.
- 수정 요청에는 바뀐 slug만 넣는다. 본문을 저장할 때만 `blocks`를 넣는다.
- 담당자 선택 목록은 `GET /{workspace_id}/member`의 `user_id`만 보낸다. 화면 이름은 `name`으로 붙인다.
- 관계 칸은 읽을 때 객체의 `title`을 보여주고, 저장할 때는 id 배열만 보낸다.
- 행 삭제는 휴지통으로 보내고, 블록만 지운 경우는 바로 없앤다.

## 비범위

- Notion.com 동기화, 수식, 롤업, 버튼
- MCP로 삭제, 멤버 변경, 스키마 변경, 댓글, 템플릿, 휴지통. 워크스페이스 레코드 도구는 조회, 생성, 수정만 한다.
- 화면의 자동화 워크봇. 계약은 [workbot_frontend.md](workbot_frontend.md)입니다.
- 앱 안 업무 대화. 계약은 [agent_frontend.md](agent_frontend.md)입니다.

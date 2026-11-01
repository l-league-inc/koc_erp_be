---
title: 워크스페이스 페이지
audience: frontend
---

# 워크스페이스 페이지

레코드 한 건을 노션 페이지처럼 열 때 쓰는 계약입니다. 데이터베이스와 조회 기본은 [workspace_frontend.md](workspace_frontend.md)입니다. 기본 경로는 `/api/v1/workspace`이고 인증은 JWT입니다.

## 유저 플로우

1. 행을 열면 `GET /record/{record_id}`의 `icon`, `title`, `values`, `blocks`로 페이지를 그립니다.
2. 본문은 `parent_id`가 비어 있는 블록을 위에 두고, 자식은 `parent_id`로 넣습니다.
3. 댓글은 `GET /record/{record_id}/comment`, 수정 이력은 `GET /record/{record_id}/activity`입니다.
4. 보드·캘린더·갤러리 탭은 보기 `type`과 `config`로 같은 `POST /query` 결과를 나눕니다.
5. 새 행에 템플릿을 쓰면 `template_id`만 보내도 제목·값·블록이 채워집니다.
6. 행 삭제 뒤 `GET /{workspace_id}/trash`에서 고르고 `POST /record/{record_id}/restore`로 되돌립니다.

## 페이지 아이콘

레코드 `icon`은 짧은 문자열입니다. 비어 있으면 아이콘이 없습니다. 생성과 수정 본문에 넣고, 목록·상세 응답에 항상 있습니다. 커버 이미지는 없습니다. 갤러리 카드 그림은 아래 `cover_property`를 씁니다.

## 서식 있는 본문

기존 `content.text` 문자열은 그대로 동작합니다. 굵게, 링크, 멘션이 있으면 `rich_text` 배열을 씁니다. 둘 다 있으면 `rich_text`를 그립니다.

```json
{
  "type": "paragraph",
  "content": {
    "rich_text": [
      {
        "text": "방문",
        "annotations": {
          "bold": true,
          "italic": false,
          "strikethrough": false,
          "code": false,
          "color": "default"
        },
        "href": "https://example.com"
      },
      {
        "text": "김담당",
        "mention": {"type": "user", "user_id": 1}
      },
      {
        "text": "A사",
        "mention": {"type": "record", "record_id": 12}
      }
    ]
  },
  "children": []
}
```

`annotations`에 없는 키는 400입니다. 허용 키는 `bold`, `italic`, `strikethrough`, `code`, `color`입니다. 앞의 네 개는 boolean이고 `color`는 문자열입니다. `href`는 `http://` 또는 `https://`이거나 `null`입니다. 멘션 `user`는 같은 워크스페이스 멤버, `record`는 같은 워크스페이스의 살아있는 레코드여야 합니다.

추가 블록:

| type | content |
|------|---------|
| `toggle` | `text` 또는 `rich_text`. 펼침 내용은 `children` |
| `callout` | `icon` 문자열, `text` 또는 `rich_text` |
| `code` | `text` 필수, `language` 문자열 |
| `image` | `url` 필수. 캡션은 `text` 또는 `rich_text` |
| `to_do` | `checked` boolean. 본문은 `text` 또는 `rich_text` |
| `divider` | `{}` |

이미지와 파일 바이트는 워크스페이스에 올리지 않습니다. `POST /api/v1/aws/upload`에 `{file_name}`을 보내 받은 `uploadURL`로 PUT한 뒤, 응답 `imageURL`을 블록 `url`이나 파일 속성의 `url`에 넣습니다.

## 활동

`GET /record/{record_id}/activity`는 최근 50건을 최신 순으로 줍니다.

```json
{
  "id": 1,
  "action": "updated",
  "source": "user",
  "actor_id": 1,
  "actor_name": "박승원",
  "changes": {
    "title": {"before": "초안", "after": "A/S 접수"}
  },
  "created_at": "2026-04-01T09:00:00"
}
```

`action`은 `created` 또는 `updated`입니다. `source`는 `user`, `mcp`, `agent`입니다. 생성은 `changes.after`에 스냅샷이 있습니다. 수정은 바뀐 `title`, `values`, `blocks`(개수)만 있습니다. 댓글은 이 목록에 섞이지 않습니다. 화면에서 시간을 합쳐 보여 줄 때는 댓글 `created_at`과 맞춥니다.

## 댓글

`GET /record/{record_id}/comment` 오래된 순.

`POST /record/{record_id}/comment`

```json
{"body": "확인 부탁합니다", "parent_id": null}
```

응답은 `id`, `record_id`, `parent_id`, `author_id`, `author_name`, `body`, `created_at`, `updated_at`입니다. `parent_id`가 있으면 그 댓글의 답글입니다. 답글에 다시 답글을 달면 400입니다. 본문은 일반 텍스트입니다.

`DELETE /comment/{comment_id}`는 작성자, 워크스페이스 소유자, 관리자만 204입니다. 그 댓글의 답글도 함께 지웁니다. 다른 멤버가 지우면 403입니다.

## 보기

조회 응답은 행 목록 그대로입니다. 칸 묶음은 프론트가 합니다. `page_size`는 최대 100입니다. 월을 옮길 때는 날짜 필터 `gte`, `lt`를 조회 본문에 더합니다.

`board`는 `config.group_by`가 필수입니다. 대상 속성은 `select`, `status`, `multi_select`입니다. 없으면 400입니다.

```json
{"name": "상태 보드", "type": "board", "config": {"group_by": "status"}}
```

열은 그 속성의 `config.options` 순서대로 만들고, 각 행의 `values[group_by]`로 넣습니다. `multi_select`는 값이 배열이므로 첫 칸에만 넣거나 옵션마다 카드를 복제하면 됩니다. 서버는 복제하지 않습니다.

`calendar`는 `config.date_property`가 필수이고 대상은 `date`입니다.

```json
{"name": "일정", "type": "calendar", "config": {"date_property": "due_date"}}
```

하루 값은 ISO 문자열, 기간은 `{start, end}`입니다. 날짜가 비어 있는 행은 달 밖에 둡니다.

`gallery`의 `config.cover_property`는 선택입니다. 대상은 `files` 또는 `url`입니다. 파일 속성이면 첫 항목의 `url`을 카드 그림으로 씁니다. 없으면 제목만 보여 줍니다.

`table`과 `list`는 `config`가 `{}`여도 됩니다.

## 템플릿

`GET /database/{database_id}/template` `position` 순.

`POST /database/{database_id}/template` 201.

```json
{
  "name": "A/S 템플릿",
  "title": "A/S 접수",
  "values": {"status": "접수", "kind": "A/S"},
  "blocks": [{"type": "paragraph", "content": {"text": "방문 요청"}, "children": []}],
  "position": 0
}
```

응답은 `id`, `database_id`, `name`, `title`, `values`, `blocks`, `position`, `created_at`, `updated_at`입니다. `values`의 키는 그 데이터베이스 속성 slug여야 합니다.

`PATCH /template/{template_id}` 보낸 키만 바꿉니다. `DELETE /template/{template_id}`.

레코드 생성에 `template_id`를 주면 템플릿 제목·값·블록을 복사합니다. 요청에 `title`, `values`, `blocks`가 있으면 그 값이 덮어씁니다. `values`는 slug 단위로 덮고, 요청에 없는 slug는 템플릿 값이 남습니다. `blocks`를 보내면 본문 전체를 요청 쪽으로 바꿉니다. 제목을 비우고 템플릿 제목도 없으면 400입니다.

```json
{"template_id": 3}
```

## 휴지통

`DELETE /record/{record_id}`는 `deleted_at`만 찍습니다. 속성 값, 블록, 관계는 남아 있습니다. 지운 행은 조회와 상세에서 빠집니다.

`GET /{workspace_id}/trash` 최근 100건. 항목은 `id`, `title`, `icon`, `database_id`, `database_slug`, `database_name`, `deleted_at`입니다.

`POST /record/{record_id}/restore` 상세 레코드를 돌려줍니다. 블록 본문도 함께 있습니다. 휴지통에 없으면 404입니다.

블록만 지운 경우, 데이터베이스를 지운 경우는 이 목록에 없습니다. 이 동작으로 바꾸기 전에 지운 행은 값과 블록까지 지워져 있어 복원해도 본문이 비어 있을 수 있습니다.

## 구현 체크리스트

- 페이지 헤더에 `icon`과 `title`을 둔다.
- `rich_text`가 있으면 그 배열을 그리고, 없으면 `text`를 그린다.
- 토글 자식은 `parent_id`로 찾는다.
- 이미지 저장 전에 `POST /api/v1/aws/upload`의 `imageURL`을 받는다.
- 댓글 답글 버튼은 `parent_id`가 비어 있는 댓글에만 둔다.
- 활동과 댓글은 `created_at`으로 한 줄에 섞되, API는 따로 호출한다.
- 보드 열은 `config.group_by` 속성의 옵션으로 만들고 행은 `values`로 분류한다.
- 캘린더 칸은 `config.date_property`로 넣고, 월이 바뀌면 날짜 필터를 다시 조회한다.
- 템플릿으로 만들 때는 `template_id`만 보내고, 사용자가 고친 칸만 추가로 보낸다.
- 행 삭제 후 휴지통에서 복원하면 상세를 다시 연다.

## 비범위

- 수식, 롤업, 버튼, Notion.com 동기화, 실시간 커서
- 데이터베이스마다 다른 권한. 멤버는 페이지를 읽고 쓸 수 있다.
- 댓글 서식과 멘션. 댓글 본문은 일반 텍스트다.
- 블록 단위 휴지통
- 서버가 보드 열마다 페이지를 나눠 주는 것
- MCP로 댓글, 템플릿, 휴지통, 복원을 여는 것

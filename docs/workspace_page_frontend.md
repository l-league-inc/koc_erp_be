---
title: 워크스페이스 페이지
audience: frontend
---

# 워크스페이스 페이지

레코드 한 건을 노션 페이지처럼 열 때 쓰는 계약입니다. 사이드바 페이지 묶음과 데이터베이스 속성은 [koc_pages_frontend.md](koc_pages_frontend.md)이고, 조회 기본은 [workspace_frontend.md](workspace_frontend.md)입니다. 기본 경로는 `/api/v1/workspace`이고 인증은 JWT입니다.

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

`annotations`에 없는 키는 400입니다. 허용 키는 `bold`, `italic`, `strikethrough`, `underline`, `code`, `color`입니다. `color`를 뺀 값은 boolean이고 `color`는 문자열입니다. `href`는 `http://` 또는 `https://`이거나 `null`입니다. 멘션 `user`는 같은 워크스페이스 멤버, `record`는 같은 워크스페이스의 살아있는 레코드, `page`는 같은 워크스페이스의 살아있는 페이지여야 합니다.

사용자 멘션이 그 본문에 새로 들어가면 멘션된 사람에게 알림이 갑니다. 저장한 사람 자신, 이미 있던 사용자, `record` 멘션, `page` 멘션은 알림을 만들지 않습니다. 알림 `metadata`는 아래와 같고 메시지는 200자 이내입니다. 화면은 `target`과 `target_id`로 레코드 또는 문서 페이지를 열고 `block_id`로 그 블록까지 이동합니다.

```json
{
  "kind": "mention",
  "workspace_id": 1,
  "target": "record",
  "target_id": 12,
  "block_id": 9
}
```

`target`은 `record` 또는 `page`입니다.

인라인 수식은 AppFlowy의 `formula`와 같습니다. `text` 없이 `formula`만 있는 항목도 됩니다. 둘 다 없으면 400입니다.

```json
{"text": "회의록", "mention": {"type": "page", "page_id": 4}}
{"formula": "E=mc^2"}
```

추가 블록:

| type | content |
|------|---------|
| `toggle` | `text` 또는 `rich_text`. 펼침 내용은 `children` |
| `callout` | `icon` 문자열, `text` 또는 `rich_text` |
| `code` | `text` 필수, `language` 문자열 |
| `image` | `url` 또는 `object_key` 중 하나. 캡션은 `text` 또는 `rich_text` |
| `to_do` | `checked` boolean. 본문은 `text` 또는 `rich_text` |
| `divider` | `{}` |
| `simple_table` | 아래 표 설정. 자식은 `simple_table_row`만 |
| `simple_table_row` | `{}`. 부모는 `simple_table`. 자식은 `simple_table_cell`만 |
| `simple_table_cell` | `{}`. 부모는 `simple_table_row`. 칸 안의 문단은 자식 블록 |
| `simple_columns` | `{}`. 자식은 `simple_column`만 |
| `simple_column` | `ratio`는 0보다 큰 숫자. 부모는 `simple_columns`. 그 안의 블록은 자식 |
| `math_equation` | `formula` 문자열. 비어 있어도 됩니다 |
| `link_preview` | `url` 필수. `title`, `description`, `image`는 문자열 |

표와 다단의 부모 규칙에 맞지 않으면 400입니다. 표 설정은 AppFlowy `SimpleTableData`와 같습니다.

```json
{
  "type": "simple_table",
  "content": {
    "column_widths": {"0": 160, "1": 160},
    "enable_header_row": true,
    "enable_header_column": false,
    "column_aligns": {"0": "Left"},
    "row_aligns": {"0": "Center"},
    "column_colors": {"0": "gray"},
    "row_colors": {"0": "yellow"}
  }
}
```

`column_aligns`와 `row_aligns`의 값은 `Left`, `Center`, `Right`입니다. 열 너비는 0보다 큰 숫자입니다.

북마크는 AppFlowy `link_preview`입니다. 서버는 URL의 제목을 긁지 않습니다. 미리보기를 보여 주려면 클라이언트가 `title`, `description`, `image`를 넣어 저장합니다.

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

## 본문 파일

이미 저장된 `https://` 이미지 주소는 그대로 읽습니다. 새로 올리는 파일은 공개 주소 대신 `object_key`를 씁니다.

1. `POST /{workspace_id}/block-file`에 `{file_name}`을 보냅니다. 응답은 `upload_url`, `object_key`, `expires_in`입니다. `expires_in`은 300초입니다.
2. `upload_url`로 파일을 올립니다.
3. 이미지 블록 `content`에 그 `object_key`를 넣습니다. 다른 워크스페이스 경로는 400입니다. 표시 이름이 필요하면 `file_name`을 같이 넣습니다.
4. 본문을 읽을 수 있는 멤버는 `POST /block/{block_id}/file`로 `download_url`과 `expires_in`을 받습니다. 주소도 300초입니다.

```json
{"type": "image", "content": {"object_key": "koc/block-files/dev/1/abc/사진.png", "file_name": "사진.png"}}
```

## 본문 개정

블록, 레코드 제목, 아이콘, 값을 바꾸기 직전 본문을 최근 50건 남깁니다. 내용이 같으면 개정은 없습니다. 목록에는 본문이 없고, 한 건 조회에만 `body`가 있습니다.

- `GET /record/{record_id}/revision`, `GET /page/{page_id}/revision`: `id`, `actor_id`, `actor_name`, `created_at`
- `GET .../revision/{revision_id}`: 위에 `body`를 더합니다. 레코드 `body`는 `title`, `icon`, `values`, `blocks`입니다. 문서 페이지 `body`는 `blocks`입니다.
- `POST .../revision/{revision_id}/restore`: 그 스냅샷으로 되돌립니다. 되돌리기 직전 본문도 개정으로 남으므로 다시 되돌릴 수 있습니다. 레코드 응답은 상세 레코드이고, 문서 응답은 페이지 상세입니다. 열린 문서방은 `reload`를 받습니다.

문서 페이지가 아니면 개정 API는 400입니다.

## 읽기와 쓰기

데이터베이스와 문서 페이지에 `access`가 있습니다. 값은 `member`(기본) 또는 `admin`입니다. 응답에 항상 있습니다.

`member`이면 지금과 같이 멤버가 본문을 수정합니다. `admin`이면 `owner`와 `admin`만 레코드와 블록을 저장합니다. 멤버의 저장과 문서방 `op`는 403이고, 조회·댓글·멘션은 됩니다. 속성, 보기 수정은 이 값과 관계없이 멤버가 할 수 있습니다.

`access`를 바꾸는 것은 `owner`와 `admin`만 가능합니다. 데이터베이스는 `PATCH /database/{database_id}`에 `access`를 넣고, 그 데이터베이스의 행과 블록이 이 값을 따릅니다. 문서 페이지는 `PATCH /page/{page_id}`에 `access`를 넣고, 그 페이지 블록이 이 값을 따릅니다. 문서가 아닌 페이지에 `access`를 보내면 400입니다.

## 휴지통

`DELETE /record/{record_id}`는 `deleted_at`만 찍습니다. 속성 값, 블록, 관계는 남아 있습니다. 지운 행은 조회와 상세에서 빠집니다.

`GET /{workspace_id}/trash` 최근 100건. 항목은 `id`, `title`, `icon`, `database_id`, `database_slug`, `database_name`, `deleted_at`입니다.

`POST /record/{record_id}/restore` 상세 레코드를 돌려줍니다. 블록 본문도 함께 있습니다. 휴지통에 없으면 404입니다.

블록만 지운 경우, 데이터베이스를 지운 경우는 이 목록에 없습니다. 이 동작으로 바꾸기 전에 지운 행은 값과 블록까지 지워져 있어 복원해도 본문이 비어 있을 수 있습니다.

## 구현 체크리스트

- 페이지 헤더에 `icon`과 `title`을 둔다.
- `rich_text`가 있으면 그 배열을 그리고, 없으면 `text`를 그린다.
- 토글 자식은 `parent_id`로 찾는다.
- 새 이미지는 `POST /{workspace_id}/block-file`의 `object_key`를 블록에 넣고, 볼 때는 `POST /block/{block_id}/file`로 주소를 받는다. 이미 있는 `https` 주소는 그대로 그린다.
- 댓글 답글 버튼은 `parent_id`가 비어 있는 댓글에만 둔다.
- 활동과 댓글은 `created_at`으로 한 줄에 섞되, API는 따로 호출한다.
- 보드 열은 `config.group_by` 속성의 옵션으로 만들고 행은 `values`로 분류한다.
- 캘린더 칸은 `config.date_property`로 넣고, 월이 바뀌면 날짜 필터를 다시 조회한다.
- 템플릿으로 만들 때는 `template_id`만 보내고, 사용자가 고친 칸만 추가로 보낸다.
- 행 삭제 후 휴지통에서 복원하면 상세를 다시 연다.
- 사용자 멘션 알림의 `metadata.target`으로 레코드 또는 문서 페이지를 열고 `block_id`로 스크롤한다.
- 개정 목록은 본문 없이 그리고, 미리보기와 복원은 `revision_id`로 호출한다. 복원 뒤 `reload`면 상세를 다시 조회한다.
- `access`가 `admin`이면 멤버에게 본문 편집을 숨긴다. 조회와 댓글은 남긴다.
- 사이드바 트리는 `parent_id`로 만들고, 데이터베이스 페이지를 폴더로 옮기면 `section_slug`도 그 폴더를 따른다.
- `workspace_changed`를 받으면 본문 없이 해당 `entity`를 다시 조회한다.
- 편집 중인 문서는 [workspace_collab_frontend.md](workspace_collab_frontend.md)의 `sync`와 `collab`로 블록을 맞춘다.
- 숨긴 열은 `config.hidden_properties`를 따른다. 제목은 숨기지 않는다.

## 페이지 트리

`GET /{workspace_id}/page`는 평탄 목록입니다. `parent_id`로 트리를 만듭니다. `kind`는 `folder`, `document`, `database`, `linked_view`입니다.

`POST /{workspace_id}/page`로 폴더, 문서, 연결 보기를 만듭니다. 폴더는 `slug`가 필요합니다. 연결 보기는 `database_id`와 선택 `view_id`만 가리키고 행을 복사하지 않습니다. 데이터베이스 페이지는 `POST /database`가 만듭니다.

`POST /page/{page_id}/move`는 `{parent_id, position}`입니다. `parent_id`가 비면 루트입니다. 자기 자손 아래는 400입니다. 데이터베이스 페이지의 직계 부모가 폴더이면 `Database.section`과 `section_slug`가 그 폴더를 따릅니다.

문서 블록은 `GET|POST /page/{page_id}/block`이고 모양은 레코드 블록과 같습니다. `POST /page/{page_id}/duplicate`는 같은 부모 아래에 블록을 복사합니다.

`POST /page/{page_id}/favorite`, `DELETE /page/{page_id}/favorite`, `GET /{workspace_id}/favorite`.

폴더, 문서, 연결 보기를 지우면 휴지통 항목의 `kind`가 `page`입니다. `page_kind`로 구분하고 `POST /page/{page_id}/restore`로 되돌립니다. 데이터베이스 페이지 삭제는 휴지통에 나오지 않습니다. 레코드 휴지통 항목의 `kind`는 `record`입니다.

## 보기 설정

`config.hidden_properties`는 숨길 속성 slug 배열입니다. 제목은 넣을 수 없습니다. `config.column_widths`는 slug별 1 이상의 정수입니다. 표의 `config.group_by`는 선택, 상태, 다중 선택입니다. 없으면 그룹이 없습니다. 행을 묶는 일은 프론트가 합니다.

## 변경 알림

연결, 페이로드, 대상별 다시 조회는 [workspace_realtime_frontend.md](workspace_realtime_frontend.md)입니다. 경로는 `ws/workspace/{workspace_id}/`이고, 메시지는 `workspace_changed`만 옵니다.

## 비범위

- 롤업, 버튼, Notion.com 동기화
- 글자 단위 병합. 블록 저장과 커서는 [workspace_collab_frontend.md](workspace_collab_frontend.md)입니다
- 사용자별 권한, 게스트, 공개 발행. 잠금은 데이터베이스와 문서 페이지의 `access`만 있다.
- 댓글 서식과 멘션. 댓글 본문은 일반 텍스트다.
- 블록 단위 휴지통
- 서버가 보드 열마다 페이지를 나눠 주는 것
- MCP로 댓글, 템플릿, 휴지통, 복원을 여는 것

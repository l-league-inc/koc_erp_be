# 워크스페이스

KOC 워크스페이스의 데이터 원본은 Django입니다. Notion.com과 동기화하지 않습니다. 저장 모양만 Notion 데이터베이스(속성, 레코드, 블록, 보기)를 따릅니다.

## 모델

| 모델 | 역할 |
|------|------|
| `Workspace` | 회사 공간. 슬러그 `koc`가 기본 시드 |
| `WorkspaceMember` | `owner` / `admin` / `member`. 이름 조회는 `GET /{workspace_id}/member` |
| `Database` | 업무 데이터베이스. `section`은 페이지 이름, `section_slug`는 페이지 키. 스킬용 슬러그는 `hr`, `daily`, `gov`, `purchase`, `sales`, `docs` |
| `Property` | 컬럼. 데이터베이스마다 `title` 타입은 하나 |
| `Record` | 행이자 페이지. `title`은 제목 속성과 같이 저장되고 `icon`은 페이지 아이콘 |
| `PropertyValue` | 타입별 값. `(record, property)`는 삭제되지 않은 행만 유니크 |
| `RelationLink` | relation 속성 연결 |
| `Block` | 페이지 본문. 기본 블록과 `toggle`, `callout`, `code`, `image` |
| `View` | 표/보드/목록/캘린더/갤러리와 필터. 보드·캘린더·갤러리는 `config`로 기준 속성을 검사 |
| `RecordActivity` | 생성·수정 스냅샷. `source`는 `user`, `mcp`, `agent`. 조회는 `GET /record/{id}/activity` |
| `RecordComment` | 레코드 댓글. 답글은 한 단계 |
| `DatabaseTemplate` | 새 레코드에 복사할 제목, 값, 블록 |

수식, 롤업, 버튼, Notion 동기화 필드는 없습니다. 통합대장은 데이터베이스가 아니라 워크스페이스 전체 레코드 조회입니다. 관계 값을 읽을 때는 `{id, title, database_id, database_slug}`이고, 쓸 때는 레코드 id 배열입니다. 레코드 삭제는 `deleted_at`만 찍고 값·블록·관계는 남깁니다. 데이터베이스 삭제는 속한 레코드까지 소프트 삭제하므로 휴지통 목록에 나오지 않습니다.

시드 명령은 두 개입니다. 둘 다 워크스페이스 `koc`를 없으면 만들고, 활성(`status=A`) 사용자를 멤버로 넣습니다. 이미 있는 데이터베이스와 속성은 덮어쓰지 않습니다. 같은 제목의 레코드도 다시 만들지 않습니다.

- `python manage.py seed_koc_workspace`: 에이전트 스킬이 쓰는 여섯 영역. `section`은 비어 있습니다. 담당은 `people`이고 사용자 id입니다.
- `python manage.py seed_koc_pages`: CSV 원본은 `app/workspace/fixtures/koc/`입니다. 데이터베이스 13개를 `section`으로 여섯 페이지에 묶고, 값이 있는 행을 레코드로 넣습니다. 프론트 속성 표는 [koc_pages_frontend.md](koc_pages_frontend.md)입니다.

`seed_koc_pages`의 페이지 키는 `hr`, `daily`, `gov`, `purchase`, `sales`, `docs`입니다. 이 키는 스킬용 데이터베이스 slug와 글자가 같고, 데이터는 다릅니다. 스킬용 `hr`의 담당은 멤버 id이고, CSV `attendance.employee`는 임직원 레코드 관계입니다.

관계 대상은 세 데이터베이스입니다.

| 대상 slug | 가리키는 칸 |
|-----------|-------------|
| `employees` | 근무·휴가·출장의 임직원, 일일 업무·정부과제·재고·문서의 담당, 휴가 승인자, 출장 신청자, A/S 처리담당, 사내규정 승인자 |
| `clients` | 일일 업무, 과제 지출, 견적, A/S, 회사 문서의 거래처 |
| `projects` | 일일 업무, 과제 지출, 회사 문서의 정부과제 |

금액은 통화 기호를 뺀 숫자, 한국어 날짜는 ISO 날짜로 저장합니다. `출장기간`처럼 화살표가 있는 값은 `{start, end}`입니다. 근무기록명이 비어 있으면 `근무일` 뒤에 `출근`을 붙인 제목을 씁니다. 칸이 모두 빈 행은 넣지 않습니다. 연결 대상을 찾지 못하면 그 관계만 비우고 경고를 출력합니다.

통합관리대장은 데이터베이스가 아닙니다. `database_slug` 없이 `POST /api/v1/workspace/query`를 호출합니다. 구매 / 발주 / 재고 페이지의 데이터베이스는 `inventory`이고, 최근 발주는 텍스트 속성 `latest_order`입니다.

## 권한

- 멤버가 아닌 워크스페이스 데이터는 403입니다. 없는 id는 404입니다.
- 워크스페이스 수정은 `owner`와 `admin`, 삭제는 `owner`만 가능합니다.
- 데이터베이스, 속성, 레코드, 블록, 보기, 템플릿, 댓글 작성, 휴지통 조회와 복원은 멤버라면 가능합니다.
- 댓글 삭제는 작성자이거나 `owner`, `admin`만 가능합니다.
- `GET /api/v1/workspace/{workspace_id}/member`는 멤버의 `user_id`, `name`, `role`을 돌려줍니다. 담당 속성에 넣을 값은 `user_id`입니다.
- 제목 속성은 지우거나 타입을 바꿀 수 없습니다.

## API

라우터는 `api/v1/workspace`이고 인증은 JWT입니다. 레코드 값은 속성 slug가 키입니다.

조회 본문 예:

```json
{
  "database_slug": "sales",
  "filters": [{"property": "status", "op": "eq", "value": "접수"}],
  "sorts": [{"property": "due_date", "direction": "asc"}],
  "q": "A/S",
  "page": 1,
  "page_size": 20
}
```

연산은 `eq`, `neq`, `contains`, `in`, `gt`, `gte`, `lt`, `lte`, `is_empty`입니다. 사람 속성의 `"me"`는 호출자 id로 바뀝니다. `view_id`를 주면 그 보기의 필터를 먼저 적용하고, 요청에 정렬이 있으면 보기 정렬 대신 요청 정렬을 씁니다. 페이지 아이콘, 서식 블록, 댓글, 활동, 템플릿, 휴지통, 보드·캘린더·갤러리 설정은 [workspace_page_frontend.md](workspace_page_frontend.md)와 같습니다.

## MCP

ChatGPT 커넥터는 기존 MCP(`/mcp`)를 씁니다. 허용된 도구는 아래뿐입니다.

- 워크스페이스 조회, 멤버 목록 조회
- 데이터베이스 목록 조회
- 데이터베이스 스키마 조회
- 레코드 조회, 상세 조회, 생성, 수정
- 워크봇 목록, 통계, 실행 이력 조회
- 워크봇 생성, 수정, 지금 실행

삭제, 멤버 변경, 속성 타입 변경, 데이터베이스 생성, 댓글, 템플릿, 휴지통, 복원, 워크봇 삭제, 실행 확정, 앱 대화 조회·확정, 스킬 조회·저장은 도구로 열지 않습니다. 대화 기록은 앱 화면 API에만 있습니다. 멤버 목록은 담당자 이름과 `user_id`를 맞추는 용도입니다. MCP 실행기는 `X-KOC-Client: mcp`를 붙여 활동 로그 `source`를 `mcp`로 남깁니다. 앱 안 에이전트가 확정한 기록은 `agent`입니다.

## Hermes

Hermes Agent의 언어 모델은 ChatGPT(OpenAI) API 키를 사용합니다. 이 저장소는 Hermes 프로세스를 띄우지 않습니다. Hermes나 ChatGPT 커넥터는 기존 MCP(`/mcp`) OAuth로 붙습니다. 도구 연결은 이 서버의 MCP입니다. Notion API 키는 쓰지 않습니다. 데이터는 Django 워크스페이스에 있고, Hermes는 레코드를 조회하거나 만들고 고치는 도구만 호출합니다. 앱 화면의 대화는 `/api/v1/agent`가 같은 모델을 호출합니다. 프롬프트에는 스킬 이름과 설명만 넣고, 필요한 스킬 전문을 읽은 뒤 처리합니다. 생성·수정은 사용자가 확정한 뒤에 저장합니다.

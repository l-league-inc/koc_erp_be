# 워크스페이스

KOC 워크스페이스의 데이터 원본은 Django입니다. Notion.com과 동기화하지 않습니다. 저장 모양만 Notion 데이터베이스(속성, 레코드, 블록, 보기)를 따릅니다.

## 모델

| 모델 | 역할 |
|------|------|
| `Workspace` | 회사 공간. 슬러그 `koc`가 기본 시드 |
| `WorkspaceMember` | `owner` / `admin` / `member`. 이름 조회는 `GET /{workspace_id}/member`, 등록·관리는 [workspace_members_frontend.md](workspace_members_frontend.md) |
| `Database` | 업무 데이터베이스. `section`은 페이지 이름, `section_slug`는 페이지 키. `access`는 본문 수정 권한 `member` 또는 `admin`. `seed_koc_workspace` 슬러그는 `hr`, `daily`, `gov`, `purchase`, `sales`, `docs` |
| `Page` | 사이드바 노드. `folder`, `document`, `database`, `linked_view`. 데이터베이스 페이지는 직계 폴더의 이름과 키를 `section`에 맞춥니다. 문서의 `access`는 그 페이지 블록 수정 권한 |
| `PageFavorite` | 사용자별 페이지 즐겨찾기 |
| `Property` | 컬럼. 데이터베이스마다 `title` 타입은 하나 |
| `Record` | 행이자 페이지. `title`은 제목 속성과 같이 저장되고 `icon`은 페이지 아이콘 |
| `PropertyValue` | 타입별 값. `(record, property)`는 삭제되지 않은 행만 유니크 |
| `RelationLink` | relation 속성 연결 |
| `Block` | 페이지 본문. 기본 블록과 `toggle`, `callout`, `code`, `image`, `simple_table`, `simple_columns`, `math_equation`, `link_preview`. `plain_text`는 검색에 쓰는 보이는 글 |
| `View` | 표/보드/목록/캘린더/갤러리와 필터. 보드·캘린더·갤러리는 `config`로 기준 속성을 검사 |
| `RecordActivity` | 생성·수정 스냅샷. `source`는 `user`, `mcp`, `agent`. 조회는 `GET /record/{id}/activity`. 블록 트리는 넣지 않습니다 |
| `DocumentRevision` | 레코드 또는 문서 페이지를 고치기 직전 본문. 최근 50건. 조회와 복원은 `GET|POST /record/{id}/revision`, `/page/{id}/revision` |
| `RecordComment` | 레코드 하단 댓글. 답글은 한 단계 |
| `BlockComment` | 블록 댓글. 답글은 한 단계. 루트만 `resolved_at`으로 해결 표시 |
| `CollabEvent` | 문서방 블록 변경. `collab_seq`와 함께 최근 100건. `since`로 빠진 변경만 전달 |
| `DatabaseTemplate` | 새 레코드에 복사할 제목, 값, 블록 |

롤업, 버튼, Notion 동기화, 글자 단위 병합은 없습니다. 수식과 북마크, 본문 표, 다단은 블록으로 저장합니다. 같은 문서를 연 멤버에게는 블록 변경과 커서를 알립니다.

저장은 REST이거나 문서방 소켓의 `op`입니다. 멤버 화면에는 `ws/workspace/{workspace_id}/`로 변경 사실만 알립니다. 열린 문서의 블록과 커서는 `ws/workspace/{workspace_id}/collab/{record|page}/{id}/`입니다. 프론트 계약은 [workspace_realtime_frontend.md](workspace_realtime_frontend.md), [workspace_collab_frontend.md](workspace_collab_frontend.md)입니다.

## 조회

- `q`는 제목, 속성 텍스트, 블록의 보이는 글을 봅니다. 서식 키와 파일 경로는 보지 않습니다.
- 필터 목록은 AND입니다. `{op: "and"|"or", filters: [...]}` 그룹은 한 단계 더 중첩할 수 있습니다.
- `created_at`, `updated_at`, `created_by`, `last_edited_by`는 속성 행 없이 필터와 정렬에 쓸 수 있습니다.
- 관계 값을 읽을 때는 `{id, title, database_id, database_slug}`이고, 쓸 때는 레코드 id 배열입니다.
- `config.two_way`가 참이면 반대 속성을 만들고 링크를 같이 갱신합니다. 기존 관계는 한 방향입니다.
- 통합대장은 데이터베이스가 아니라 워크스페이스 전체 레코드 조회입니다. `database_slug` 없이 `POST /api/v1/workspace/query`를 호출합니다.

## 삭제

- 레코드 삭제는 `deleted_at`만 찍습니다. 값, 블록, 관계는 남습니다.
- 데이터베이스 삭제는 속한 레코드까지 소프트 삭제하므로 휴지통 목록에 나오지 않습니다.

## 시드

두 명령 모두 워크스페이스 `koc`가 없으면 만들고, 활성(`status=A`) 사용자를 멤버로 넣습니다. 이미 있는 데이터베이스와 속성은 덮어쓰지 않습니다. 같은 제목의 레코드도 다시 만들지 않습니다.

- `python manage.py seed_koc_workspace`: 단순 여섯 영역. `section`은 비어 있습니다. 담당은 `people`이고 사용자 id입니다. 고정 스킬은 이 영역을 쓰지 않습니다.
- `python manage.py seed_koc_pages`: CSV 원본은 `app/workspace/fixtures/koc/`입니다. 데이터베이스 13개를 `section`으로 여섯 페이지에 묶고, 값이 있는 행을 레코드로 넣습니다. 프론트 속성 표는 [koc_pages_frontend.md](koc_pages_frontend.md)입니다.

`seed_koc_pages`의 페이지 키는 `hr`, `daily`, `gov`, `purchase`, `sales`, `docs`입니다. 글자는 `seed_koc_workspace` 데이터베이스 slug와 같고, 데이터는 다릅니다. 그 `hr`의 담당은 멤버 id이고, CSV `attendance.employee`는 임직원 레코드 관계입니다. 고정 스킬은 CSV 데이터베이스를 씁니다. 출근은 `attendance`, 일정은 `tasks`, 견적은 `quotes`, 출장은 `trip`, A/S는 `after_service`입니다.

관계 대상은 세 데이터베이스입니다.

| 대상 slug | 가리키는 칸 |
|-----------|-------------|
| `employees` | 근무·휴가·출장의 임직원, 일일 업무·정부과제·재고·문서의 담당, 휴가 승인자, 출장 신청자, A/S 처리담당, 사내규정 승인자 |
| `clients` | 일일 업무, 과제 지출, 견적, A/S, 회사 문서의 거래처 |
| `projects` | 일일 업무, 과제 지출, 회사 문서의 정부과제 |

값 규칙:

- 금액은 통화 기호를 뺀 숫자입니다.
- 한국어 날짜는 ISO 날짜로 저장합니다.
- `출장기간`처럼 화살표가 있는 값은 `{start, end}`입니다.
- 근무기록명이 비어 있으면 `근무일` 뒤에 `출근`을 붙인 제목을 씁니다.
- 칸이 모두 빈 행은 넣지 않습니다.
- 연결 대상을 찾지 못하면 그 관계만 비우고 경고를 출력합니다.

구매 / 발주 / 재고 페이지의 데이터베이스는 `inventory`입니다. 최근 발주는 텍스트 속성 `latest_order`입니다.

## 권한

- 멤버가 아닌 워크스페이스 데이터는 403입니다. 없는 id는 404입니다.
- 워크스페이스 수정은 `owner`와 `admin`, 삭제는 `owner`만 가능합니다.
- 데이터베이스, 속성, 레코드, 블록, 보기, 템플릿, 댓글 작성, 휴지통 조회와 복원은 기본적으로 멤버라면 가능합니다.
- `Database.access` 또는 문서 `Page.access`가 `admin`이면 그 본문과 레코드 저장은 `owner`, `admin`만 가능합니다. 멤버는 조회, 댓글, 멘션이 되고 저장과 문서방 `op`는 403입니다. 속성·보기 수정은 그대로 멤버가 합니다. `access` 변경은 `owner`, `admin`만 가능합니다.
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

연산은 `eq`, `neq`, `contains`, `in`, `gt`, `gte`, `lt`, `lte`, `is_empty`입니다. 사람 속성의 `"me"`는 호출자 id로 바뀝니다. `view_id`를 주면 그 보기의 필터를 먼저 적용하고, 요청에 정렬이 있으면 보기 정렬 대신 요청 정렬을 씁니다.

페이지 아이콘, 서식 블록, 댓글, 활동, 템플릿, 휴지통, 보드·캘린더·갤러리 설정은 [workspace_page_frontend.md](workspace_page_frontend.md)와 같습니다.

## MCP

ChatGPT 커넥터는 기존 MCP(`/mcp`)를 씁니다. 허용된 도구는 아래뿐입니다.

- 워크스페이스 조회, 멤버 목록 조회
- 데이터베이스 목록 조회
- 데이터베이스 스키마 조회
- 레코드 조회, 상세 조회, 생성, 수정
- 워크봇 목록, 통계, 실행 이력 조회
- 워크봇 생성, 수정, 지금 실행

도구로 열지 않는 것:

- 삭제, 멤버 변경, 속성 타입 변경, 데이터베이스 생성
- 댓글, 템플릿, 휴지통, 복원
- 워크봇 삭제, 실행 확정
- 앱 대화 조회·확정, 스킬 조회·저장

대화 기록은 앱 화면 API에만 있습니다. 멤버 목록은 담당자 이름과 `user_id`를 맞추는 용도입니다. MCP 실행기는 `X-KOC-Client: mcp`를 붙여 활동 로그 `source`를 `mcp`로 남깁니다. 앱 안 에이전트가 확정한 기록은 `agent`입니다.

## Hermes

Hermes Agent의 언어 모델은 ChatGPT(OpenAI) API 키를 사용합니다. 이 저장소는 Hermes 프로세스를 띄우지 않습니다.

Hermes나 ChatGPT 커넥터는 기존 MCP(`/mcp`) OAuth로 붙습니다. 도구 연결은 이 서버의 MCP입니다. Notion API 키는 쓰지 않습니다. 데이터는 Django 워크스페이스에 있고, Hermes는 레코드를 조회하거나 만들고 고치는 도구만 호출합니다.

앱 화면의 대화는 `/api/v1/agent`가 같은 모델을 호출합니다. 프롬프트에는 스킬 이름과 설명만 넣고, 필요한 스킬 전문을 읽은 뒤 처리합니다. 생성·수정은 사용자가 확정한 뒤에 저장합니다.

## 워크봇 예약 실행기

서버 프로세스(`config/asgi.py`)가 뜨면 `assistant.scheduler`의 백그라운드 스레드가 30초마다 `run_due_workbots`를 부릅니다. railway 설정에서는 기본으로 켜지고 `WORKBOT_SCHEDULER=0`이면 끕니다. 주기는 `WORKBOT_SCHEDULER_INTERVAL`(초)입니다. 워커가 여러 개여도 `claim_due_workbots`가 `next_run_at`을 조건부 UPDATE로 먼저 다음 일정으로 넘기므로 중복 실행되지 않습니다. 서버 안 스케줄러를 끈 환경에서는 `python manage.py run_workbot_scheduler`를 별도 프로세스로 두거나 `python manage.py run_due_workbots`를 주기적으로 부릅니다.

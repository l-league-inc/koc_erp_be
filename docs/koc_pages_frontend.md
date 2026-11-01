---
title: KOC 기본 페이지
audience: frontend
---

# KOC 기본 페이지

사이드바의 페이지 묶음과 그 안의 데이터베이스 계약입니다. 서버 명령 `python manage.py seed_koc_pages`가 만듭니다. 조회·저장의 공통 규칙은 [workspace_frontend.md](workspace_frontend.md)이고, 레코드 본문 화면은 [workspace_page_frontend.md](workspace_page_frontend.md)입니다.

여기서 페이지는 사이드바 그룹입니다. 레코드 한 건을 여는 화면과 다릅니다. 기본 경로는 `/api/v1/workspace`이고 인증은 JWT입니다.

## 유저 플로우

1. `GET /database`로 데이터베이스를 가져옵니다. 응답은 `position`, `id` 오름차순입니다.
2. `section_slug`가 같은 항목을 한 페이지로 모읍니다. 페이지 순서는 그 그룹에서 가장 작은 `position`입니다. 페이지 안도 `position` 오름차순입니다.
3. `section`이 빈 문자열이면 페이지 묶음이 없습니다. 그 항목은 그룹 아래에 그대로 둡니다.
4. 데이터베이스를 열면 `GET /database/{database_id}`의 `properties`로 열 머리와 입력 칸을 만듭니다. 선택 목록은 `config.options`의 `name`입니다.
5. 표는 `POST /query`에 `database_slug`를 넣어 그립니다. 시드 보기는 `전체` 표 하나라서 `view_id`만 넣어도 됩니다.
6. 관계 칸은 읽은 객체의 `title`을 보여주고, 저장할 때는 그 객체의 `id` 배열을 보냅니다.
7. 통합관리대장은 `database_slug`, `database_id`, `view_id`를 비운 `POST /query`입니다. 각 행의 `database_name`으로 영역을 구분합니다.

## 페이지

| section_slug | section | 데이터베이스 |
|--------------|---------|----------------|
| `hr` | 인사 / 근태 관리 | `employees` 임직원, `attendance` 근무 기록, `leave` 휴가, `trip` 출장 |
| `daily` | 일일 업무 관리 | `tasks` 일일 업무 |
| `gov` | 정부과제 및 거래처 | `projects` 정부과제, `expenses` 과제 지출, `clients` 거래처 |
| `purchase` | 구매 / 발주 / 재고 | `inventory` 재고 |
| `sales` | 영업 / 견적 / A/S | `quotes` 견적, `after_service` A/S |
| `docs` | 문서 및 사내규정 | `company_docs` 회사 문서, `policies` 사내규정 |

`section_slug`는 영문 소문자로 시작하고 숫자와 `_`만 씁니다. 구매 / 발주 / 재고의 데이터베이스는 재고입니다. 최근 발주는 `inventory.latest_order` 텍스트입니다.

## 관계

임직원, 거래처, 정부과제는 `people`이 아닙니다. 대상 데이터베이스의 레코드 id입니다.

| 데이터베이스 | slug | 대상 |
|--------------|------|------|
| `attendance` | `employee`, `confirmed_by` | `employees` |
| `leave` | `employee`, `approver` | `employees` |
| `trip` | `applicant` | `employees` |
| `tasks` | `owner` | `employees` |
| `tasks` | `client` | `clients` |
| `tasks` | `project` | `projects` |
| `projects` | `owner` | `employees` |
| `expenses` | `project` | `projects` |
| `expenses` | `client` | `clients` |
| `clients` | `owner` | `employees` |
| `inventory` | `owner` | `employees` |
| `quotes` | `client` | `clients` |
| `after_service` | `owner`, `handler` | `employees` |
| `after_service` | `client` | `clients` |
| `company_docs` | `owner` | `employees` |
| `company_docs` | `client` | `clients` |
| `company_docs` | `project` | `projects` |
| `policies` | `owner`, `approver` | `employees` |

읽기:

```json
"client": [
  {"id": 12, "title": "LG U+ 레저파워", "database_id": 4, "database_slug": "clients"}
]
```

쓰기:

```json
{"title": "견적", "values": {"client": [12], "status": "작성중", "total": "59400"}}
```

대상 후보 목록은 그 데이터베이스의 `POST /query`입니다. 멤버 이름 목록은 관계 칸에 쓰지 않습니다.

## 값

공통 쓰기·읽기 표는 [workspace_frontend.md](workspace_frontend.md)와 같습니다. 이 시드에서 자주 나오는 모양만 적습니다.

- 금액과 수량은 `number`입니다. 읽기는 `"59400"`, `"0.5"`처럼 문자열입니다.
- 하루 날짜는 `YYYY-MM-DD`로 쓰고, 읽기는 ISO 문자열입니다.
- 시각이 있는 날짜도 `date`입니다. `2026-10-12T23:40:00`처럼 보냅니다.
- 기간은 `{start, end}`입니다. `trip.period`가 이 모양입니다.
- `tasks.done`은 `checkbox`입니다. `true` 또는 `false`를 보냅니다.
- 선택·상태의 화면 글자는 `config.options[].name`입니다. 저장은 `name` 또는 `id`입니다. 시드 옵션 id는 이름에서 만든 값이라 화면에 고정하지 않습니다.

CSV에 값이 없어 시드가 미리 넣는 옵션:

| 데이터베이스 | slug | 옵션 name |
|--------------|------|-----------|
| `leave` | `approval_status` | 대기, 승인, 반려 |
| `expenses` | `expense_kind` | 확인필요 |
| `expenses` | `execution_status` | 대기, 진행 중, 완료 |
| `clients` | `account_status` | 거래중, 중단 |
| `after_service` | `severity` | 낮음, 보통, 높음 |

그 외 선택·상태는 가져온 행의 값으로 만들어집니다. 화면은 항상 스키마 응답을 씁니다.

## 속성

`title` 타입의 slug는 모두 `title`입니다. 응답의 `title`과 `values.title`은 같습니다.

### 임직원 `employees`

| slug | 이름 | 타입 |
|------|------|------|
| `title` | 이름 | `title` |
| `duty` | 담당업무 | `text` |
| `department` | 부서 | `text` |
| `email` | 사내 이메일 | `email` |
| `employee_no` | 사번 | `text` |
| `phone` | 연락처 | `phone` |
| `location` | 위치 | `text` |
| `hired_on` | 입사일 | `date` |
| `employment_status` | 재직상태 | `status` |
| `rank` | 직급 | `select` |
| `job` | 직무 | `text` |
| `left_on` | 퇴사일 | `date` |

### 근무 기록 `attendance`

| slug | 이름 | 타입 |
|------|------|------|
| `title` | 근무기록명 | `title` |
| `memo` | 근무메모 | `text` |
| `work_date` | 근무일 | `date` |
| `work_type` | 근무형태 | `select` |
| `attendance_status` | 근태상태 | `status` |
| `registered_at` | 등록시각(자동) | `date` |
| `employee` | 임직원 | `relation` → `employees` |
| `check_in` | 출근시각 | `date` |
| `check_out` | 퇴근시각 | `date` |
| `confirmed_by` | 확인담당 | `relation` → `employees` |

제목이 비어 있던 시드 행은 `2026년 10월 12일 출근`처럼 근무일 뒤에 `출근`을 붙입니다.

### 휴가 `leave`

| slug | 이름 | 타입 |
|------|------|------|
| `title` | 휴가신청명 | `title` |
| `days` | 사용일수 | `number` |
| `approval_status` | 승인상태 | `status` |
| `approver` | 승인자 | `relation` → `employees` |
| `start_date` | 시작일 | `date` |
| `employee` | 임직원 | `relation` → `employees` |
| `end_date` | 종료일 | `date` |
| `reason` | 휴가사유 | `text` |
| `leave_type` | 휴가유형 | `select` |

### 출장 `trip`

| slug | 이름 | 타입 |
|------|------|------|
| `title` | 출장 건명 | `title` |
| `attachment` | 기안 첨부자료 | `text` |
| `applicant` | 신청자 | `relation` → `employees` |
| `estimated_cost` | 예상 경비 | `number` |
| `submitted_at` | 접수일시(자동) | `date` |
| `purpose` | 출장 목적 | `text` |
| `period` | 출장기간 | `date` |
| `destination` | 출장지 | `text` |

`period` 쓰기 예:

```json
{"period": {"start": "2026-10-27", "end": "2026-10-28"}}
```

### 일일 업무 `tasks`

| slug | 이름 | 타입 |
|------|------|------|
| `title` | 업무명 | `title` |
| `result_url` | 결과링크 | `url` |
| `client` | 관련 거래처 | `relation` → `clients` |
| `project` | 관련 정부과제 | `relation` → `projects` |
| `owner` | 담당 임직원 | `relation` → `employees` |
| `due_date` | 마감일 | `date` |
| `body` | 업무내용 | `text` |
| `task_type` | 업무유형 | `select` |
| `work_date` | 업무일 | `date` |
| `done` | 완료 | `checkbox` |
| `priority` | 우선순위 | `select` |
| `status` | 진행상태 | `status` |

### 정부과제 `projects`

| slug | 이름 | 타입 |
|------|------|------|
| `title` | 사업명 | `title` |
| `notice_url` | 공고/협약 링크 | `url` |
| `announced_on` | 공고일 | `date` |
| `owner` | 담당 임직원 | `relation` → `employees` |
| `memo` | 비고 | `text` |
| `source_no` | 원본 관리번호 | `text` |
| `self_fund` | 자부담금 | `number` |
| `deadline` | 접수마감일 | `date` |
| `agency` | 주관기관 | `text` |
| `interim_on` | 중간보고일 | `date` |
| `grant_amount` | 지원금액 | `number` |
| `status` | 진행상태 | `status` |
| `deliverable` | 최종 결과물 | `text` |
| `final_on` | 최종보고일 | `date` |
| `contract_start` | 협약시작일 | `date` |
| `contract_end` | 협약종료일 | `date` |

### 과제 지출 `expenses`

| slug | 이름 | 타입 |
|------|------|------|
| `title` | 지출명 | `title` |
| `quote_url` | 견적서 링크 | `url` |
| `supply_amount` | 공급가액 | `number` |
| `project` | 관련 과제 | `relation` → `projects` |
| `vat` | 부가세 | `number` |
| `memo` | 비고 | `text` |
| `compare_url` | 비교견적서 링크 | `url` |
| `tax_url` | 세금계산서 링크 | `url` |
| `client` | 지출 거래처 | `relation` → `clients` |
| `expense_kind` | 지출구분 | `select` |
| `spent_on` | 지출일 | `date` |
| `total` | 지출합계 | `number` |
| `execution_status` | 집행상태 | `status` |
| `proof_url` | 집행증빙 링크 | `url` |
| `item` | 집행항목 | `text` |

### 거래처 `clients`

| slug | 이름 | 타입 |
|------|------|------|
| `title` | 업체명 | `title` |
| `account_status` | 거래상태 | `status` |
| `account_type` | 거래유형 | `select` |
| `client_no` | 거래처번호 | `text` |
| `contract_url` | 계약서 링크 | `url` |
| `owner` | 내부담당 | `relation` → `employees` |
| `contact_name` | 담당자명 | `text` |
| `ceo` | 대표자 | `text` |
| `memo` | 비고 | `text` |
| `business_no` | 사업자등록번호 | `text` |
| `license_url` | 사업자등록증 링크 | `url` |
| `phone` | 연락처 | `phone` |
| `email` | 이메일 | `email` |
| `address` | 주소 | `text` |

### 재고 `inventory`

| slug | 이름 | 타입 |
|------|------|------|
| `title` | 품목명 | `title` |
| `unit` | 단위 | `select` |
| `location` | 보관위치 | `text` |
| `category` | 분류 | `select` |
| `memo` | 비고 | `text` |
| `safety_stock` | 안전재고 | `number` |
| `stock_alert` | 재고경고 | `status` |
| `owner` | 재고담당 | `relation` → `employees` |
| `latest_order` | 최근 발주 | `text` |
| `received_on` | 최근입고일 | `date` |
| `item_code` | 품목코드 | `text` |
| `quantity` | 현재고 | `number` |

### 견적 `quotes`

| slug | 이름 | 타입 |
|------|------|------|
| `title` | 견적명 | `title` |
| `client` | 견적 거래처 | `relation` → `clients` |
| `quote_no` | 견적번호 | `text` |
| `status` | 견적상태 | `status` |
| `drive_url` | 견적서 Drive 링크 | `url` |
| `supply_amount` | 공급가액 | `number` |
| `labor_cost` | 공임 | `number` |
| `contact` | 담당자 | `text` |
| `issued_on` | 발행일 | `date` |
| `vat` | 부가세 | `number` |
| `parts_cost` | 부품비 | `number` |
| `memo` | 비고 | `text` |
| `team` | 운영팀 | `select` |
| `source_id` | 원본 견적 ID | `text` |
| `source_file` | 원본 파일명 | `text` |
| `valid_until` | 유효기간 | `date` |
| `unit_count` | 접수대수 | `number` |
| `shipping_cost` | 택배비 | `number` |
| `total` | 합계금액 | `number` |

`contact`는 거래처 담당자 이름 문자열입니다. 임직원 관계가 아닙니다.

### A/S `after_service`

| slug | 이름 | 타입 |
|------|------|------|
| `title` | 접수건명 | `title` |
| `client` | 관련 거래처 | `relation` → `clients` |
| `owner` | 담당 임직원 | `relation` → `employees` |
| `cost_type` | 비용구분 | `select` |
| `product` | 서비스/제품 | `select` |
| `unit_count` | 수리대수 | `number` |
| `severity` | 심각도 | `select` |
| `completed_on` | 완료일 | `date` |
| `team` | 운영팀 | `select` |
| `source_no` | 원본 문서번호 | `text` |
| `source_file` | 원본 파일명 | `text` |
| `serial_no` | 장비 일련번호 | `text` |
| `body` | 접수내용 | `text` |
| `ticket_no` | 접수번호 | `text` |
| `received_on` | 접수일 | `date` |
| `result` | 조치결과 | `text` |
| `proof_url` | 증빙링크 | `url` |
| `report` | 처리 보고 | `text` |
| `due_date` | 처리기한 | `date` |
| `handler` | 처리담당 | `relation` → `employees` |
| `status` | 처리상태 | `status` |
| `amount` | 청구금액 | `number` |

### 회사 문서 `company_docs`

| slug | 이름 | 타입 |
|------|------|------|
| `title` | 문서명 | `title` |
| `drive_url` | Google Drive 링크 | `url` |
| `client` | 관련 거래처 | `relation` → `clients` |
| `project` | 관련 정부과제 | `relation` → `projects` |
| `owner` | 담당 임직원 | `relation` → `employees` |
| `contact` | 담당자 | `text` |
| `issued_on` | 발행일 | `date` |
| `version` | 버전 | `text` |
| `security` | 보안등급 | `select` |
| `category` | 분류 | `select` |
| `memo` | 비고 | `text` |
| `expires_on` | 유효기한 | `date` |

### 사내규정 `policies`

| slug | 이름 | 타입 |
|------|------|------|
| `title` | 문서명 | `title` |
| `drive_url` | Google Drive 링크 | `url` |
| `change_note` | 개정내용 | `text` |
| `revised_on` | 개정일 | `date` |
| `owner` | 문서담당 | `relation` → `employees` |
| `status` | 문서상태 | `status` |
| `version` | 버전 | `text` |
| `category` | 분류 | `select` |
| `approver` | 승인자 | `relation` → `employees` |
| `audience` | 열람대상 | `text` |
| `effective_on` | 적용일 | `date` |

## 통합관리대장

데이터베이스를 만들지 않습니다. 조회 본문에서 `database_slug`, `database_id`, `view_id`를 비웁니다.

```json
{"q": "", "filters": [], "sorts": [{"property": "title", "direction": "asc"}], "page": 1, "page_size": 50}
```

`data[]`의 `database_slug`와 `database_name`으로 어느 데이터베이스 행인지 구분합니다. 열 구성은 데이터베이스마다 다르므로, 행을 열 때 `GET /database/{database_id}`로 그 행의 스키마를 가져옵니다.

## 구현 체크리스트

- 사이드바는 `section_slug`로 묶고, 그룹 순서는 그룹 안 최소 `position`이다.
- 페이지 제목은 `section`을 쓴다. 데이터베이스 제목은 `name`을 쓴다.
- 열 머리와 입력 타입은 `properties`의 `name`, `slug`, `type`, `config`를 쓴다. slug 표는 칸이 빠졌는지 확인하는 용도다.
- 선택 목록은 `config.options[].name`만 보여 주고, 저장은 `name`을 보낸다.
- 관계 후보를 열기 전에 대상 `database_slug`로 `POST /query`한다. 저장 값은 id 배열이다.
- 금액 칸은 읽은 문자열을 숫자로 보여 주고, 저장할 때 숫자 또는 숫자 문자열을 보낸다.
- `trip.period`는 시작과 끝을 가진 날짜 범위로 그린다.
- `tasks.done`은 체크박스다.
- 통합관리대장은 데이터베이스 필터 없이 조회하고, 행의 `database_name`을 영역 칸에 넣는다.
- URL 칸은 `http://` 또는 `https://`만 저장된다.

## 비범위

- 발주 전용 데이터베이스. 최근 발주 문장은 `inventory.latest_order`입니다.
- 통합관리대장 데이터베이스와 그 전용 스키마.
- 임직원 칸에 `people`과 멤버 `user_id`를 넣는 일. 그 타입은 `seed_koc_workspace`의 `hr`, `daily`, `gov`, `purchase`, `sales`, `docs`에 있습니다.
- 선택 옵션 id를 클라이언트에 하드코딩하는 일.
- Notion.com 동기화.

---
name: schedule
description: 일정과 일일 업무를 등록하거나 조회할 때 씁니다.
---

# 일정

일정, 할 일, 오늘 업무를 묻거나 등록하면 이 절차를 따릅니다.

1. `get_database_schema`로 `daily` 스키마를 확인합니다.
2. `list_members`로 담당 `user_id`를 확인합니다. 담당을 말하지 않으면 시스템 프롬프트의 사용자 id를 씁니다. `owner`는 그 id를 원소로 하는 배열입니다.
3. 같은 날 중복을 확인합니다. `query_records`의 `database_slug`는 `daily`이고, 제목 검색 `q`와 필터 `owner` eq `me`, `due_date` eq 해당 날짜(`YYYY-MM-DD`)를 함께 씁니다. 같은 제목의 행이 있으면 새로 만들지 않고 그 행을 안내하거나 `propose_update_record`로 바뀐 `status`, `due_date`, `memo`만 초안을 만듭니다.
4. 없을 때만 `propose_create_record`를 씁니다. `database_slug`는 `daily`입니다. `title`은 사용자가 말한 일정 이름입니다. `values.status`는 스키마 옵션 중 진행에 맞는 이름, `values.owner`는 담당 id 배열, `values.due_date`는 말한 날짜 또는 오늘, `values.memo`는 추가 설명입니다.
5. 저장이 끝났다고 말하지 않습니다. 사용자가 초안을 확정하기 전에는 레코드가 없습니다.

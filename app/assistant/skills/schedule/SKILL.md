---
name: schedule
description: 일정과 일일 업무를 등록하거나 조회할 때 씁니다.
---

# 일정

일정, 할 일, 오늘 업무를 묻거나 등록하면 이 절차를 따릅니다.

1. `get_database_schema`로 `tasks` 스키마를 확인합니다. `status`는 스키마 옵션에 있는 이름만 씁니다. 없는 옵션은 비웁니다.
2. 담당 임직원을 찾습니다. `query_records`의 `database_slug`는 `employees`이고, 필터는 `email` eq 시스템 프롬프트의 사용자 이메일입니다. 없거나 이름을 말했으면 `q`로 이름을 찾습니다. 한 건이면 그 레코드 id를 씁니다. 없거나 여러 건이면 초안을 만들지 않고 누구인지 묻습니다.
3. 같은 날 중복을 확인합니다. `query_records`의 `database_slug`는 `tasks`이고, 제목 검색 `q`와 필터 `owner` eq 임직원 레코드 id, `work_date` eq 해당 날짜(`YYYY-MM-DD`)를 함께 씁니다. 관계 필터 값은 id 하나이고 배열이나 `me`가 아닙니다. 같은 제목의 행이 있으면 새로 만들지 않고 그 행을 안내하거나 `propose_update_record`로 바뀐 `due_date`, `body`만 초안을 만듭니다. `status`와 `done`은 사용자가 말한 값이 스키마와 맞을 때만 넣습니다.
4. 없을 때만 `propose_create_record`를 씁니다. `database_slug`는 `tasks`입니다. `title`은 사용자가 말한 일정 이름입니다. `values.owner`는 임직원 id를 원소로 하는 배열입니다. `values.work_date`는 말한 날짜 또는 오늘입니다. 마감을 말했으면 `values.due_date`, 설명이 있으면 `values.body`에 넣습니다. `status`와 `done`은 사용자가 말한 값이 스키마와 맞을 때만 넣습니다.
5. 저장이 끝났다고 말하지 않습니다. 사용자가 초안을 확정하기 전에는 레코드가 없습니다.

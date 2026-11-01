---
name: attendance
description: 출근 기록을 남기거나 오늘 출근 여부를 확인할 때 씁니다.
---

# 출근

출근, 근태 체크, 오늘 출근 등록을 요청하면 이 절차를 따릅니다.

1. `get_database_schema`로 `hr` 스키마를 확인합니다. 옵션 이름은 스키마에 있는 값을 씁니다.
2. `list_members`로 담당 `user_id`를 확인합니다. 담당을 말하지 않으면 시스템 프롬프트의 사용자 id를 씁니다. `owner`는 그 id를 원소로 하는 배열입니다.
3. 같은 날 중복을 확인합니다. `query_records`의 `database_slug`는 `hr`이고, 필터는 `kind` eq `출근`, `owner` eq `me`, `due_date` eq 오늘 날짜(`YYYY-MM-DD`)입니다. 같은 담당의 오늘 출근이 있으면 새로 만들지 않고 그 행을 안내합니다.
4. 없을 때만 `propose_create_record`를 씁니다. `database_slug`는 `hr`, `title`은 `출근`, `values.kind`는 `출근`, `values.status`는 `출근`, `values.due_date`는 오늘, `values.owner`는 담당 id 배열입니다.
5. 저장이 끝났다고 말하지 않습니다. 사용자가 초안을 확정하기 전에는 레코드가 없습니다.

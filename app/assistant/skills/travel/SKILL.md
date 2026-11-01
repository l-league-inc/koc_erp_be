---
name: travel
description: 출장을 등록하거나 같은 날 출장 여부를 확인할 때 씁니다.
---

# 출장

출장 등록, 출장 일정, 출장 여부를 묻거나 기록하면 이 절차를 따릅니다.

1. `get_database_schema`로 `hr` 스키마를 확인합니다. 옵션 이름은 스키마에 있는 값을 씁니다.
2. `list_members`로 담당 `user_id`를 확인합니다. 담당을 말하지 않으면 시스템 프롬프트의 사용자 id를 씁니다. `owner`는 그 id를 원소로 하는 배열입니다.
3. 같은 날 중복을 확인합니다. `query_records`의 `database_slug`는 `hr`이고, 필터는 `kind` eq `출장`, `owner` eq `me`, `due_date` eq 출장일(`YYYY-MM-DD`)입니다. 같은 담당의 그 날짜 출장이 있으면 새로 만들지 않고 그 행을 안내하거나, 메모만 바뀌었으면 `propose_update_record`로 `memo` 초안을 만듭니다.
4. 없을 때만 `propose_create_record`를 씁니다. `database_slug`는 `hr`, `title`은 행선지가 있으면 그 이름이고 없으면 `출장`입니다. `values.kind`는 `출장`, `values.status`는 `출장`, `values.due_date`는 출장일 또는 오늘, `values.owner`는 담당 id 배열, `values.memo`는 목적입니다.
5. 저장이 끝났다고 말하지 않습니다. 사용자가 초안을 확정하기 전에는 레코드가 없습니다.

---
name: quote
description: 견적을 접수하거나 금액·상태를 바꿀 때 씁니다.
---

# 견적

견적, 견적서, 견적 금액을 묻거나 등록하면 이 절차를 따릅니다.

1. `get_database_schema`로 `sales` 스키마를 확인합니다. `kind`와 `status`는 스키마 옵션 이름을 씁니다.
2. `list_members`로 담당 `user_id`를 확인합니다. 담당을 말하지 않으면 시스템 프롬프트의 사용자 id를 씁니다. `owner`는 그 id를 원소로 하는 배열입니다.
3. 같은 견적 중복을 확인합니다. `query_records`의 `database_slug`는 `sales`이고, 필터는 `kind` eq `견적`입니다. 제목이 있으면 `q`로 찾고, 날짜를 말했으면 `due_date` eq 그 날짜를 더합니다. 같은 제목이 있으면 새로 만들지 않고 `propose_update_record`로 `status`, `amount`, `due_date`, `owner` 중 바뀐 값만 초안을 만듭니다.
4. 없을 때만 `propose_create_record`를 씁니다. `database_slug`는 `sales`, `values.kind`는 `견적`, `values.status`는 말하지 않았으면 `접수`, `values.amount`는 말한 금액, `values.owner`는 담당 id 배열, `values.due_date`는 말한 날짜입니다. 금액을 말하지 않았으면 `amount`를 비웁니다.
5. 저장이 끝났다고 말하지 않습니다. 사용자가 초안을 확정하기 전에는 레코드가 없습니다.

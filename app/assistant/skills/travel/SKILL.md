---
name: travel
description: 출장을 등록하거나 같은 날 출장 여부를 확인할 때 씁니다.
---

# 출장

출장 등록, 출장 일정, 출장 여부를 묻거나 기록하면 이 절차를 따릅니다.

1. `get_database_schema`로 `trip` 스키마를 확인합니다.
2. 신청자를 찾습니다. `query_records`의 `database_slug`는 `employees`이고, 필터는 `email` eq 시스템 프롬프트의 사용자 이메일입니다. 없거나 이름을 말했으면 `q`로 이름을 찾습니다. 한 건이면 그 레코드 id를 씁니다. 없거나 여러 건이면 초안을 만들지 않고 누구인지 묻습니다.
3. 같은 날 중복을 확인합니다. `query_records`의 `database_slug`는 `trip`이고, 필터는 `applicant` eq 임직원 레코드 id, `period` eq 출장 시작일(`YYYY-MM-DD`)입니다. 관계 필터 값은 id 하나이고 배열이나 `me`가 아닙니다. 같은 신청자의 그 날짜 출장이 있으면 새로 만들지 않고 그 행을 안내하거나, 목적만 바뀌었으면 `propose_update_record`로 `purpose` 초안을 만듭니다.
4. 없을 때만 `propose_create_record`를 씁니다. `database_slug`는 `trip`입니다. `title`은 행선지가 있으면 그 이름이고 없으면 `출장`입니다. `values.applicant`는 임직원 id를 원소로 하는 배열입니다. `values.destination`은 출장지, `values.purpose`는 목적입니다. `values.period`는 `{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}`이고, 종료일을 말하지 않았으면 start와 end를 같은 날로 둡니다. 경비를 말했으면 `values.estimated_cost`에 넣습니다.
5. 저장이 끝났다고 말하지 않습니다. 사용자가 초안을 확정하기 전에는 레코드가 없습니다.

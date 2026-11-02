---
name: attendance
description: 출근 기록을 남기거나 오늘 출근 여부를 확인할 때 씁니다.
---

# 출근

출근, 근태 체크, 오늘 출근 등록을 요청하면 이 절차를 따릅니다.

1. `get_database_schema`로 `attendance` 스키마를 확인합니다. `work_type`과 `attendance_status`는 스키마 옵션에 있는 이름만 씁니다. 없는 옵션은 비웁니다.
2. 임직원을 찾습니다. `query_records`의 `database_slug`는 `employees`이고, 필터는 `email` eq 시스템 프롬프트의 사용자 이메일입니다. 없거나 이름을 말했으면 `q`로 이름을 찾습니다. 한 건이면 그 레코드 id를 씁니다. 없거나 여러 건이면 초안을 만들지 않고 누구인지 묻습니다.
3. 같은 날 중복을 확인합니다. `query_records`의 `database_slug`는 `attendance`이고, 필터는 `employee` eq 임직원 레코드 id, `work_date` eq 오늘 날짜(`YYYY-MM-DD`)입니다. 관계 필터 값은 id 하나이고 배열이나 `me`가 아닙니다. 같은 임직원의 오늘 출근이 있으면 새로 만들지 않고 그 행을 안내합니다.
4. 없을 때만 `propose_create_record`를 씁니다. `database_slug`는 `attendance`입니다. `title`은 `YYYY-MM-DD 출근`입니다. `values.work_date`는 오늘입니다. `values.employee`는 임직원 id를 원소로 하는 배열입니다. 출근 시각을 말했으면 `values.check_in`에 넣고, 메모를 말했으면 `values.memo`에 넣습니다. `work_type`과 `attendance_status`는 사용자가 말한 값이 스키마 옵션과 같을 때만 넣습니다.
5. 저장이 끝났다고 말하지 않습니다. 사용자가 초안을 확정하기 전에는 레코드가 없습니다.

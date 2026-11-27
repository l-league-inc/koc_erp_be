---
name: attendance
description: 출근 기록을 남기거나 오늘 출근 여부를 확인하고, 야근 시간을 신청할 때 씁니다.
---

# 출근

출근, 근태 체크, 오늘 출근 등록, 야근 신청을 요청하면 이 절차를 따릅니다.

1. `get_database_schema`로 `attendance` 스키마를 확인합니다. `work_type`과 `attendance_status`는 스키마 옵션에 있는 이름만 씁니다. 없는 옵션은 비웁니다.
2. 임직원을 찾습니다. 사용자가 다른 사람 이름을 말하지 않았으면 본인입니다. `find_self_employee`를 호출합니다. `found`가 true이면 그 `id`를 쓰고 이름을 묻지 않습니다. "출근"만 말해도 그 사람 출근을 만듭니다. `found`가 false이고 `matches`가 있으면 그중 누구인지 묻습니다. 한 건도 없으면 임직원 기록이 없다고 알리고 초안을 만들지 않습니다. 다른 사람 이름을 말했으면 `query_records`의 `database_slug`는 `employees`이고 `q`는 그 이름입니다. 제목이 그 이름과 같은 한 건이면 그 id를 씁니다. 없거나 여러 건이면 초안을 만들지 않고 누구인지 묻습니다.
3. 같은 날 중복을 확인합니다. `query_records`의 `database_slug`는 `attendance`이고, 필터는 `employee` eq 임직원 레코드 id, `work_date` eq 오늘 날짜(`YYYY-MM-DD`)입니다. 관계 필터 값은 id 하나이고 배열이나 `me`가 아닙니다. 같은 임직원의 오늘 출근이 있으면 새로 만들지 않고 그 행을 안내합니다.
4. 출근만 요청한 경우, 없을 때만 `propose_create_record`를 씁니다. `database_slug`는 `attendance`입니다. `title`은 `YYYY-MM-DD 출근`입니다. `values.work_date`는 오늘입니다. `values.employee`는 임직원 id를 원소로 하는 배열입니다. `check_in`과 `check_out`은 넣지 않습니다. 사용자가 시각을 말해도 그 시각은 저장하지 않고, 출근·퇴근 시각은 서버가 현재 시각만 남긴다고 안내합니다. 메모를 말했으면 `values.memo`에 넣습니다. `work_type`과 `attendance_status`는 사용자가 말한 값이 스키마 옵션과 같을 때만 넣습니다.
5. 야근 시간을 말하면 새 출근 행을 만들지 않습니다. 오늘 출근 행이 없으면 먼저 출근하라고 안내합니다. 있으면 `propose_update_record`에 `overtime_minutes`(분, 1 이상 720 이하 정수)와 `overtime_reason`만 넣습니다. `overtime_status`, `check_in`, `check_out`은 넣지 않습니다. 사용자가 승인을 요청해도 상태를 승인으로 넣지 않습니다. 저장되면 대기이며, 관리자 승인 전에는 야근 시간으로 반영되지 않았다고 안내합니다.
6. `propose_create_record`가 `confirmed`와 `record_id`를 돌려주면 출근 기록은 이미 저장된 것입니다. 그 제목과 저장되었다는 사실을 사용자에게 알립니다. 확정 전이라거나 아직 반영되지 않았다고 말하지 않습니다. 야근 신청이 접수된 경우에는 관리자 승인 전이라고 말합니다.

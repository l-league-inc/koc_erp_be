---
name: leave
description: 휴가를 신청하거나 신청한 휴가의 사유, 기간, 유형을 고칠 때 씁니다.
---

# 휴가

휴가, 연차, 반차 신청과 그 내용 수정을 요청하면 이 절차를 따릅니다.

1. 초안 상태를 먼저 봅니다. 시스템 프롬프트에 `pending` `create_record`이고 `database_slug`가 `leave`이며 `record_id`가 없으면 스키마와 레코드를 조회하지 않습니다. `revise_pending_action`을 한 번만 호출하고 도구를 멈춥니다. `action_id`는 그 초안 id입니다. `values`에는 바뀐 칸만 넣습니다. 사유는 `reason`, 시작일은 `start_date`, 종료일은 `end_date`, 유형은 `leave_type`, 일수는 `days`입니다. `start_date`와 `end_date`는 각각 `YYYY-MM-DD` 문자열입니다. `period`로 합치지 않습니다. 사용자에게는 초안이 바뀌었고 확정 전에는 저장되지 않는다고 안내합니다.
2. `confirmed`이고 `record_id`가 있으면 `propose_update_record`를 한 번만 호출하고 도구를 멈춥니다. `record_id`는 그 값입니다. 바뀐 `values`만 넣고 날짜 규칙은 1번과 같습니다. 저장이 끝났다고 말하지 않습니다.
3. 대기 초안도 확정된 레코드도 없을 때만 새로 만듭니다. `get_database_schema`로 `leave`를 확인합니다. `leave_type`과 `approval_status`는 스키마 옵션에 있는 이름만 씁니다. 없는 옵션은 비웁니다.
4. 임직원을 찾습니다. 다른 사람을 지목하지 않았으면 `find_self_employee`를 호출합니다. `found`가 true이면 그 `id`를 쓰고 이름을 묻지 않습니다. `found`가 false이고 `matches`가 있으면 그중 누구인지 묻습니다. 한 건도 없으면 임직원 기록이 없다고 알리고 초안을 만들지 않습니다. 다른 사람 이름을 말했으면 `query_records`의 `database_slug`는 `employees`이고 `q`는 그 이름입니다. 제목이 그 이름과 같은 한 건이면 그 id를 씁니다. 없거나 여러 건이면 초안을 만들지 않고 누구인지 묻습니다.
5. 같은 시작일 중복을 확인합니다. `query_records`의 `database_slug`는 `leave`이고, 필터는 `employee` eq 임직원 레코드 id, `start_date` eq 시작일(`YYYY-MM-DD`)입니다. 관계 필터 값은 id 하나이고 배열이나 `me`가 아닙니다. 같은 임직원의 그 시작일 휴가가 있으면 새로 만들지 않고 그 행을 안내하거나, 내용만 바뀌었으면 `propose_update_record`로 바뀐 값만 초안을 만듭니다.
6. 없을 때만 `propose_create_record`를 씁니다. `database_slug`는 `leave`입니다. `title`은 말한 이름이고 없으면 `YYYY-MM-DD 휴가`입니다. `values.employee`는 임직원 id를 원소로 하는 배열입니다. `values.start_date`와 `values.end_date`는 각각 날짜 문자열입니다. 종료일을 말하지 않았으면 시작일과 같게 둡니다. 사유를 말했으면 `values.reason`에 넣습니다. `leave_type`과 `days`는 사용자가 말한 값이 스키마와 맞을 때만 넣습니다.
7. 저장이 끝났다고 말하지 않습니다. 사용자가 초안을 확정하기 전에는 레코드가 없습니다.

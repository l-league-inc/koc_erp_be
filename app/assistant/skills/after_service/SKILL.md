---
name: after_service
description: A/S를 접수하거나 진행 상태를 바꿀 때 씁니다.
---

# A/S

A/S, 애프터서비스, 수리 접수를 묻거나 등록하면 이 절차를 따릅니다.

1. `get_database_schema`로 `after_service` 스키마를 확인합니다. `status`와 선택 속성은 스키마 옵션에 있는 이름만 씁니다. 없는 옵션은 비웁니다.
2. 담당을 말했으면 임직원을 찾습니다. `query_records`의 `database_slug`는 `employees`이고, 본인이면 필터 `email` eq 시스템 프롬프트의 사용자 이메일, 다른 사람이면 `q`로 이름을 찾습니다. 한 건이면 그 레코드 id를 씁니다. 없거나 여러 건이면 초안을 만들지 않고 누구인지 묻습니다. 담당을 말하지 않았으면 `owner`와 `handler`를 비웁니다.
3. 거래처 이름을 말했으면 `query_records`의 `database_slug`는 `clients`이고 `q`는 그 이름입니다. 한 건이면 그 레코드 id를 씁니다. 없거나 여러 건이면 초안을 만들지 않고 어느 거래처인지 묻습니다. 이름을 말하지 않았으면 `client`를 비웁니다.
4. 같은 접수 중복을 확인합니다. `query_records`의 `database_slug`는 `after_service`입니다. 제목이 있으면 `q`로 찾고, 날짜를 말했으면 `received_on` eq 그 날짜(`YYYY-MM-DD`)를 더합니다. 같은 제목이 있으면 새로 만들지 않고 `propose_update_record`로 `status`, `due_date`, `amount`, `owner`, `handler` 중 바뀐 값만 초안을 만듭니다.
5. 없을 때만 `propose_create_record`를 씁니다. `database_slug`는 `after_service`입니다. `title`은 접수 내용입니다. `values.body`는 접수 내용입니다. `values.received_on`은 말한 접수일 또는 오늘이고, 기한을 말했으면 `values.due_date`에 넣습니다. `values.amount`는 금액을 말했을 때만 넣습니다. `values.client`는 거래처 id 배열입니다. 담당은 `values.owner`, 처리담당을 따로 말했으면 `values.handler`에 임직원 id 배열을 넣습니다. `status`는 사용자가 말한 값이 스키마 옵션과 같을 때만 넣습니다.
6. 저장이 끝났다고 말하지 않습니다. 사용자가 초안을 확정하기 전에는 레코드가 없습니다.

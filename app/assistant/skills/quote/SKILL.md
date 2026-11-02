---
name: quote
description: 견적을 접수하거나 금액·상태를 바꿀 때 씁니다.
---

# 견적

견적, 견적서, 견적 금액을 묻거나 등록하면 이 절차를 따릅니다.

1. `get_database_schema`로 `quotes` 스키마를 확인합니다. `status`와 `team`은 스키마 옵션에 있는 이름만 씁니다. 없는 옵션은 비웁니다.
2. 거래처 이름을 말했으면 `query_records`의 `database_slug`는 `clients`이고 `q`는 그 이름입니다. 한 건이면 그 레코드 id를 씁니다. 없거나 여러 건이면 초안을 만들지 않고 어느 거래처인지 묻습니다. 이름을 말하지 않았으면 `client`를 비웁니다.
3. 같은 견적 중복을 확인합니다. `query_records`의 `database_slug`는 `quotes`입니다. 제목이 있으면 `q`로 찾고, 날짜를 말했으면 `issued_on` eq 그 날짜(`YYYY-MM-DD`)를 더합니다. 같은 제목이 있으면 새로 만들지 않고 `propose_update_record`로 `status`, `total`, `issued_on`, `client` 중 바뀐 값만 초안을 만듭니다. 금액 항목을 짚었으면 `supply_amount`, `labor_cost`, `vat`, `parts_cost`, `shipping_cost` 중 그 항목만 바꿉니다.
4. 없을 때만 `propose_create_record`를 씁니다. `database_slug`는 `quotes`입니다. `title`은 견적 이름입니다. `values.issued_on`은 말한 날짜 또는 오늘입니다. 금액을 말했고 항목을 짚지 않았으면 `values.total`에 넣습니다. 항목을 짚었으면 그 속성만 넣습니다. `values.client`는 거래처 id를 원소로 하는 배열입니다. `contact`는 담당자 이름을 말했으면 문자열로 넣습니다. `status`는 사용자가 말한 값이 스키마 옵션과 같을 때만 넣습니다.
5. 저장이 끝났다고 말하지 않습니다. 사용자가 초안을 확정하기 전에는 레코드가 없습니다.

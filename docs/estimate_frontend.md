---
title: 견적서 작성
audience: frontend
---

# 견적서 작성

견적서 양식 docx에 거래처, 부서, 담당자, 견적일과 장비 행을 넣고 파일을 돌려줍니다. 행 금액, 공급가액, 부가세, 합계는 서버가 계산합니다. 만든 파일을 다시 읽어 맞는지 확인한 뒤에만 응답합니다. 인증은 기존 JWT입니다.

양식에는 장비 칸이 6개입니다. 한 칸은 품번, 부품, 작업시간 세 줄입니다. 부품이 두 줄이거나 장비가 7대 이상이면 400입니다. 행은 추가하지 않습니다.

## 유저 플로우

1. 거래처, 부서, 담당자, 견적일, 품명, 장비와 택배 단가를 알고 있으면 `POST /api/v1/estimate/documents`로 보냅니다.
2. 문장만 있으면 `POST /api/v1/estimate/documents/from-instruction`으로 보냅니다. 서버가 행 구조만 만들고, 단가와 수량은 문장에 있는 값만 씁니다.
3. 응답이 docx면 다운로드합니다. 400이면 `detail`을 그대로 보여 주고 파일을 저장하지 않습니다.
4. 견적 레코드나 드라이브 업로드는 이 API가 하지 않습니다.

## API

기본 경로는 `/api/v1/estimate`입니다.

- `POST /documents` 구조화 입력. 응답은 docx 첨부
- `POST /documents/from-instruction` 자연어 입력. 응답은 docx 첨부

성공 `Content-Type`은 `application/vnd.openxmlformats-officedocument.wordprocessingml.document`입니다. `Content-Disposition`은 `attachment`이고 파일명은 `견적서_{거래처}_{YYYY-MM-DD}.docx`입니다.

금액 필드는 요청에 없습니다. 부품 금액은 수량×단가, 작업 금액은 시간×시간당 단가, 장비 금액은 그 둘의 합입니다. 공급가액은 장비 금액 합 + 택배비입니다. 부가세는 공급가액의 10%를 원 단위 반올림한 값입니다. 합계는 공급가액+부가세이고, 표 상단 합계와 같습니다.

### 구조화 작성

```json
{
  "client": "LG유플러스",
  "department": "수원운영팀",
  "contact": "김현전",
  "issued_on": "2026-11-10",
  "product_name": "ESLP-440P(기본형)",
  "devices": [
    {
      "serial": "S/N-LP2201211",
      "part_name": "배터리 교체",
      "part_unit": "EA",
      "part_qty": 1,
      "part_unit_price": 260000,
      "labor_level": "상",
      "labor_hours": 3,
      "labor_unit_price": 20000
    }
  ],
  "shipping_qty": 6,
  "shipping_unit_price": 16000
}
```

`part_unit`을 빼면 `EA`입니다. `labor_level`은 `상` 또는 `하`입니다. `shipping_qty`가 0이면 택배 행은 비웁니다. `devices`는 1개 이상 6개 이하입니다.

머리글은 `{거래처} {부서}`, `{담당자} 님 귀중`, `견적일자 : 2026년 11월 10일`입니다. 월과 일에는 0을 붙이지 않습니다.

### 지시로 작성

```json
{
  "instruction": "LG유플러스 수원운영팀 김현전님, 2026-11-10, ESLP-440P. S/N-LP2201211 배터리 교체 260000원, 난이도 상 3시간 시간당 20000원. 택배 6대 대당 16000원.",
  "model": ""
}
```

`model`을 비우면 견적 작성자의 선택된 모델을 씁니다. 값을 넣으면 그 요청에 쓰고 선택도 바꿉니다. 문장에 없는 단가는 만들지 않으며 400입니다.

## 에러

- 400: 장비 6대 초과, 거래처·부서·담당자·품명·단가·난이도 누락, 만든 문서의 금액이 맞지 않음. 본문은 `{"detail": "..."}`입니다.
- 422: 필드 타입이 다를 때
- 502: 자연어 작성에서 언어 모델 호출 실패
- 503: 언어 모델 키가 없을 때

## 업무 대화

고정 스킬 이름은 `estimate`입니다. 도구는 `propose_create_estimate`이고 초안 `kind`는 `create_estimate`입니다. 확정 응답 `estimates`의 `docx_base64`가 파일입니다. 견적 레코드 접수·수정은 고정 스킬 `quote`입니다. 자세한 초안 필드는 [agent_frontend.md](agent_frontend.md)에 있습니다.

## MCP

공개되는 것:

- `POST /api/v1/estimate/documents/json`
- `POST /api/v1/estimate/documents/from-instruction/json`

둘 다 JSON입니다. `docx_base64`를 디코드하면 docx입니다. `supply_amount`, `vat`, `total`은 서버 계산값입니다. 견적 레코드는 만들지 않습니다. 바이너리 `POST /documents`와 `POST /documents/from-instruction`은 MCP에 열지 않습니다. 지시 작성은 언어 모델 호출 때문에 MCP 제한 시간을 120초로 둡니다.

## 구현 체크리스트

- 앱 화면의 직접 작성은 `POST /documents`의 바이너리를 저장한다. 업무 대화는 확정 응답의 `docx_base64`를 저장한다. MCP도 `docx_base64`를 쓴다.
- 400 `detail`을 그대로 보여 주고, 실패한 응답으로 파일을 만들지 않는다.
- 합계 입력란을 만들지 않는다. 화면 합계가 필요하면 같은 식(공급가의 10% 원 단위 반올림)으로 미리보기만 한다.
- 장비 6대, 장비당 부품 1줄과 작업시간 1줄을 넘기면 보내기 전에 막거나 서버 400을 처리한다.

## 비범위

- 견적 레코드 생성과 드라이브 업로드
- 양식에 없는 6대 초과, 부품 2줄 이상
- 사용자가 말하지 않은 단가 추정

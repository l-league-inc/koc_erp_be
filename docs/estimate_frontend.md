---
title: 견적서 작성
audience: frontend
---

# 견적서 작성

견적서 양식 docx에 거래처, 부서, 담당자, 견적일과 장비 행을 넣고 파일을 돌려줍니다. 행 금액, 공급가액, 부가세, 합계는 서버가 계산합니다. 만든 파일을 다시 읽어 맞는지 확인한 뒤에만 응답합니다. 인증은 기존 JWT입니다.

양식에는 장비 칸이 6개입니다. 한 칸은 품번, 부품, 작업시간 세 줄입니다. 부품이 두 줄이거나 장비가 7대 이상이면 400입니다. 행은 추가하지 않습니다.

## 유저 플로우

1. 사용자가 자연어로 견적서를 요청하면 `POST /api/v1/estimate/documents/from-instruction/json`으로 보냅니다. 서버가 행만 판단하고, 말하지 않은 단가는 만들지 않습니다.
2. 응답의 `draft`를 편집 폼에 넣고 `docx_base64`를 미리보기로 엽니다. 고친 값은 같은 `draft` 모양으로 `POST /api/v1/estimate/documents/json`에 다시 보내 미리보기를 갱신합니다.
3. PDF 다운로드는 그 `draft`를 `POST /api/v1/estimate/documents/pdf`로 보냅니다. 화면이 JSON이 필요하면 `POST /documents/pdf/json`의 `pdf_base64`를 씁니다. PDF는 미리보기 docx를 그대로 변환한 파일이며 회사 직인 이미지가 유지됩니다.
4. 메일 보내기는 선택입니다. 사용자가 받는 사람을 확인한 뒤에만 `POST /api/v1/estimate/documents/send`에 `draft`와 `to`를 보냅니다. PDF가 첨부됩니다. Daum 계정이 없으면 메일의 계정 오류를 보여 줍니다.
5. 400이면 `detail`을 그대로 보여 주고 파일을 저장하지 않습니다. 견적 레코드나 드라이브 업로드는 이 API가 하지 않습니다.

## API

기본 경로는 `/api/v1/estimate`입니다.

- `POST /documents/from-instruction/json` 자연어 초안. `draft`와 미리보기 docx
- `POST /documents/json` 편집한 초안의 미리보기 docx
- `POST /documents` 편집한 초안의 docx 첨부
- `POST /documents/from-instruction` 자연어 초안의 docx 첨부. 편집 폼에는 JSON 응답을 씁니다
- `POST /documents/pdf` 편집한 초안의 PDF 첨부
- `POST /documents/pdf/json` 같은 PDF의 base64
- `POST /documents/send` 같은 초안의 PDF를 메일로 첨부

docx 성공 `Content-Type`은 `application/vnd.openxmlformats-officedocument.wordprocessingml.document`입니다. PDF는 `application/pdf`입니다. `Content-Disposition`은 `attachment`이고 파일명은 `견적서_{거래처}_{YYYY-MM-DD}.docx` 또는 `.pdf`입니다.

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

JSON 응답에는 요청에 다시 넣을 수 있는 `draft`가 있습니다. `supply_amount`, `vat`, `total`은 서버 계산값이라 다음 요청에 넣지 않습니다.

### 메일로 보내기

본문은 `draft`, `to`, `subject`, `body`, `cc`, `bcc`입니다. `draft`는 위의 구조화 작성과 같은 객체입니다. `subject`와 `body`가 비어 있으면 서버가 거래처와 합계로 채웁니다. 응답은 `sender`, `to`, `cc`, `bcc`, `subject`, `filename`입니다.

## 에러

- 400: 장비 6대 초과, 거래처·부서·담당자·품명·단가·난이도 누락, 만든 문서의 금액이 맞지 않음. 본문은 `{"detail": "..."}`입니다.
- 422: 필드 타입이 다를 때
- 502: 자연어 작성에서 언어 모델 호출 실패
- 503: 언어 모델 키가 없을 때
- 메일 발송의 400·502는 메일 API와 같습니다. 계정이 없거나 받는 사람이 없으면 400이고, SMTP 실패는 502입니다.

## 업무 대화

고정 스킬 이름은 `estimate`입니다. 도구는 `propose_create_estimate`이고 초안 `kind`는 `create_estimate`입니다. 확정 응답 `estimates`의 `draft`로 편집 폼을 열고 `docx_base64`를 미리보기로 씁니다. PDF와 메일은 이 문서의 API로 이어서 호출합니다. 견적 레코드 접수·수정은 고정 스킬 `quote`입니다. 자세한 초안 필드는 [agent_frontend.md](agent_frontend.md)에 있습니다.

## MCP

공개되는 것:

- `POST /api/v1/estimate/documents/json`
- `POST /api/v1/estimate/documents/from-instruction/json`
- `POST /api/v1/estimate/documents/pdf/json`

미리보기 응답의 `docx_base64`를 디코드하면 docx이고, PDF 응답의 `pdf_base64`를 디코드하면 PDF입니다. `draft`는 편집용입니다. `supply_amount`, `vat`, `total`은 서버 계산값입니다. 견적 레코드는 만들지 않습니다. 바이너리 다운로드와 `POST /documents/send`는 MCP에 열지 않습니다. 지시 작성은 언어 모델 호출 때문에 MCP 제한 시간을 120초로 둡니다.

## 구현 체크리스트

- 자연어 요청은 `from-instruction/json`의 `draft`와 `docx_base64`로 편집 폼과 미리보기를 연다.
- 폼을 고치면 `POST /documents/json`으로 미리보기를 다시 그린다. 다운로드 버튼은 `POST /documents/pdf`다.
- 메일 버튼은 받는 사람이 있을 때만 `POST /documents/send`를 호출한다. 계정이 없다는 오류면 메일 계정 화면으로 안내한다.
- 업무 대화 확정은 `estimates.draft`를 같은 편집 폼에 넣고, 확정 전에는 파일이 없다고 보여 준다.
- 400 `detail`을 그대로 보여 주고, 실패한 응답으로 파일을 만들지 않는다.
- 합계 입력란을 만들지 않는다. 화면 합계는 응답의 `supply_amount`, `vat`, `total`을 보여 준다.
- 장비 6대, 장비당 부품 1줄과 작업시간 1줄을 넘기면 보내기 전에 막거나 서버 400을 처리한다.

## 비범위

- 견적 레코드 생성과 드라이브 업로드
- 양식에 없는 6대 초과, 부품 2줄 이상
- 사용자가 말하지 않은 단가 추정
- 메일 계정 등록. 발송은 이미 등록된 Daum 계정을 씁니다.

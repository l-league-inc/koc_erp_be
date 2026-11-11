---
title: Daum 메일 연동
audience: frontend
---

# Daum 메일 연동

유저마다 Daum 메일 아이디와 앱 비밀번호를 등록하면 IMAP으로 메일을 읽고 SMTP로 보냅니다. 서버·포트는 고정입니다. 아이디와 앱 비밀번호만 받습니다. 앱 비밀번호는 AES로 암호화해 저장하고, API 응답에는 넣지 않습니다. 인증은 기존 JWT입니다.

호스트는 `imap.daum.net:993`(SSL), `smtp.daum.net:465`(SSL)입니다.

## 유저 플로우

1. 설정 화면에서 `GET /api/v1/mail/account`로 연결 여부를 그립니다. `configured`가 false면 등록 폼을 보여 줍니다.
2. 아이디와 앱 비밀번호를 `PUT /api/v1/mail/account`로 보냅니다. 서버가 IMAP·SMTP 연결을 확인한 뒤 저장합니다. 실패하면 400/502와 안내 문구입니다.
3. 목록은 `GET /api/v1/mail/messages`입니다. 상세는 `GET /api/v1/mail/messages/{uid}`입니다.
4. 바로 보내려면 `POST /api/v1/mail/send`입니다.
5. 연결 해제는 `DELETE /api/v1/mail/account`입니다. 204면 설정 화면을 비웁니다.
6. 업무 대화에서 메일 확인·회신을 하면 고정 스킬 `mail`이 절차를 따릅니다. 발송은 초안(`send_mail`)이고, 사용자가 확정한 뒤에만 나갑니다.

## API

기본 경로는 `/api/v1/mail`입니다.

- `GET /account` 연결 상태. 비밀번호 없음
- `PUT /account` 아이디·앱 비밀번호 저장과 연결 확인
- `DELETE /account` 연결 해제. 204
- `GET /messages` 목록. 쿼리 `folder`(기본 `INBOX`), `limit`(기본 20, 최대 50), `unread_only`
- `GET /messages/{uid}` 본문 포함. 쿼리 `folder`
- `POST /send` 즉시 발송

### 계정 등록

요청:

```json
{
  "username": "example",
  "app_password": "daum-app-password"
}
```

`username`은 Daum 로그인 아이디 또는 `@daum.net` / `@hanmail.net` 전체 주소입니다.

응답:

```json
{
  "configured": true,
  "provider": "daum",
  "username": "example",
  "username_masked": "ex***",
  "is_verified": true,
  "last_verified_at": "2026-11-11T04:00:00+00:00",
  "last_error": ""
}
```

미연결 응답은 `configured`가 false이고 `username`·`username_masked`가 빈 문자열입니다.

### 메일 목록·상세

목록 항목:

```json
{
  "uid": "12345",
  "folder": "INBOX",
  "subject": "견적 요청",
  "sender": "client@example.com",
  "date": "2026-11-11T01:00:00+00:00",
  "flags": ["unseen"],
  "snippet": "본문 앞부분"
}
```

상세는 목록 필드에 `to`, `cc`, `body`가 추가됩니다. `flags`는 `seen`, `unseen`, `flagged`입니다.

### 발송

요청:

```json
{
  "to": ["client@example.com"],
  "subject": "회신드립니다",
  "body": "확인했습니다.",
  "cc": [],
  "bcc": []
}
```

응답:

```json
{
  "sender": "example@daum.net",
  "to": ["client@example.com"],
  "cc": [],
  "bcc": [],
  "subject": "회신드립니다"
}
```

## 에이전트

고정 스킬 이름은 `mail`입니다. 도구는 `list_mails`, `get_mail`, `propose_send_mail`입니다. 발송 초안 `kind`는 `send_mail`이고 `payload`는 `to`, `subject`, `body`, 선택 `cc`·`bcc`입니다. 확정 응답에 `mails` 배열이 추가됩니다. 항목은 `action_id`, `sender`, `to`, `cc`, `bcc`, `subject`입니다. 계정이 없으면 도구가 400을 내고, 화면은 설정으로 안내하면 됩니다.

## MCP

공개되는 것:

- `GET /api/v1/mail/account`
- `GET /api/v1/mail/messages`
- `GET /api/v1/mail/messages/{uid}`
- `POST /api/v1/mail/send` (즉시 발송)

열지 않는 것:

- `PUT /account`, `DELETE /account` (앱 비밀번호 저장·삭제)

## 구현 체크리스트

- 설정 화면에 비밀번호를 다시 보여 주지 않는다. `configured`와 `username_masked`만 쓴다.
- `PUT` 실패 문구를 그대로 보여 준다.
- 업무 대화에서 `send_mail` 초안이 `pending`일 때만 확정 버튼을 띄운다. 확정 전에는 보냈다고 표시하지 않는다.
- MCP/외부 에이전트용으로 계정 등록 UI는 앱 설정에만 둔다.

## 비범위

- Gmail 등 다른 제공자
- 첨부 업로드·다운로드
- 폴더 생성·이동 UI
- 메일 HTML 정밀 렌더
- MCP로 자격증명 저장
- 워크봇 예약 발송

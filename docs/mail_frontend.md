---
title: 메일 연동
audience: frontend
---

# 메일 연동

유저마다 Daum 또는 Naver 메일 아이디와 앱 비밀번호를 등록하면 IMAP으로 메일을 읽고 SMTP로 보냅니다. 등록할 때 `provider`로 `daum` 또는 `naver`를 고릅니다. 비우면 `daum`입니다. 계정당 제공자는 하나이고, 다시 등록하면 그 제공자로 바뀝니다. 앱 비밀번호는 AES로 암호화해 저장하고, API 응답에는 넣지 않습니다. 인증은 기존 JWT입니다.

Daum은 `imap.daum.net:993`(SSL), `smtp.daum.net:465`(SSL)입니다. Naver는 `imap.naver.com:993`(SSL), `smtp.naver.com:587`(TLS)입니다. Naver에서 TLS를 쓸 수 없으면 `smtp.naver.com:465`(SSL)로 연결합니다.

## 유저 플로우

1. 설정 화면에서 `GET /api/v1/mail/account`로 연결 여부를 그립니다. `configured`가 false면 등록 폼을 보여 줍니다.
2. 제공자, 아이디, 앱 비밀번호를 `PUT /api/v1/mail/account`로 보냅니다. 서버가 IMAP·SMTP 연결을 확인한 뒤 저장합니다. 실패하면 400/502와 안내 문구입니다.
3. 목록은 `GET /api/v1/mail/messages`입니다. 상세는 `GET /api/v1/mail/messages/{uid}`입니다.
4. 바로 보내려면 `POST /api/v1/mail/send`입니다.
5. 연결 해제는 `DELETE /api/v1/mail/account`입니다. 204면 설정 화면을 비웁니다.
6. 업무 대화에서 메일 확인·회신을 하면 고정 스킬 `mail`이 절차를 따릅니다. 발송은 초안(`send_mail`)이고, 사용자가 확정한 뒤에만 나갑니다.
7. 서버가 약 60초마다 받은편지함의 새 메일을 확인합니다. 도착하면 기존 알림으로 옵니다. 제목과 앞부분으로 중요도를 `urgent`(긴급), `normal`(보통), `low`(낮음)으로 나눕니다. 알림 문구는 `[긴급] 제목 · 보낸 사람`처럼 중요도 한글이 앞에 붙습니다.
8. 계정 응답의 `notify_importances`가 받을 범위입니다. 기본은 셋 다입니다. 긴급과 보통만 받으려면 `PUT /api/v1/mail/account/notify`에 `["urgent", "normal"]`을 보냅니다. 범위를 벗어난 메일은 알림을 만들지 않고 받은 것으로 처리합니다.

## API

기본 경로는 `/api/v1/mail`입니다.

- `GET /account` 연결 상태. 비밀번호 없음. `notify_importances` 포함
- `PUT /account` 제공자·아이디·앱 비밀번호 저장과 연결 확인. `provider`는 `daum` 또는 `naver`
- `PUT /account/notify` 알림 수신 범위. `importances`는 `urgent`, `normal`, `low`
- `DELETE /account` 연결 해제. 204
- `GET /messages` 목록. 쿼리 `folder`(기본 `INBOX`), `limit`(기본 20, 최대 50), `unread_only`
- `GET /messages/{uid}` 본문 포함. 쿼리 `folder`
- `POST /send` 즉시 발송

### 계정 등록

요청:

```json
{
  "provider": "naver",
  "username": "example",
  "app_password": "app-password"
}
```

`provider`를 빼면 `daum`입니다. `gmail`처럼 모르는 값은 400입니다. `username`은 로그인 아이디 또는 전체 주소입니다. Daum은 `@daum.net` / `@hanmail.net`, Naver는 `@naver.com`입니다. 아이디만 있으면 발신 주소는 Daum `@daum.net`, Naver `@naver.com`입니다.

응답:

```json
{
  "configured": true,
  "provider": "naver",
  "username": "example",
  "username_masked": "ex***",
  "is_verified": true,
  "last_verified_at": "2026-11-11T04:00:00+00:00",
  "last_error": "",
  "notify_importances": ["urgent", "normal", "low"]
}
```

미연결 응답은 `configured`가 false이고 `username`·`username_masked`가 빈 문자열입니다. `notify_importances`는 기본값 세 개입니다.

### 도착 알림

받은편지함을 약 60초마다 확인합니다. 계정을 처음 연결한 뒤 첫 확인은 그때까지의 메일을 알리지 않고 위치만 기억합니다. 그 다음에 도착한 메일만 알립니다.

중요도는 제목과 본문 앞부분입니다.

- `urgent`: 긴급, 오늘 마감, 장애, 서버 다운, 클레임, 계약 해지, 미수, 연체, 독촉처럼 바로 볼 일
- `low`: noreply, 뉴스레터, 수신거부, 광고메일, 프로모션
- `normal`: 그 외 업무 메일. 견적, 회신, 회의가 여기 있습니다

알림 목록 API와 함께, 로그인 사용자는 알림 소켓으로 같은 건을 바로 받습니다.

연결은 `wss://{API호스트}/ws/notification/{user_id}/`입니다. 페이지가 `http`이면 `ws`입니다. `{user_id}`는 로그인한 사용자 id이고, 다른 사용자 id면 서버가 연결을 닫습니다. 인증은 워크스페이스 소켓과 같이 쿠키 `access`입니다. `Authorization` 헤더는 보지 않습니다.

연결되면 `user_connected`가 한 번 옵니다. 그 다음 새 메일은 `new_notification`입니다. `notification`은 알림 목록 항목과 같고, 목록을 다시 조회하지 않고 그대로 붙이면 됩니다. 누르면 `metadata.uid`로 `GET /messages/{uid}`를 엽니다.

```json
{
  "type": "new_notification",
  "has_unread": true,
  "notification": {
    "id": 40,
    "message": "[긴급] 오늘 마감 견적 · client@example.com",
    "is_read": false,
    "created_at": "2026-11-26T15:40:00",
    "metadata": {
      "kind": "mail",
      "importance": "urgent",
      "uid": "12345",
      "folder": "INBOX",
      "subject": "오늘 마감 견적",
      "sender": "client@example.com"
    }
  }
}
```

`metadata`만 보면 아래와 같습니다.

```json
{
  "kind": "mail",
  "importance": "urgent",
  "uid": "12345",
  "folder": "INBOX",
  "subject": "오늘 마감 견적",
  "sender": "client@example.com"
}
```

수신 범위 변경:

```json
{ "importances": ["urgent", "normal"] }
```

모르는 값이나 빈 배열은 400입니다. 고른 순서대로 저장됩니다.

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
  "sender": "example@naver.com",
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

- `PUT /account`, `PUT /account/notify`, `DELETE /account` (앱 비밀번호와 수신 범위 변경)

## 구현 체크리스트

- 설정 화면에 `daum`과 `naver` 중 하나를 고르게 한다. 응답 `provider`로 현재 연결을 표시한다.
- 설정 화면에 비밀번호를 다시 보여 주지 않는다. `configured`와 `username_masked`만 쓴다.
- `PUT` 실패 문구를 그대로 보여 준다.
- 업무 대화에서 `send_mail` 초안이 `pending`일 때만 확정 버튼을 띄운다. 확정 전에는 보냈다고 표시하지 않는다.
- MCP/외부 에이전트용으로 계정 등록 UI는 앱 설정에만 둔다.
- 로그인 후 `ws/notification/{user_id}/`를 연다. `new_notification`의 `notification.metadata.kind`가 `mail`이면 토스트를 띄우고, `importance`를 뱃지로 보여주고 `uid`로 메일 상세를 연다.
- 소켓이 끊기면 다시 연결하고, 그 사이 알림은 목록 API로 맞춘다.
- 수신 범위는 `notify_importances`로 그리고, 저장은 `PUT /account/notify`만 쓴다.

## 비범위

- Gmail 등 Daum·Naver 외 제공자
- 첨부 업로드·다운로드
- 폴더 생성·이동 UI
- 메일 HTML 정밀 렌더
- MCP로 자격증명 저장
- 워크봇 예약 발송
- 받은편지함 외 폴더의 도착 알림
- 메일 서버의 즉시 푸시. 확인 주기는 약 60초입니다.

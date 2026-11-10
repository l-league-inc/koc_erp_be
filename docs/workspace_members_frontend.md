---
title: 유저 등록과 워크스페이스 멤버 관리
audience: frontend
---

# 유저 등록과 워크스페이스 멤버 관리

워크스페이스 유저는 관리자가 직접 등록합니다. 순서는 계정 만들기, 워크스페이스에 넣기입니다. 두 API는 모두 JWT 인증이고, 호출자는 시스템 관리자(`permission_type=admin`)이거나 워크스페이스 `owner`/`admin`이어야 합니다.

## 유저 플로우

1. 관리자 화면의 「유저 등록」에서 이름, 이메일, 비밀번호(전화번호는 선택)를 받아 `POST /api/v1/auth/admin-signup`을 부릅니다.
2. 응답의 `id`로 `POST /api/v1/workspace/{workspace_id}/member`를 불러 워크스페이스에 넣습니다. 이미 가입한 사람은 1번 없이 이메일만으로 넣을 수 있습니다.
3. 멤버 관리 화면은 `GET /api/v1/workspace/{workspace_id}/member/manage`로 그립니다.
4. 역할 변경은 `PATCH`, 내보내기는 `DELETE`입니다. 내보내도 계정은 남고, 같은 사람을 다시 넣을 수 있습니다.

## 유저 등록 `POST /api/v1/auth/admin-signup`

전화번호 인증 해시(`phone_hash`)는 받지 않습니다. 기존 공개 `POST /signup`은 그대로입니다.

```json
{
  "email": "newbie@example.com",
  "password": "password1234!",
  "password2": "password1234!",
  "name": "신입",
  "phone_number": "01055556666"
}
```

- `name`은 필수, 30자 이하입니다. `phone_number`는 선택이고 숫자만 10~12자리입니다.
- 비밀번호는 8자 이상, 소문자와 숫자를 하나 이상 포함해야 합니다. `password2`가 다르면 400입니다.
- 만들어진 계정은 이메일 인증 없이 바로 활성(`status=A`)이고 일반 회원(`customer`)입니다. 시스템 관리자 권한은 이 API로 줄 수 없습니다.
- 응답 201은 `{id, email, name, phone_number, status, type, ...}`입니다.
- 400: 이미 쓰는 이메일 또는 전화번호, 형식 오류. 401: 로그인 안 함. 403: 관리자/소유자가 아님.

## 멤버 API

경로는 `api/v1/workspace` 기준입니다.

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/{workspace_id}/member/manage` | 멤버 관리 목록. owner/admin만 |
| POST | `/{workspace_id}/member` | 멤버 등록 |
| PATCH | `/{workspace_id}/member/{user_id}` | 역할 변경 |
| DELETE | `/{workspace_id}/member/{user_id}` | 멤버 내보내기. 204 |

기존 `GET /{workspace_id}/member`(user_id, name, role)는 담당자 선택용으로 모든 멤버가 쓰고, 이메일과 전화번호는 없습니다.

관리 목록 응답 항목:

```json
{
  "user_id": 7,
  "name": "신입",
  "email": "newbie@example.com",
  "phone_number": "01055556666",
  "user_status": "A",
  "role": "member",
  "joined_at": "2026-11-10T16:00:00"
}
```

등록 본문은 `user_id`와 `email` 중 정확히 하나, 그리고 선택 `role`(기본 `member`)입니다.

```json
{"email": "newbie@example.com", "role": "member"}
```

역할 변경 본문은 `{"role": "admin"}`입니다. 응답은 관리 목록 항목과 같습니다.

## 권한 규칙

| 하는 일 | owner | admin | member |
|---------|-------|-------|--------|
| 목록, 등록, 내보내기 (`member` 역할 대상) | 가능 | 가능 | 403 |
| `admin`/`owner` 역할 주기, 그 역할 가진 사람의 역할 변경·내보내기 | 가능 | 403 | 403 |

- 마지막 `owner`는 역할을 낮추거나 내보낼 수 없습니다(400). 먼저 다른 사람을 owner로 올립니다.
- 이미 멤버면 400, 없는 유저나 탈퇴한 유저는 404, 멤버가 아닌 사람 변경·삭제는 404입니다. 역할 값이 틀리면 400입니다.
- 내보내진 사람은 그 워크스페이스 API가 403이 됩니다.
- 이 변경은 WebSocket 이벤트를 보내지 않습니다. 목록은 화면에서 다시 조회합니다.

## 구현 체크리스트

- 유저 등록 폼에 전화번호 인증 단계를 넣지 않는다.
- 403이면 「등록 권한이 없습니다」를 보이고, `admin`은 역할 선택에서 `admin`/`owner`를 숨긴다.
- 등록 직후 멤버 관리 목록을 다시 조회한다.
- 마지막 owner의 변경·내보내기 버튼은 비활성으로 둔다.

## 비범위

- 임시 비밀번호 메일 발송, 초대 링크, 일괄 등록(CSV)
- 계정 정지·탈퇴 처리(`PATCH /api/v1/auth/{user_id}`는 시스템 관리자 전용으로 유지)
- 공개 회원가입 `POST /api/v1/auth/signup`의 폐쇄

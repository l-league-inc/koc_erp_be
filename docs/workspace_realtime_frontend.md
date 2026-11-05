---
title: 워크스페이스 변경 알림
audience: frontend
---

# 워크스페이스 변경 알림

워크스페이스를 다른 화면과 같이 볼 때 쓰는 WebSocket입니다. 저장은 기존 REST이고, 이 소켓은 커밋된 뒤에 「무엇이 바뀌었는지」만 알립니다. 블록 내용과 커서는 오지 않습니다. 열린 문서의 블록과 커서는 [workspace_collab_frontend.md](workspace_collab_frontend.md)입니다. 데이터 계약은 [workspace_frontend.md](workspace_frontend.md), 페이지 트리는 [workspace_page_frontend.md](workspace_page_frontend.md)입니다.

## 유저 플로우

1. 워크스페이스 화면에 들어가면 `wss://{API호스트}/ws/workspace/{workspace_id}/`에 연결합니다. 페이지가 `http`이면 `ws`입니다. 호스트는 REST와 같습니다.
2. 브라우저는 로그인 때 받은 `access` 쿠키를 그대로 보냅니다. 쿠키는 `HttpOnly`라 자바스크립트로 읽어 쿼리에 붙이지 않습니다.
3. 연결이 수락되면 서버는 인사 메시지를 보내지 않습니다. 열린 화면은 기존 GET으로 그립니다.
4. 누군가 저장하면 `workspace_changed`가 옵니다. 그 `entity`와 `id`만 다시 조회해 열린 표, 페이지, 사이드바를 고칩니다.
5. 워크스페이스를 바꾸면 소켓을 닫고 새 `workspace_id`로 다시 연결합니다. 한 연결은 그 워크스페이스 멤버에게 가는 변경만 받습니다.
6. 연결이 끊기면 잠시 뒤 다시 연결하고, 지금 보고 있는 화면을 한 번 다시 조회합니다. 끊긴 동안의 이벤트는 다시 보내 주지 않습니다.

## 연결

경로: `/ws/workspace/{workspace_id}/`

인증은 쿠키 `access`입니다. REST에 쓰는 `Authorization` 헤더는 이 연결에서 보지 않습니다. 멤버가 아니거나 쿠키가 없거나 만료되면 서버가 연결을 바로 닫습니다. 닫기 전에 오류 JSON은 오지 않습니다.

클라이언트가 보내는 메시지는 무시됩니다. 구독, 읽음, 핑을 이 소켓으로 보내지 않습니다. 알림 배지는 `ws/notification/{user_id}/`이고 이 문서의 대상이 아닙니다.

## 페이로드

텍스트 프레임 하나입니다.

```json
{
  "type": "workspace_changed",
  "workspace_id": 1,
  "entity": "record",
  "action": "updated",
  "id": 12,
  "actor_id": 3
}
```

| 필드 | 의미 |
|------|------|
| `type` | 항상 `workspace_changed` |
| `workspace_id` | 연결한 워크스페이스 id |
| `entity` | 바뀐 대상. 아래 표 |
| `action` | `created`, `updated`, `deleted`, `restored` 중 실제로 발생한 값 |
| `id` | 그 대상의 id. 본문, 제목, 속성 값은 없습니다 |
| `actor_id` | 저장한 사용자 id. 없으면 `null` |

저장한 사람의 화면에도 같은 이벤트가 옵니다. 방금 성공한 요청과 같은 변경이면 무시해도 되고, 그 사용자의 다른 탭은 이 이벤트로 맞춥니다. 같은 저장에서 이벤트가 둘 이상 올 수 있습니다. 데이터베이스를 만들면 `database` `created`와 `page` `created`가 이어집니다. 양방향 관계를 만들면 `property` `created`가 양쪽 id로 한 번씩 옵니다.

| entity | action | 다시 조회 |
|--------|--------|-----------|
| `record` | `created`, `updated`, `restored` | 열린 상세는 `GET /api/v1/workspace/record/{id}`. 그 데이터베이스 표가 열려 있으면 `POST /query` |
| `record` | `deleted` | 표에서 빼고, 그 상세가 열려 있으면 닫습니다. 휴지통이 열려 있으면 `GET /{workspace_id}/trash` |
| `block` | `created`, `updated`, `deleted` | 열린 레코드나 문서의 블록 목록. 레코드는 `GET /record/{id}`, 문서는 `GET /page/{id}` |
| `comment` | `created`, `deleted` | 열린 레코드의 `GET /record/{id}/comment` |
| `database` | `created`, `updated`, `deleted` | `GET /database`와, 열려 있으면 `GET /database/{id}`. `deleted`일 때 속한 레코드마다 `record` `deleted`는 오지 않습니다 |
| `property` | `created`, `updated`, `deleted` | 그 데이터베이스 `GET /database/{id}`의 `properties`. `id`는 속성 id입니다 |
| `view` | `created`, `updated`, `deleted` | 그 데이터베이스 상세의 `views`. 열린 보기가 지워졌으면 다른 보기로 옮깁니다 |
| `page` | `created`, `updated`, `deleted`, `restored` | `GET /{workspace_id}/page`. 열린 문서면 `GET /page/{id}` |
| `template` | `created`, `updated`, `deleted` | `GET /database/{id}/template`. 이벤트 `id`는 템플릿 id입니다 |

`block`과 `comment`, `property`, `view`, `template`의 `id`는 부모 레코드나 데이터베이스 id가 아닙니다. 부모가 필요하면 이미 열어 둔 화면의 id로 다시 조회합니다. 그 화면이 아니면 이벤트를 버려도 됩니다.

즐겨찾기 추가와 해제는 이벤트가 없습니다. 그 사용자의 `GET /{workspace_id}/favorite`만 갱신하면 됩니다.

레코드 저장에 `blocks`가 포함되면 `block` 이벤트 없이 `record` `updated`만 옵니다. 상세 `GET /record/{id}`에 블록이 들어 있습니다. 양방향 관계로 반대편 레코드의 링크가 바뀌어도 그 레코드 id의 `record` 이벤트는 오지 않습니다. 반대편 상세는 다시 열 때 GET으로 맞춥니다.

경로는 `api/v1/workspace` 기준입니다.

## 구현 체크리스트

- 소켓 URL의 호스트는 REST API와 같고, 경로는 `/ws/workspace/{workspace_id}/`이다.
- `new WebSocket`에 토큰 쿼리나 `Authorization`을 붙이지 않는다. 같은 사이트 쿠키가 전송되는 연결이어야 한다.
- 연결 직후 인사 메시지를 기다리지 않고, 지금 화면은 REST로 그린다.
- `workspace_changed`를 받으면 표의 페이로드를 합치지 말고 위 표의 GET을 다시 호출한다.
- 같은 `entity`와 `id`가 연속되면 한 번만 조회하도록 짧게 모은다.
- 저장한 탭이 이미 응답을 그렸다면 그 요청과 같은 이벤트는 건너뛰어도 된다. 다른 탭은 건너뛰지 않는다.
- 워크스페이스를 떠나거나 화면을 닫으면 소켓을 `close`한다.
- 끊기면 재연결하고, 재연결 뒤 열린 화면을 한 번 다시 조회한다.
- 알림 소켓과 이 소켓을 한 연결로 합치지 않는다.

## 비범위

- AppFlowy `/ws/v2` 바이너리 프로토콜과 글자 단위 CRDT. 문서방 JSON은 [workspace_collab_frontend.md](workspace_collab_frontend.md)입니다
- 서버가 놓친 이벤트를 이어서 보내 주는 것
- 클라이언트가 소켓으로 저장하거나 구독 대상을 고르는 것
- 워크스페이스 멤버 변경, 즐겨찾기, 워크스페이스 이름 수정의 알림
- 페이지별 권한. 멤버이면 그 워크스페이스의 변경을 모두 받는다

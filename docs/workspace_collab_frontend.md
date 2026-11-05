---
title: 문서방 공동 편집
audience: frontend
---

# 문서방 공동 편집

레코드나 문서 페이지를 같이 편집할 때 쓰는 WebSocket입니다. AppFlowy-Cloud가 문서 동기화와 커서 알림을 나누는 방식을 따릅니다. 저장 본문은 블록 JSON이고, Yrs 바이너리 프로토콜은 쓰지 않습니다. 블록 모양은 [workspace_page_frontend.md](workspace_page_frontend.md)이고, 워크스페이스 전체 알림은 [workspace_realtime_frontend.md](workspace_realtime_frontend.md)입니다.

같은 블록을 두 사람이 동시에 고치면 나중에 저장된 내용이 남습니다. 글자 단위로 합치지 않습니다.

## 유저 플로우

1. 문서를 열면 `wss://{API호스트}/ws/workspace/{workspace_id}/collab/{target}/{id}/`에 연결합니다. `target`은 레코드면 `record`, 문서 페이지면 `page`입니다.
2. 인증은 워크스페이스 소켓과 같습니다. 쿠키 `access`만 보고, `Authorization`은 보지 않습니다.
3. 연결이 되면 `sync`로 블록 목록이 오고, 이어서 `presence`로 방에 있는 사람이 옵니다.
4. 선택 영역이 바뀌면 `awareness`를 보냅니다. 다른 사람의 커서는 `awareness`로 옵니다.
5. 블록을 저장하면 REST를 써도 되고, 이 소켓으로 `op`를 보내도 됩니다. 커밋되면 방 전체에 `collab`이 옵니다.
6. 20초마다 `ping`을 보냅니다. 45초 동안 메시지가 없는 접속은 목록에서 빠집니다.
7. 화면을 닫으면 소켓을 `close`합니다. 방을 나간 사람의 커서는 `presence`에서 빠집니다.

멤버가 아니거나, 대상이 없거나, `page`가 문서가 아니면 서버가 연결을 닫습니다. 오류 JSON은 오지 않습니다.

## 서버가 보내는 메시지

`sync`는 연결한 소켓에만 옵니다. 블록은 `position`, `id` 순의 평탄 목록입니다.

```json
{"type": "sync", "target": "record", "target_id": 12, "blocks": []}
```

`presence`는 방 전체 목록입니다. 같은 사용자의 탭이 둘이면 항목이 둘입니다.

```json
{
  "type": "presence",
  "users": [
    {
      "presence_id": "a1b2c3d4e5f6",
      "user_id": 3,
      "name": "박승원",
      "cursor": {"block_id": 9, "offset": 2},
      "selection": null
    }
  ]
}
```

`awareness`는 커서가 바뀐 한 명입니다. 보낸 소켓에는 다시 오지 않습니다.

```json
{
  "type": "awareness",
  "presence_id": "a1b2c3d4e5f6",
  "user_id": 3,
  "name": "박승원",
  "cursor": {"block_id": 9, "offset": 4},
  "selection": {
    "anchor": {"block_id": 9, "offset": 0},
    "focus": {"block_id": 9, "offset": 4}
  }
}
```

`collab`은 커밋된 블록입니다. REST로 저장해도 같은 메시지가 옵니다. 저장한 소켓에도 옵니다.

```json
{
  "type": "collab",
  "action": "created",
  "actor_id": 3,
  "block_id": 9,
  "block": {
    "id": 9,
    "record_id": 12,
    "page_id": null,
    "parent_id": null,
    "type": "paragraph",
    "content": {"text": "같이"},
    "position": 0,
    "created_at": "2026-11-05T12:00:00",
    "updated_at": "2026-11-05T12:00:00"
  }
}
```

`action`이 `updated`이면 `block`이 바뀐 블록입니다. `deleted`이면 `block`은 `null`이고, 그 블록의 자식도 함께 지워집니다. `reload`이면 `block_id`와 `block`이 `null`입니다. 레코드 수정 본문에 `blocks`를 넣어 본문을 통째로 바꾼 경우이므로 `GET /record/{id}`로 다시 그립니다.

`error`는 그 소켓의 `op`나 형식이 거절된 것입니다. 연결은 유지됩니다.

```json
{"type": "error", "detail": "표 행은 표 블록 아래에만 둘 수 있습니다."}
```

`pong`은 `ping`의 응답입니다.

## 클라이언트가 보내는 메시지

커서입니다. `cursor`와 `selection`은 `null`일 수 있습니다. `offset`은 0 이상의 정수입니다.

```json
{
  "type": "awareness",
  "cursor": {"block_id": 9, "offset": 4},
  "selection": null
}
```

블록을 만듭니다. `block`은 REST `POST /block` 본문과 같습니다.

```json
{
  "type": "op",
  "action": "create",
  "block": {"type": "paragraph", "content": {"text": "같이"}, "position": 0, "parent_id": null}
}
```

블록을 고칩니다. `block`에 있는 키만 바꿉니다. `parent_id`를 `null`로 두면 루트로 올립니다.

```json
{"type": "op", "action": "update", "block_id": 9, "block": {"content": {"text": "고침"}}}
```

블록을 지웁니다.

```json
{"type": "op", "action": "delete", "block_id": 9}
```

접속을 유지합니다.

```json
{"type": "ping"}
```

## 구현 체크리스트

- 편집 화면은 문서방 소켓을 연다. 워크스페이스 소켓의 `block` 이벤트와 문서방 `collab`이 같은 저장에서 둘 다 올 수 있다. 문서방을 쓰는 화면은 `collab`만 반영한다.
- `sync`의 블록으로 본문을 그린다. 제목, 속성, 아이콘은 기존 GET을 쓴다.
- `created`와 `updated`는 `block`으로 그 칸만 바꾼다. `deleted`는 그 id와 자식을 뺀다. `reload`는 레코드 상세를 다시 조회한다.
- 방금 보낸 `op`의 `collab`이 자기 `actor_id`로 다시 오면, 이미 화면에 반영했다면 건너뛴다. 다른 탭은 건너뛰지 않는다.
- 커서 이동마다 `awareness`를 보내고, 20초마다 `ping`을 보낸다.
- 표 행, 표 칸, 단은 부모 없이 만들지 않는다.
- 워크스페이스를 떠나거나 문서를 닫으면 소켓을 `close`한다.

## 비범위

- AppFlowy `/ws/v2` 바이너리 메시지, Yrs 상태, 글자 단위 병합
- 끊긴 동안의 조작을 이어 주는 것
- 워크스페이스 멤버가 아닌 게스트 편집
- 서버가 북마크 URL을 열어 제목과 설명을 채우는 것

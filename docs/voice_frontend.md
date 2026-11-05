---
title: 음성 등록
audience: frontend
---

# 음성 등록

음성 샘플은 비공개 S3에 있습니다. 화면은 파일 바이트를 API 서버로 보내지 않습니다. 올릴 때와 재생할 때 모두 짧은 presigned URL을 쓰고, 그 주소는 저장하지 않습니다. 서버가 보관하는 값은 객체 키입니다. 인증은 기존 JWT이고, 헤더는 `Authorization: Bearer {access}`입니다.

이미지 업로드 `POST /api/v1/aws/upload`, `POST /api/v1/aws/upload-new`, `POST /api/v1/aws/directupload`와 문서함 업로드는 쓰지 않습니다. 그 API는 경로와 응답이 다릅니다.

## 유저 플로우

1. 녹음이나 파일 선택 뒤 `POST /api/v1/storybook/voice/upload`로 업로드 URL을 받습니다.
2. 응답 `upload_url`에 파일 바이트를 PUT합니다. 헤더 `Content-Type`은 응답 `content_type`과 같아야 합니다. 이 요청에는 `Authorization`을 넣지 않습니다.
3. S3가 200을 주면 `POST /api/v1/storybook/voice`로 음성을 등록합니다. 파일 대신 업로드 응답의 `object_key`를 그대로 넣습니다.
4. 목록은 `GET /api/v1/storybook/voice`입니다. 항목에는 재생 주소가 없습니다.
5. 재생 버튼을 누르면 `GET /api/v1/storybook/voice/{voice_id}/url`의 `url`을 `<audio>`의 `src`로 넣습니다.
6. `expires_in`이 지나거나 재생이 실패하면 5번을 다시 호출합니다. 이전에 받은 주소는 버립니다.

## API

기본 경로는 `/api/v1/storybook`입니다.

- `POST /voice/upload` 업로드 URL 발급
- `POST /voice` 음성 등록. 201
- `GET /voice` 내 음성 목록
- `GET /voice/{voice_id}/url` 재생 URL 발급

### 업로드 URL

요청:

```json
{
  "file_name": "sample.webm",
  "content_type": "audio/webm",
  "size": 240112
}
```

응답:

```json
{
  "upload_url": "https://s3.amazonaws.com/...",
  "object_key": "koc erp/voices/main/15/ab12cd.webm",
  "content_type": "audio/webm",
  "expires_in": 300
}
```

`object_key`는 서버가 만든 값입니다. 화면에서 경로를 조합하지 않고, 등록 요청에 같은 문자열을 넣습니다. `upload_url`은 300초 뒤 만료됩니다.

PUT 예:

```http
PUT {upload_url}
Content-Type: audio/webm

{파일 바이트}
```

본문은 `multipart/form-data`가 아닙니다. S3 응답이 200이면 업로드가 끝난 것입니다.

허용 `content_type`은 `audio/webm`, `audio/wav`, `audio/x-wav`, `audio/mpeg`, `audio/mp4`입니다. `size`는 1바이트 이상 50MB 이하입니다. 브라우저 녹음의 타입은 보통 `audio/webm`입니다.

### 음성 등록

요청:

```json
{
  "name": "안내 음성",
  "ref_text": "안녕하세요. 케이오씨입니다.",
  "object_key": "koc erp/voices/main/15/ab12cd.webm",
  "content_type": "audio/webm",
  "size": 240112
}
```

`name`은 화면에 보일 이름입니다. `ref_text`는 그 녹음에서 읽은 문장입니다. `content_type`과 `size`는 업로드 요청에 보낸 값과 같아야 합니다.

응답 201:

```json
{
  "id": 1,
  "name": "안내 음성",
  "ref_text": "안녕하세요. 케이오씨입니다.",
  "content_type": "audio/webm",
  "size": 240112,
  "created_at": "2026-11-05T10:00:00"
}
```

이 응답과 목록 항목에는 `url`, `upload_url`, CloudFront 주소가 없습니다.

### 목록

`GET /voice` 항목은 등록 응답과 같은 필드입니다. 최신 등록이 앞에 옵니다. 다른 사용자의 음성은 나오지 않습니다.

### 재생 URL

`GET /voice/{voice_id}/url` 응답:

```json
{
  "url": "https://s3.amazonaws.com/...",
  "expires_in": 300
}
```

이 주소는 비공개 객체를 잠시 읽을 수 있는 presigned GET입니다. `<audio src>`에 넣고, 다운로드로 저장하지 않습니다. 300초가 지나면 S3가 거절하므로 재생 직전에 다시 발급합니다. 목록을 새로고침할 때 미리 받아 두지 않습니다.

## 오류

본문은 `{"detail": "메시지"}`입니다.

- 401: 토큰이 없거나 만료됨
- 400: 허용하지 않는 콘텐츠 타입, 1바이트 미만이거나 50MB를 넘는 크기, 빈 이름, 빈 대사, 업로드 응답과 다른 `object_key`, S3에 아직 없는 객체
- 404: 내 음성이 아닌 id
- 502: presigned URL을 만들지 못함

S3 PUT이 200이 아니면 등록 API를 호출하지 않습니다. 만료된 `upload_url`이면 업로드 URL 발급부터 다시 합니다.

## 구현 체크리스트

- 녹음 파일의 MIME을 확인해 허용 타입이 아니면 업로드 URL을 요청하지 않습니다.
- 순서는 업로드 URL 발급, S3 PUT, 음성 등록입니다. 등록 요청에는 파일을 붙이지 않습니다.
- PUT 헤더 `Content-Type`은 업로드 응답의 `content_type`과 같습니다.
- `upload_url`과 재생 `url`은 메모리에만 두고, 로컬 저장소나 서버 상태에 남기지 않습니다.
- 재생은 버튼을 누를 때 `GET /voice/{voice_id}/url`을 호출합니다. 실패하거나 `expires_in`이 지나면 같은 API를 다시 호출합니다.
- 이미지 업로드 API와 문서함 업로드 API를 음성에 재사용하지 않습니다.

## 비범위

- CloudFront 주소를 DB나 화면에 저장
- API 서버로 파일 바이트를 보내는 멀티파트 등록
- 음성 수정, 삭제, 합성
- 문서함 파일 API로 음성 샘플 관리

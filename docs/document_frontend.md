---
title: 회사 문서함
audience: frontend
---

# 회사 문서함

워크스페이스 멤버가 공유 문서함과 개인 문서함을 폴더로 관리합니다. 파일 바이트는 비공개 S3에 있고, 화면은 이 API의 메타데이터만 사용합니다. 인증은 기존 JWT입니다.

## 유저 플로우

1. `GET /api/v1/document/{workspace_id}/space`로 공유 문서함과 내 개인 문서함을 가져옵니다. 없으면 서버가 만듭니다.
2. 각 공간의 `root_folder_id`를 루트로 두고, `GET /api/v1/document/{workspace_id}/folder?space_id=&parent_id=`로 하위 폴더를 그립니다. `parent_id`를 비우면 루트의 자식입니다.
3. 폴더 안 파일은 `GET /api/v1/document/{workspace_id}/file?folder_id=`입니다.
4. 업로드는 `POST .../upload`로 URL을 받은 뒤, 그 URL에 PUT하고 `POST .../file`로 등록합니다. PUT 헤더 `Content-Type`은 응답의 `content_type`과 같아야 합니다.
5. 다운로드는 `POST .../file/{file_id}/download`의 `url`로 받습니다. 이 호출이 다운로드 이력을 남깁니다.
6. 검색은 `GET .../file/search?q=`이고, 본문은 `GET .../file/{file_id}`의 `extracted_text`입니다.
7. 메일 발송 이력은 `GET .../file/{file_id}/mail`입니다. 발송 API는 아직 없습니다.

개인 문서함은 소유자에게만 보입니다. 다른 멤버와 워크스페이스 관리자에게도 404입니다. 폴더와 파일은 같은 문서함 안에서만 옮길 수 있습니다.

## API

기본 경로는 `/api/v1/document/{workspace_id}`입니다.

- `GET /space` 공유 공간과 내 개인 공간. 항목은 `id`, `workspace_id`, `kind`(`shared`/`personal`), `owner_id`, `root_folder_id`
- `GET /folder?space_id=&parent_id=` 하위 폴더
- `POST /folder` `{parent_id, name}` 생성. 201
- `PATCH /folder/{folder_id}` `{name?, parent_id?}` 이름 변경 또는 같은 공간 이동
- `DELETE /folder/{folder_id}` 빈 폴더 삭제. 204
- `POST /upload` `{folder_id, file_name, content_type, size}` → `upload_url`, `object_key`, `content_type`, `expires_in`
- `POST /file` `{folder_id, object_key, original_filename, content_type, size}` 등록. 201
- `GET /file?folder_id=` 폴더 안 파일
- `GET /file/search?q=` 검색 결과
- `GET /file/{file_id}` 상세. `extracted_text`, `error` 포함
- `PATCH /file/{file_id}` `{folder_id}` 같은 문서함으로 이동
- `DELETE /file/{file_id}` 소프트 삭제. 204. S3 객체는 지우지 않습니다
- `POST /file/{file_id}/download` `{url, expires_in}`
- `POST /file/{file_id}/reindex` 올린 사람만. 상세와 같은 응답
- `GET /file/{file_id}/mail` 발송 이력

파일 항목은 `id`, `workspace_id`, `space_id`, `space_kind`, `folder_id`, `original_filename`, `content_type`, `size`, `uploaded_by_id`, `path`, `index_status`, `index_source`, `description_ko`, `tags_ko`, `created_at`, `updated_at`입니다. 상세만 `extracted_text`, `error`가 있습니다.

`index_status`는 `pending`, `processing`, `ready`, `failed`, `skipped`입니다. `index_source`는 `local` 또는 `llm`입니다. 공유 문서는 요약에 언어 모델을 쓰고, 개인 문서는 본문 추출만 합니다. PDF, DOCX, txt, md, csv만 추출합니다.

검색 항목은 `id`, `original_filename`, `folder_id`, `folder_path`, `description_ko`, `score`입니다. 공유 문서와 내 개인 문서만 나옵니다.

업로드 URL과 다운로드 URL은 300초 뒤 만료됩니다. 파일 크기는 1바이트 이상 50MB 이하입니다. `object_key`는 업로드 응답 값을 그대로 등록 API에 넣습니다.

메일 이력 항목은 `id`, `file_id`, `sender_id`, `recipients`, `subject`, `status`(`pending`/`sent`/`failed`), `sent_at`, `error`, `created_at`입니다.

없는 워크스페이스는 404, 비멤버는 403입니다. 다른 사람의 개인 문서함·폴더·파일은 404입니다. 같은 이름 폴더, 빈 이름이 아닌 잘못된 이름, 다른 문서함으로의 이동, 비어 있지 않은 폴더 삭제는 400입니다. 올린 사람이 아닌 멤버의 삭제는 403이고, 소유자와 관리자는 공유 문서를 지울 수 있습니다.

## 구현 체크리스트

- 문서함 진입 시 `space`를 먼저 호출하고, 공유와 개인을 `kind`로 나눕니다.
- 폴더 트리는 `root_folder_id`와 `parent_id`로 펼칩니다. 루트 폴더는 목록에 다시 그리지 않습니다.
- 업로드는 URL 발급, PUT, 등록 순서입니다. 등록 응답의 `index_status`가 `pending`이면 색인 중입니다.
- 다운로드 버튼은 `download` POST를 호출한 뒤 받은 URL로 이동합니다.
- 검색 결과에서 상세로 들어가면 `extracted_text`를 미리보기로 씁니다.
- 메일 이력 화면은 목록 API만 붙이고, 보내기 버튼은 두지 않습니다.

## 비범위

- 메일 첨부 발송
- 개인 문서를 공유 문서함으로 옮기기
- 폴더별 추가 공유 대상
- hwp, 이미지 설명, 음성 전사
- 기존 `company_docs` Google Drive 링크 데이터베이스 교체

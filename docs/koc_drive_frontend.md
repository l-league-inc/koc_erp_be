---
title: KOC Drive
audience: frontend
---

# KOC Drive

Windows 트레이 앱이 워크스페이스 공유 문서함을 탐색기에 보여 줍니다. 파일은 크기만 가진 플레이스홀더로 먼저 보이고, 열 때 내용을 받습니다. 문서함 API는 [document_frontend.md](document_frontend.md)입니다.

개인 문서함, 파일을 다시 플레이스홀더로 빼기, 카카오·애플 로그인은 포함하지 않습니다.

## 유저 플로우

1. 이메일과 비밀번호로 `POST /api/v1/auth/login`에 로그인합니다. `refresh`는 Windows 자격 증명 관리자에 두고, `access`는 메모리에만 둡니다. 만료되면 `POST /api/v1/auth/refresh`로 바꿉니다.
2. `GET /api/v1/workspace`로 워크스페이스를 고릅니다. 하나가 아니면 처음 한 번만 고르고 기억합니다.
3. `GET /api/v1/document/{workspace_id}/space`에서 `kind`가 `shared`인 문서함을 고릅니다.
4. `%USERPROFILE%\KOC ERP`를 동기화 루트로 등록합니다. 탐색기 탐색 창 이름은 KOC ERP입니다.
5. `GET .../sync-cursor`를 받은 뒤 폴더·파일 목록으로 트리를 만듭니다. 이후 약 15초마다 `GET .../changes`만 따라갑니다.
6. 파일을 열면 `POST .../file/{file_id}/sync-url`로 내용을 받아 채웁니다. 이 호출은 다운로드 이력을 남기지 않습니다.
7. 저장, 이름 변경, 삭제는 문서함 API로 올립니다. 서버가 403이면 플레이스홀더를 되돌리고 트레이에 오류를 남깁니다.
8. Windows에 로그인하면 앱이 다시 실행됩니다.

## 충돌

로컬 해시와 서버 `content_hash`가 같으면 그대로 둡니다. 로컬이 깨끗하고 서버만 바뀌었으면 서버 내용으로 플레이스홀더를 갱신합니다. 로컬만 바뀌었으면 `POST .../file/{file_id}/upload`와 `POST .../file/{file_id}/content`로 올립니다. `base_hash`가 어긋나 409이면 서버 내용을 유지하고, 로컬 파일은 `이름 (충돌).ext`로 새 문서에 등록합니다. 오프라인에서 만든 변경은 로컬 대기열에 두었다가 연결되면 올립니다. 열기와 받기는 온라인이어야 합니다.

## 구현 체크리스트

- 코드는 `clients/koc-drive`입니다. `KocDrive.Core`는 `net8.0`이고 WSL에서 `dotnet test` 합니다.
- `KocDrive.CloudFiles`와 `KocDrive.App`은 Windows에서만 동작합니다. 탐색기 확인은 Windows 기기에서 합니다.
- 배포본은 Windows x64용 자체 포함 폴더입니다. .NET을 따로 설치하지 않습니다. `clients/koc-drive/publish.sh`가 `dist/KocDrive-win-x64.zip`을 만듭니다. 압축을 풀고 `KocDrive.exe`를 실행합니다. 설치 마법사는 없습니다.
- 서버 주소 기본값은 `https://kocerpbe-main.up.railway.app`입니다. 다른 주소는 환경 변수 `KOC_API_BASE`로 바꿉니다.
- 동기화 루트 등록은 `StorageProviderSyncRootManager`, 콜백은 Cloud Files API입니다.
- 플레이스홀더 identity는 서버의 폴더 id, 파일 id입니다.

## 비범위

- 개인 문서함
- 받은 파일을 다시 비우는 동작
- 50MB를 넘는 파일과 0바이트 파일
- 구간 다운로드

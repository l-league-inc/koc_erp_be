---
name: KOC ERP API 백엔드 개발 지침
description: KOC ERP API 백엔드 개발을 위한 역할, 프로젝트 설명, 개발환경, 코드 구현 규칙, 목차를 담은 지침 문서입니다.
applyTo: "**"
---

# 역할
- 당신은 Python 3.10+ 및 Django-Ninja를 사용하는 API 백엔드 전문가입니다.
항상 명시적인 타입 힌팅을 사용하고, 비즈니스 로직과 API 라우팅 레이어를 엄격하게 분리하여 코드를 작성합니다.

# 프로젝트 간단 설명
- 프로젝트명: KOC ERP
- 프로젝트 간단 설명: KOC ERP 백엔드 API
- 타겟 사용자: KOC ERP 사용자

# 개발환경
- Django-Ninja
- Python


# 코드 구현 규칙
- Django-Ninja의 Docs를 최대한 참고하여 작성
- Django-Ninja의 ModelSchema를 사용

# 문서 위키

관리자 계정으로 `/wiki/` 에 로그인하면 `docs/` 마크다운을 열람할 수 있습니다 (`/wiki/login/`).  
위키 CMS를 따로 편집하지 마세요. **문서를 `docs/`에 추가·수정하면 위키가 그대로 반영됩니다.**

프론트 전달이 필요한 API/계약 변경이면 `{주제}_frontend.md` 를 쓰고 YAML frontmatter (`title`, `audience: frontend`)를 붙인 뒤, 아래 목차에 행을 추가하세요.

# 목차

| 문서 | 설명 |
|------|------|
| [models.md](../docs/models.md) | CommonModel, 소프트 삭제, 마이그레이션 절차, UniqueConstraint |
| [api-design.md](../docs/api-design.md) | 라우터 등록, 인증, 페이지네이션, 에러 응답, 파일 업로드 |
| [workspace.md](../docs/workspace.md) | Notion형 워크스페이스 모델, 권한, MCP, Hermes |
| [workspace_frontend.md](../docs/workspace_frontend.md) | KOC 워크스페이스 데이터베이스·레코드·조회 계약 |
| [workspace_page_frontend.md](../docs/workspace_page_frontend.md) | 페이지 아이콘, 서식 블록, 댓글, 활동, 보기, 템플릿, 휴지통 |
| [agent_frontend.md](../docs/agent_frontend.md) | 앱 안 업무 대화, 스킬, 초안 확정 |
| [workbot_frontend.md](../docs/workbot_frontend.md) | 워크봇 저장, 실행, 통계 |

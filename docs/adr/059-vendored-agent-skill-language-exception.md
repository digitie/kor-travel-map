# ADR-059: 벤더링된 agent/skill 설정의 언어·context-discovery 예외 정책

### 상태

Accepted (2026-06-17) — issue #452 #450 review-followup.

### 배경

`.claude/agents`(전문 subagent 5종), `.claude/skills`, `.agents/skills`(Timescale/
PostgreSQL skill 세트), `.codex/agents`는 상위 카탈로그에서 벤더링한 원문이다(#450/#451).
2026-06-17 Claude Code PR 리뷰 취합(#452 #450)에서 두 문제가 제기됐다:

1. 5개 `.claude/agents/*.md`가 존재하지 않는 `context-manager` agent를 (일부는 필수)
   첫 단계로 요구한다 — 저장소에 해당 agent가 없어 실행 불가능한 지시다.
2. 본문이 전부 영어라 `AGENTS.md` "문서 언어 정책"(한국어)과 충돌하나 예외 정책이 없었다.

### 결정

1. **언어 예외**: `.claude/`·`.agents/`·`.codex/`·`.opencode/` 아래 벤더링된 agent/skill 원문은
   한국어 규칙의 예외로 영어 원문을 유지한다(상위 동기화 충실성). 단 본 저장소 관례에
   맞춘 **적응**은 허용한다.
2. **context-discovery 적응**: `context-manager` agent 의존을 본 저장소 실제 절차
   (entry 문서 `CLAUDE.md`→`AGENTS.md`→`SKILL.md`→`docs/architecture/architecture.md`→
   `docs/resume.md` + codegraph 질의)로 치환한다. 빈 `context-manager` stub은 만들지
   않는다(미사용 더미 회피).
3. 범위·근거는 `.claude/agents/README.md`에 명시하고 `AGENTS.md` 문서 언어 정책에
   한 단락으로 못박는다.

### 근거

- 빈 `context-manager` agent를 추가하면 미사용 더미만 늘고 사용성 문제는 그대로다.
- 전량 한국어 번역은 상위 원문과의 drift를 키우고 재동기를 어렵게 한다 — vendored
  예외가 더 싸고 유지보수에 유리하다.

### 결과

- `.claude/agents/{frontend-developer,ui-designer,backend-developer,api-designer,`
  `mobile-developer}.md`의 `context-manager` 참조를 entry 문서 + codegraph 절차로 교체.
- `.claude/agents/README.md` 신설(벤더 출처·예외 명시).
- `AGENTS.md` "문서 언어 정책"에 예외 단락 추가.

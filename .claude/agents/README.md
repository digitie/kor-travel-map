# `.claude/agents` — vendored upstream agent 원본 (영어 예외)

이 디렉터리(그리고 `.claude/skills`, `.agents/skills`, `.codex/agents`)의 파일은
외부 upstream에서 가져온 **vendored agent/skill 원본**이다. 이들은 한국어 문서
정책(`AGENTS.md` 문서 언어 규칙)의 **예외로 영어 본문을 그대로 유지**한다
(ADR-059). upstream과의 drift를 줄이고 재동기를 쉽게 하기 위함이며, 본 저장소의
다른 문서(docs/**, 루트 `*.md`, `SKILL.md`, `AGENTS.md`)는 한국어 정책을 따른다.

## 본 저장소에 맞춘 조정

upstream 원본은 별도의 `context-manager` agent에 컨텍스트를 질의하는 절차를
전제했으나, **본 저장소에는 그런 agent가 없다.** 따라서 각 agent 파일의
context-manager 의존 단계(필수 첫 단계, `requesting_agent`/`get_*_context` JSON
질의 stub, "Notify context-manager" 핸드오프 줄)는 본 저장소의 실제 컨텍스트
탐색 절차로 교체했다:

- entry 문서를 순서대로 읽는다 — CLAUDE.md → AGENTS.md → SKILL.md →
  docs/architecture/architecture.md → docs/resume.md (CLAUDE.md §3 진입 순서).
- 코드 작성 전 codegraph 인덱스로 기존 심볼과 영향도를 조회한다 —
  `codegraph_explore`(survey) + `codegraph_callers`/`codegraph_impact`(영향도),
  area/feature 맥락은 `codegraph_context`.

본문(frontmatter, tool 목록, 나머지 workflow)은 upstream 원본 그대로 두고, 위
context-discovery 부분만 본 저장소 기준으로 맞췄다.

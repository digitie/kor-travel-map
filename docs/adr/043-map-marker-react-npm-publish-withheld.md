# ADR-043: `@kor-travel-map/map-marker-react` npm 게시 보류 — 모노레포 내부 share로만

- **상태**: accepted (PR#33, 2026-05-27) — ADR-029를 supersede
- **날짜**: 2026-05-27
- **결정자**: 사용자

### 컨텍스트

ADR-029에서 `packages/map-marker-react/`를 별도 npm 패키지(`@kor-travel-map/map-
marker-react`)로 추출 + npm registry 게시까지 계획. 사용자가 검토 후 "npm
게시는 하지 말 것"으로 지시.

### 결정

- `packages/map-marker-react/` 코드 자체는 **유지** — 디버그 UI가 카테고리/maki
  매핑을 공유하는 단일 source.
- **npm registry 게시 안 함** — `package.json`에 `"private": true` 박음.
- 사용처는 git URL + commit sha 또는 yarn/pnpm workspace로 import (모노레포 내부
  share). registry install 의존 없음.
- `@kor-travel-map/map-marker-react` scope 이름은 유지(이전 등록 X). 향후 다시
  registry 게시 필요해지면 새 ADR로 unfreeze.

### 근거

- npm registry 게시는 namespace 점유 / 버전 관리 / 보안 책임이 따른다.
- 현재 사용처가 모노레포 내부로 한정되어 git share로 충분.
- 사용자 결정 — registry 외부 노출 보류는 보안/유지보수 비용 절약.

### 결과 (긍정)

- npm 계정/2FA/access token 관리 회피.
- 라이브러리 코드 변경이 즉시 디버그 UI에 반영 (git URL refresh).

### 결과 (부정)

- 외부 OSS 사용자가 본 패키지를 쓰려면 git clone + workspace 설정 필요 —
  진입장벽 약간 상승. (현재 외부 OSS user 0 → 비용 없음.)

### 후속

- `packages/map-marker-react/package.json`에 `"private": true` 박음.
- ADR-029 status `superseded by ADR-043` 표기 (본 PR 동시).
- `docs/journal.md`에 결정 reverse note.
- `pyproject.toml` 등에서 `@kor-travel-map/map-marker-react` 의존성은 git URL
  형식 유지(npm install registry 의존 X).

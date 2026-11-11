# ADR-123 — 관리자 UI와 지도 공용 구현 채택

- 상태: accepted(사용자 확정 방향, 2026-11-11). 산출물은 통합 검증 후보이며 배포 승인과 구분한다.
- 범위: Map frontend. DB·인증 세션·REST·transport 정책 변경 없음.

## 결정

운영 표는 common VirtualTable 한 구현을 쓴다. TanStack 9의 기능 제네릭은 common에서 숨기며
기존 DataTable public props와 ColumnDef/Row/Cell 타입 사용을 보존한다.
기본 렌더링은 semantic table이며 정렬 aria-sort, 행 선택, 가상 스크롤을 제공한다.
Geo의 plain renderCell은 열 정의 배열이 바뀌어도 SSE 셀의 수명을 보존한다.

버튼·체크박스·dialog·popover·tooltip·tabs·field 등 shadcn Radix primitive는 common을 쓴다.
앱의 추가 variant/disabledReason/도메인 행위는 얇은 로컬 조합에 둔다.
Base UI와 범용 floating 위치 계산은 제거한다. Pretendard와 Radix token bridge를 가져오되
로컬 semantic theme를 뒤에서 적용한다.

지도 생성·해제·VWorld URL/style은 GitHub 최신 web/core public API에 위임한다.
모든 앱은 부모가 제공한 동일 tgz와 SHA512 원장을 사용한다. 도메인 마커·클러스터·geometry와
long press 정책은 Map에 둔다. 최종 upstream 수정 commit과 pack freeze는 부모가 확정한다.

로그인은 common LoginForm의 RHF+Zod 검증 및 인스턴스별 Zustand를 사용한다.
원격 상태는 Query, UI 상태는 Zustand라는 기존 경계를 유지한다.
복잡한 feature/provider 편집 폼은 별도 단위로 이관하며 기존 검증을 삭제하지 않는다.

## 검증과 배포 경계

ESLint 10, React Doctor full/warning gate, AST 소스/원장 guard를 CI에서 강제한다.
TypeScript는 현재 peer 호환 때문에 5.9.3, Node 타입은 runtime 22에 맞춘 22.20.5 exact다.
검증·독립 리뷰 2개·CI·PR merge·부모 go 뒤에만 UI 새 이미지를 배포한다.
구체 절차와 잔여 gate는 [통합 기록](../reports/common-unification-20261111.md)에 둔다.

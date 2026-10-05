# ADR-107 — Dagster 복구·제한 전송과 관리자 UI의 Common 채택

- 상태: accepted
- 날짜: 2026-10-05
- 결정자: human, Codex

## 컨텍스트

Map의 긴 수집·Dagster 조회가 다른 요청에 실패를 전파하거나 최근 실행 목록 밖의 활성 job을 숨길 수 있다. Weather·Transport·Geo·PinVi와 같은 복구·메모리·관리자 UI 기반을 사용하라는 사용자 지시를 반영한다.

## 결정과 근거

API·Dagster 패키지는 `kor-travel-common`의 각각 HTTP·Dagster extra를 고정 Git commit으로 소비한다. 관리자 UI는 동일한 공통 로그인·메뉴·Dagster UI 산출물을 소비한다. Map의 canonical operation·curation snapshot·queue·인증·REST 경계는 앱이 계속 소유한다. 저장소를 우회하는 자동 write run 복제는 허용하지 않고 기존 identity와 복구 절차를 사용한다.

## 결과와 후속

공통 timeout·응답 제한과 job runtime tags를 적용하며 step·DB 연결·bundle 배치를 제한한다. 관리자 전용 summary endpoint를 OpenAPI와 UI 타입에 함께 추가한다. 요청별 HTTP client는 불확실한 연결 재사용을 방지하지만 새 요청의 연결 생성 비용이 있다. shared Dagster 운영 설정은 Manager 배포 경계를 따른다. 두 독립 리뷰와 paired 재구축·실제 UI 검증 결과는 [검증 기록](../reviews/common-dagster-2026-10-05/README.md)에 보존한다.

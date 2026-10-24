# 공용 지도 작업면 채택 후보 — 2026-10-24

## 변경과 고정 산출물

Map Feature 작업면을 공용화한 Common `e79816afb3c19b1b1e2fc1486b809c2ee3d34d6e`를 소비한다.
[공용 API·치수 계약](https://github.com/digitie/kor-travel-common/pull/45).
Feature 지도의 종류 필터에 아이콘을 결합하고 필터·보기 탭·건수/실제 좌표·줌·상세 오버레이를 공통 컴포넌트로 소비한다. Map의 기본 종류·소스·상태 필터와 조회 동작은 보존한다.

`kor-travel-ui-0.1.0-dev.7.tgz` SHA256은 `4445c694013bd19fb57d3655cfc25d86e99a6733d655524718be3bf769ba7422`다.
Map/Transport/Weather가 같은 산출물과 lock integrity를 고정한다.

## 검증과 통합 경계

동일 소스/고정 lock을 WSL 내부 디스크에서 설치하여 타입 검사 PASS. frontend395 중 mirror에 빠뜨린 core enum 파일로3 실패가 있었고 같은 파일을 복사한 후 해당6 PASS, 나머지392 PASS였다. Common UI54와 Transport/Weather 반응형375/1440px 소비자 검증은 별도로 PASS다. Map 자체 live 브라우저/CI·최종 통합 gate는 아직 미실행이다.

사용자 지시로 운영 빌드·배포는 다른 통합 에이전트가 담당하며 이 후보는 배포하지 않았다.
Weather 종류 필터는 API/UI를 함께 반영해야 한다. UI만 먼저 배포하면 서버 필터가 적용되지 않는다.

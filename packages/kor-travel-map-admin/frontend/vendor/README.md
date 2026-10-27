# 고정 공용 UI 산출물

## 로그인 hydration 준비 dev.9 (2026-10-27)

Common source `aa232ad5f255233184de80eceaab2e9b6ccb00c9`(#47 병합). `kor-travel-ui-0.1.0-dev.9.tgz` SHA256 `b738d8824e36eb6e58d8cc6b78af7dc31233b6763248d634286044def795b403`. Common CI `packages` lane 조건(Node 22.23.1·npm 11.19.1·루트 `npm ci`·`npm pack -w packages/ui`)으로 재현했고 Common T-217의 정규 산출물과 byte-exact다. dev.8의 지도 작업면(`MapWorkspace`·`MapFilterPanel`·`MapStage`, 상세 header/접기)은 opt-in이며 Map은 아직 채택하지 않는다. 더 쓰지 않는 dev.6·dev.7 tgz는 지웠다. [출처](../../../../docs/third-party-common.md).

## 공용 지도 작업면 dev.7 (2026-10-24)

Common source `e79816afb3c19b1b1e2fc1486b809c2ee3d34d6e`. `kor-travel-ui-0.1.0-dev.7.tgz` SHA256 `4445c694013bd19fb57d3655cfc25d86e99a6733d655524718be3bf769ba7422`. Map/Transport/Weather 동일 산출물이었다. [검증](../../../../docs/reports/2026-10-24-shared-map-ui.md).

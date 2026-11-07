# KNPS 대피소 미적재 해소

## 범위와 완료 기준

사용자가 Map1450 범위를 다른 미적재 KNPS 데이터셋까지 확대했다. 최신 main70b86c5에는 Claude Code의1452 스케줄과1453 보호지역 정책이 이미 포함돼 있다. 이를 보존하고 T-KNPS-DATA-GAPS 중 남은 python-knps-api17 대피소 중첩 SHP 파싱을 처리한다. 이미 적재한 화장실·야영장·문화자원, 보호지역 allowlist·바다 역지오 drop, 위험지역/선형시설 미적재 정책을 바꾸지 않는다.

## 구현과 검증

공급자 draft18에서 공개 typed place record를 먼저 수정·검증·독립2리뷰·CI 뒤 병합한다. 이 PR은 실제 병합된 공급자 SHA로 핀을 올리고 공개 client에서 Map place 변환까지의 회귀·실제 격리 PG 적재·필요한 WSL UI를 검증한다. 자연키와 주소 계약을 우회하거나 단순 wrapper를 추가하지 않는다.

초안 PR을 먼저 만들고 자주 commit/push한다. 실패 우선·WSL 관련/필수 검사·전문 독립 적대리뷰2명·정확 HEAD CI 후 머지한다. 운영/SSH/실제 provider 호출·운영 적재는 수행하지 않는다. 공급자 공식 원천 확인과 prod 재적재·Pinvi UI 최종 확인은 Claude Code 인계에 남기며, 확인 전에는 운영 데이터 성공으로 기록하지 않는다.

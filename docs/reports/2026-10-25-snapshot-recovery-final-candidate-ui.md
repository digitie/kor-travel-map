# 430 복구 통합 후보 API·UI 실제 검증

고정 API source 1093dd3e7e3432e79824a9f445a89fd640609434와 schema head430에서
실제 uvicorn factory/lifespan·DB preflight, Next/BFF와 n150 Linux 브라우저의
격리 후보 E2E를 통과했다. pytest는 1 PASS/skip0, XML suite 51.698초이며
브라우저 판정은 14개다. 운영 서비스나 운영 자격증명은 변경·사용하지 않았다.

최종 성공 실행의 로그인·로그아웃 POST는 각각 1회다. 취소와 같은 취소 replay의
POST는 합계 2회이며 실제 DB cancellation attempt는 1개다. 상세 조회와 reload,
취소 후 상태, HttpOnly cookie, 보호 요청의 로그아웃 후401, 실제 WebSocket
3연결/17수신 frame, 로그아웃 뒤5초 재연결 관측과 reload 로그인 요구를 확인했다.
page error와 범위 밖 요청은 각각0이다. 한 개의 synthetic generic queued root를
검증했으며 전체 수집 활성화·물리 worker commit 경합·운영 배포 증거로 확대하지 않는다.

API는 최종1093의 실제 Git import7개와 SQLAlchemy2.0.54/default pool로 실행했다.
UI는 기존7839 source의 수용된 production build를 재사용했다. 최종source와
frontend333개·marker workspace10개·user client5개·root npm입력3개, 합계351개의
mode/blob이 같고 관련 BFF 전부가 포함됨을 별도 대조했다. 기존 build의 원archive2437개,
manifest4개/static176개도 다시 검증했다. 전체1093을 새로 build했다고 표현하지 않는다.

runner의 실제 source2509개·SDK53개 전후와 import16개를 확인했다.
API/UI owned unit은 PID0, owned tunnel은 부재, 임시 config는 삭제됐다.
브라우저 owned process와 profile도 제거됐고 Node/Chrome/module inventory는 전후 같았다.
정확 PG CID/UUID label과 익명 volume1개는 부재이며 runner의 최종 scalar global label0을
확인했다. 슬롯 반환 뒤에도 정확 CID/UUID/volume 부재와 현재 source/SDK 전체를
독립 read-only로 재확인했다. 원 private audit log는 보존하며 전체 비밀 폐기를 주장하지 않는다.

첫 최종후보 r1은 TEST 파일hash와 달리 실제 --pyargs module 인자가 옛1410r3를 가리킨
감사 하네스 오류였다. 옛7839 API의429 preflight가430DB를 거부했고 browser/auth는0이었다.
그 FAIL과 raw8/XML36.274초·별도 source/SDK 후관찰을 그대로 보존했다.
인자1곳과 namespace/launcherhash만 바로잡은 r2가 위 최종 성공 실행이다.
그에 앞선 offline build입력 경로 범위 오류도 PG 기동 전 자료로 분리했다.
제품 assert·권한 guard·시간/자원 상한은 완화하지 않았다.

공통 finish 성공종결 경합 보완은 별도687 source에서 canonical lifecycle actual3PASS,
기존 failed/cancelled 차단·원 tracking/receipt 불변을 검증한 뒤 최종1093에 합성됐다.
W674의 claim 뒤 fresh SDK0 read와 exact inactive-seal 원receipt 복원 수정은
별도 source 검토와 순수40PASS로 P2 closure를 확인했다. 이 결과들과 실제UI1을 합산하지 않는다.

최종 사실 원장: map430-1093-final-candidate-live-ui-r2-actual-acceptance.json
SHA256 eb76f987f99d79c1a84a17d7c68478a05854155fe946cd7308f5010c32f8ed52.
원 result: map430-owned-final-candidate-ui-r2-86da04dba5cf46208e92ae22fa842639/result.json.
이 실제 검증 뒤 제품과 SQL은 변경하지 않고 역비교 fixture와 문서만 수정했다.
최종 head의 제품·스키마·UI 입력 동등성으로 위 검증을 연결하며 새 전체 build를 주장하지 않는다.
최종 CI 수용·머지·공식 운영 배포는 각각 별도로 정산한다.

## CI 원 실패와 비교 기준 수정

1093의 CI 세 Python lane은 각각4177 PASS/7 SKIP과 같은 activation 역비교1 FAIL이었다.
430으로 바뀌는 현재 head-schema를 과거429 기준으로 사용한 시험 경로가 원인이다.
원429의 activation1개와 tracking authorization2개 정의 전체를 고정 fixture로 남겼고
원 assert를 보존했다. tracking은 같은 최신 함수끼리 비교해 우연히 통과하던 경로도 고쳤다.
제품·SQL·권한·ORM·golden 변경0이며, 별도 전체 unit4180 PASS/6 SKIP(167.19초)을 확인했다.
첫 로컬4167 PASS/13 FAIL은 Next @next/env 미설치였고, 같은 lock의 기존16.4.3 캐시를
읽기 재사용한 뒤 위 전체 검사가 통과했다. 원 실패 로그는 별도 보존한다.
최종 exact CI는 이 fixture·문서 변경을 포함한 head에서 새로 확인하며, 아직 성공으로 세지 않는다.

## 운영 경계

신규 read-only 운영 조회에서 Map head409와 7개 Map·PinVi 관련 컨테이너의 healthy를 확인했다.
Map source974e2d0258c53efdffaa1446abed30603d0c72a3와 PinVi source3e1e8bc0327397bb506a0ea0e3b3acc04bbc606f다.
실제 스케줄28 RUNNING/7 STOPPED, 센서10 RUNNING/2 STOPPED의 identity를 기록했다.
운영 image·DB 배포와 SH 활성화는 미실행이다. 최종 CI/두 리뷰 뒤 공식 Manager 절차로
418 commit과 최종430 commit을 분리하고, 원래 중지된 작업과 퇴역 작업은 재개하지 않는다.
실제 두 dataset worker overlap·Rest profile fit·전체 T-CWRITE 수용, Common→Weather/Transport
전파와 CPU/RSS 비교는 후속이다. 이 UI 검증으로 완료 표시하지 않는다.

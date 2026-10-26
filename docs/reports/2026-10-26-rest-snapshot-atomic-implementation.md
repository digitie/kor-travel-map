# Rest432 실제 동시 쓰기 구현 원장

## 최종 제품652의 CI·병합·공식 배포 수용

이 절은 아래 각 시점의 실패/대기 기록을 삭제하지 않고 마지막 제한 단위의 상태를 정산한다.
최종 제품 `6520215810bcc23d50c0aea169e5100c3ac46617`은 Python3.11/3.12/3.13,
fixture replay, Alpine/glibc PostGIS, lint/OpenAPI/frontend/production image의 **10개 CI가
모두 SUCCESS**다. PR #1418은 main `d7fd7d18b2e33bce130b0b49951d3794c36f91a8`에 병합됐고
제품·시험·UI·문서 전체 tree가 정확히 일치한다. 이전6ceb/5d6 및 초기 CI·오라클·하네스 실패를
최종 성공으로 바꾸지 않는다. 제품 변경과 각 최소 수정에는 독립2인 적대 검토를 적용했다.

### 같은 상한의 최종 owned 시험

| 시험 | 실제 수용 | 구분해야 할 범위 |
| --- | --- | --- |
| 합성215 전체 | console92.19초/case91.228초, atomic17.733949초·reader왕복2.261216초·decode0.726517초·assessment1.449269초; wholecomplete/retired0·23비scalar·Geo/policy/head 양clock·후처리·별도seal PASS | reader3초/lock1초/wholeTX30초 및 기존 capture 상한 유지; upstream HTTP0,215 backend CPU/RSS 미측정 |
| byte quota 첫 초과 | console89.24초/case88.353초,11×744997B 등록 뒤12번째53000·정확constraint·wholeTX rollback PASS | 8MiB/16행과 원검증 불변; 한 owned 시험의 값이며 운영 처리량이 아님 |
| 새 빌드·실제 API/Next 후보 | console53.95초/case53.043초,원14판정·login/logout각1·cancel2·WS3연결 총수신18frame·보호401/5초 재연결없음·세션미해제가능성false | exact652 source/build·UI351·manifest4/static176·mock0·정확자원정리; 공개 배포 후13과 별개 |

위 세 실행의 raw10/10/9 SHA·Git2577 mode/OID/전체 blob·SDK53 전후·import52/52/16과 API7을
저장 원문으로 대조했다. 독립 원장 `map1418-652-j-independent-final-three-actual-acceptance-r1.json`
SHA256은 `2a6dd803be4eb88dc89d21fca4ae417d007d9dd6821b1ab6f4ec13ec4218b3b7`이다.
로컬 Python3.13.14/별도 이미지의 CTracer 결과를 CI 환경과 동일하다고 주장하지 않는다.

source511의 추가 물리 시험도 각 범위에서 통과했다. 같은 member 최초 등록은 immutable1개·
quota한번·첫 nonce만, 이전 read/다른 worker seal 경합은 원 receipt SDK0, 적용중 GC는 정확
writer 대기→own backend 종료 뒤 rollback/GC0·원자료/예약 보존을 확인했다. 두 profile의 실제
blocker와 양commit도 통과했다. CPU ticks는100Hz에서 Airport 선행[21,41], Rest 선행[11,17],
backend RSS는4개 sample point뿐이다. client begin-SQL→commit ACK 구간·controlled hold와
backend 실제 lock 취득/해제 시각은 다르다. 원 역순 deadlock 재현·일반 caller 교착 부재나
S5 일곱 종류 전부의 새로운 Rest 물리 시험으로 확대하지 않는다.

### 공식 설치·공개 UI·기존 일정 복원

공식 rebuild 원장은 success/phase=committed, 실제 schema는 Map432/PinVi0102다.
Map3개·PinVi3개와 Valkey를 합친7개가 healthy이며 공개 UI 전후 같은 runtime7을 확인했다.
운영 설치의 원장 `map432-official-rebuild-d7fd-20261026-r1.json` SHA256은
`c2fea706fcdfc23feb3e66e9fc28be853dcc818a5f9f4e0c9f5fc1148fb04b12`이다.

배포 후 공개 read-only UI는55.972초에 Map7/PinVi6 모두 통과했다. 실제 secure/HttpOnly
쿠키·지도와 provider tile·기존 목록/상세 identity·재조회·logout200/204 뒤보호401을 확인했다.
Map/PinVi login/logout은 각각1회이고 새 세션 잔류가능성은false다. business DML0,
credentials/raw cookie/trace/screenshot 저장0이며 browser/profile을 회수했다. runtime7와
브라우저 runtime106/Node/Chromium 지문·설치 env는 전후 동일했다. 원장
`map-pinvi-postdeploy432-public-readonly-5bc1e8e4a66e441b8e49e73d0cf25d57.json` SHA256은
`65c1512049d34e8b22b7d1295af32ce3be1eaec9f670289c6cca0d8c27c72e33`이다.

기존 RUNNING37개만 복원했고 STOPPED14개·새 profile OFF는 유지한다. root env의 bytes·mode도
그대로이며 새 활성화0이다. 복원 원장 `map432-postdeploy-instigator-restore-d7fd-root-r1.json`
SHA256은 `cb5978786b2e8f422f6e4e1e4396aa66f5cd2e6df0eb0ed8044f444b4942d8d2`다.

### 계속 열린 상위 수용

이 제한 단위의 완료가 **T-CWRITE-01–09 전체 완료를 뜻하지 않는다**. 운영 CPU/RSS·물리
heap/WAL·215 backend CPU/RSS와 실 upstream215 수집은 미측정/미수용이다. 공유 Feature의
후보/winner·양성 동시 쓰기, 지역 경계 이동·전 writer 전환, 실제 OS worker 사망/물리 wire
단절, 새 profile 활성화·실부하/확대·되돌림 전수 수용은 각각 기존 상위 과제로 남긴다.
SQL/권한/자료 정본·reader3초/lock1초/wholeTX30초·quota와 capture 상한은 유지했다.

## 5d6 최종 glibc byte quota 실패와 네이티브 문자열 선검사 초안

최종5d6 CI는9성공·1실패다. glibc의 quota bytes 시험만 전체30초가 등록 SQL 대기 중
만료됐고1931PASS/23SKIP였다. 원로그 SHA256은
`ea981c432e7aeed9235f424e12919ba60c9815d319cebd811864d91a1a840ad3`이다.
Alpine 성공이나 기존 owned Bbytes 성공으로 이 실패를 덮지 않는다.

같은215개 순수 fixture(719797B)의 CTracer 한정 구간을 확인해 JSON 객체를 만들기 전
문자열·모델 선검사 비용을 줄이는 초안을 추가했다. exact str/None/bool은 일치할 수 없는
모델/enum 목록을 탐색하지 않는다. ASCII는 네이티브 판별·escape span으로 기존 인코딩
비용만 계산하며 복사된 JSON 객체를 만들지 않는다. wire scanner도 인용 문자열 span만
네이티브로 건너뛰고 바깥 node/depth를 기존처럼 센다. 잘못 닫힌 문자열의 최종 구문
거부는 기존 json.loads 책임을 유지한다. 공통 helper이므로 Airport에도 같은 의미 보존
검사를 적용하되 각 profile의 상한·wire·pins·검증 계약은 바꾸지 않는다.

단일 순수 구간 관측에서 preflight0.552→0.158초, whole decode1.682→1.036초였다.
후속 stdout의 source 필드는 benchmark donor가 가진 base5d6 문자열이므로 그 자체가
수정 전 제품 실행 증거가 아니다. 해당 working 입력의 codec SHA256은
`28b54c18fce0bdb3bfb2dabe7226b9f69f6de2591b7c61745e2d6ccce9c25534`이며,
CI/DB 전체시간·운영 CPU/RSS 개선률로 환산하지 않는다. 새28개 문자열/예산 경계와
기존179개를 합친207개가6.70초에 통과했다. 두 독립 리뷰·실제PG·새 최종CI 수용은 남는다.
전체30초·reader3초·lock1초·8MiB/16행·215 fixture와 SQL은 그대로다.

첫 정규식 초안은1MiB의 유효 escape 입력에서 약78.5MB의 역추적 상태를 만드는 문제가
독립 리뷰에서 발견돼 보류했다. 원 반례를 보존하고 겹치지 않는 span을 possessive로
소비하도록 수정했다. 최종 codec SHA256은
`ed7ff46acc50b5a2eaa39377ce92693117a3bb84db97d28698e5080f2c3e98c8`이다.
Linux3.13 순수 regex의 추적 peak는1286B였으나 전체 RSS 또는 ARM 결과는 아니다.
최종 관련207개는6.77초, 두 독립 전문·원본 차등·메모리 수정 리뷰는 PASS다. mypy1과
CI 대상 source/test/packages Ruff는 통과했다. 별도 `ruff check .`는 이번 변경 밖의
기존 docs/handoff 및 scripts 파일의7개 지적으로 실패했으며 무관 파일은 수정하지 않았다.
새 실제PG와 최종CI·운영 수용은 아직 남는다.


## 8fa 제품의 같은 상한 PG·새 후보 UI 검증

`8fa17bf4ed82ba89c504ac13342f6943c5250cd4`는 두 독립 제품 리뷰와 관련160개 순수시험,
Ruff·strict mypy2·import4를 통과했다. 공개 strict assessor는 유지하고 같은 호출에서
이미 decode한 두 값만 private 의미 대조로 보낸다. frozen 순수215의 coverage 비교는
5.260→1.442초였으나 DB 없는 해당 함수 구간이며 whole TX/운영 CPU 개선율로 환산하지 않는다.

개입 코드 없는 coverage 실제 PG 결과는 다음과 같다. 두 실행은 각각 별도 owned DB를
사용하고 각 종료 뒤 정확 CID/UUID/볼륨을 정리했으며 operating 호출은 없다.

| 선택 시험 | 실제 결과 | 판정 |
| --- | --- | --- |
| 합성215 전체 반영 | case100.369초, reader2.226481초·decode0.733188초·assessment1.456537초·atomic19.733465초 | 전체215/retired0·원 결과·필수 후처리·별도seal PASS |
| 실제 byte quota 첫 초과 | case119.625초,11×744997B 등록 뒤12번째SQLSTATE53000 | 정확 quota constraint·전체TX rollback·8MiB/16행 유지 PASS |

원장 SHA는 A215 `01fcbafacc81d87259c3408d387b969e73c6409b696437761af2989f0750f199`,
Bbytes `62afccdb60ecd41d628391aa91250c44a4b521dc17aecee9d0f63e87bd098940`이다.
독립 raw/환경/정리 검산 원장은 `77c9702c17f7b6e9b15930b6f722cc8f2f1258606ddd1c0e15c929f307f01b12`다.
모두 Python3.13.14·SQLAlchemy2.0.55의 로컬 합성 fixture이며 CI환경동등이나 서버CPU/RSS
측정이 아니다. 전체30초·reader3초·lock1초·SQL/ACL은 변경하지 않았다.

같은8fa source로 새 빌드163.352초와 실제 API/Next UI14개를50.038초에 통과했다.
원14 driver·엄격 n150 접속·자원/정리 상한을 그대로 사용했다. 실제 선택module·API7 및
전체 source2576/SDK53/UI351·manifest4/static176을 결박했고 mocked 응답은 없다.
로그인/logout 각1·cancel2·WS 연결3·수신17frame·보호401·5초간재연결없음·pageerror/outside0·
possible_unrevoked_test_session=false와 정확 browser/profile/API/UI/터널/ownedDB 정리를 확인했다.
UI 원장은 `d3d7374cf1d0e62038f1b022f4c3b844eec58fbb43b3f314959afe29b019e1ce`다.

이후 문서 정산은 제품 코드·시험·UI 입력을 바꾸지 않는다. 새 최종 CI와 main merge·
운영 배포/공개13 판정·원 일정 복원은 아직 대기한다. 원6ceb 실패는 삭제하거나 성공으로
바꾸지 않으며 일반 dataset/region 전수 CWRITE 확대나 OFF profile 활성화도 뜻하지 않는다.


## 6ceb 최종 CI 시간초과와 같은 호출 안의 재검증 비용 제거

`6ceb42780e0e393b9229c5b1dcb8566bb6a1d5c4`의 열 검사 중 여덟 개는 성공했고
PostGIS 두 검사는 각각 실제215와 byte quota 반복 등록의 합산30초에 실패했다.
glibc의 실제215는 COMMIT 응답 대기에서, Alpine은 후처리 시작 SQL 준비에서 취소됐다.
따라서 특정 SQL 하나가 원인이라고 단정하지 않으며 COMMIT 결과 불명 경계를 보존한다.
reader3초·lock1초의 실패와도 구분한다. 원 로그는
`map1418-6ceb-ci-failed-raw-r1.log`로 보존한다.

후속 수정은 전체30초를 유지하면서 같은 호출에서 이미 검증한 값의 중복 작업을 줄인다.
Rest codec은 기존 exact-type 선검사·foreign timezone 거부·raw/identity/fieldset·native 지문·
canonical bytes 검사를 유지하고, digest 전에 만든 packed 값을 같은 호출의 envelope에
재사용한다. 호출 간 DTO/bytes 캐시는 만들지 않으며 Airport codec은 바꾸지 않는다.

Rest 적용은 원 artifact를 엄격히 decode하고 잠금 뒤 새 DB evidence도 엄격히 decode한
두 지역 값을 private 의미 대조로 보낸다. 별도의 값싼 Geo 집합 한도 검사는 유지하며
전체 범위·저장 projection·raw·Geo·scalar 판정과 fence/DB 재확인은 그대로다. 외부 입력을
받는 public assessor의 재검증도 유지한다. 가변 DTO는 기존 caller 독점 소유 계약을 따른다.

초기 새 Geo 회귀는 fixture가 Geo=None인 것을 놓쳐1FAIL/159PASS였으며 원 로그를 남겼다.
실제 GeoLoadContext를 구성한 수정 후 관련160개가7.13초에 통과했다. DB 없는 순수 검사이며
후속 두 독립 리뷰·같은 제한의 실제 PG·최종 CI가 남는다. 기존 새 UI14PASS는6ceb의
별도 검증이며 이 후속 Python 수정의 최종 source UI/배포 완료로 확대하지 않는다.



## 최종 CI 실패와 후속 수정 — 2026-10-26

정확 source `7fc5bff1439fcbbd3f03800d8d1d26563d917e6f`의 CI는 5 workflow 중
4개 성공·CI workflow 실패, 전체 검사 10개 중 8개 성공·PostGIS 두 개 실패다.
세 Python lane은 각각 core4426PASS/7SKIP·API1457PASS·Dagster1117PASS/4SKIP다.
glibc PG는3FAIL/1929PASS/23SKIP(1325.05초), Alpine PG는
3FAIL/1923PASS/29SKIP(1910.53초)이며 양쪽 모두 아래 세 실패가 같았다.

- 실제 Dagster asset: `AssetExecutionContext.run_id` deprecation 경고가 오류가 됐다.
- 실제215: 단일 apply/후검사/후처리의 전체30초가 만료됐다. 취소가 begin 후처리 호출에서
  관측됐다는 사실만으로 해당 SQL 단독 비용이 원인이라고 판단하지 않는다.
- byte quota: 여러 등록을 수행하는 같은 TX의 전체30초가 만료됐다. job 제한이나 reader
  statement3초·lock1초의 실패와 구분한다.

Rest caller는 기존 정본 helper의 native run 옵션으로 ID를 고정하고 ETL의 기존 retry
framing에 전달한다. 다른 caller의 기본 helper 계약·직접 호출 fallback·root 불일치 거부·
OFF 상태의 durable read 우선은 유지한다. recovery fixture에는 기존 DagsterRun을
`run=run` 한 필드로 노출한다. 관련 순수76PASS와 두 독립 리뷰는 실제 asset의 PG 수용을
대체하지 않는다. 실행 원장은 `map432-run-id-five-file-handoff-r5.json`이다.

Rest decoder는 바로 앞에서 검증한 digest/DTO/pins로 고정 envelope를 조립해 전체
`_snapshot` 두 번째 호출만 제거한다. encoder의 전체 검증과 canonical bytes·raw hash·
fieldset·clock·Geo·상한은 유지한다. 마지막 행의 raw/source link를 바꾸고 native digest도
재계산한 음성 2개를 추가해 관련127PASS를 확인했다. coverage ON 순수215행 decode는
기존2.71~2.85초에서 후보1.61~1.65초였으나 실제 TX 시간초과 해결 증거가 아니다. CI는 coverage7.17.0·Python3.13.16·별도 이미지,
기존 owned 시험은 무coverage·다른 interpreter/image여서 환경 차이를 명시한다.
새 owned 검증과 최종 CI·머지·운영432 배포는 아직 미완이다. 30초/3초/1초와 quota 및
검증 단언을 완화하지 않는다. 원 최종 CI 원장은
`map1418-7fc5-terminal-ci10-five-workflow-failure-acceptance-r1.json`이다.

## 현재 범위

기준 main은 `df8776903c8ef54fc1e6ad89edfc5c3dd0934aed`다. 431 reader는 제품 CI와
후보 UI를 통과해 main에 반영됐고, 운영 배포도 아래 별도 Manager·공개 UI 절차로 완료했다.
이 문서는 [선택 A 명세](2026-10-26-rest-snapshot-registration-spec.md)와
[작업 목록](2026-10-26-rest-snapshot-registration-tasks.md)의 구현 checkpoint다.
실제 격리 DB의215·quota/GC·복구·공유 topic 두 writer는 아래 범위에서 통과했다.
최종 CI·후보 UI·머지/배포와 운영 활성화는 별개이며 아직 미완이다.

## 단일 transaction 경계

새 client 내부 coordinator는 하나의 READ COMMITTED connection/TX에서 다음을 수행한다.

1. 명시 session을 받는 정본 apply가 잠금 후 evidence를 재검증하고 원 14 counter와 retired를 저장한다.
2. 같은 session에서 미commit 원 입력과 원 결과를 읽고 snapshot·artifact/context SHA·상태를 대조한다.
3. 저장된 bytes로만 후처리 intent와 작업을 준비한다. 새 시계·SDK·HTTP·Geo 호출을 수행하지 않는다.
4. 기존 fenced begin SD, 같은 connection의 rollback_only bound client 작업, finish receipt를 수행한다.
5. outer commit 성공 응답 후에만 완료를 돌려준다. 오류·취소·불명확한 commit 응답을 전파한다.

등록·claim·planning은 별도 단계이고 child/root seal도 기존 P_EX 경로에서 별도로 수행한다.
기존 Airport public own-TX API의 서명과 동작은 유지한다. Airport runner의 prepared 경로는
새 coordinator를 쓰며, 이미 적용된 저장 snapshot 복구는 기존 SDK0 read와 receipt 확인을 따른다.
공유 작업 callback은 내부 코드에서만 구성하고, DB의 fence·domain 검증을 대체하지 않는다.

## 병행 소유권

- Root: coordinator, 기존 postprocess session seam, Airport 연결, asset/definitions/image 배선과 최종 통합.
- J: Rest 정적 SQL profile·migration·typed gateway·session apply·quota/설치 계약.
- T: 기존 service HTTP를 재사용하는 bounded 단일응답·Rest 관측/후처리·runner/runtime.
- W: rollback·응답 유실·두 물리 writer·공유 topic 잠금 시험과 기존 runner 회귀.

원본 dirty worktree는 보존하고 공동 branch에서는 Root만 stage/commit한다. Rest runtime은 기본
OFF다. 입력·wire·reader·quota 한도를 서로 혼동하거나 수용을 위해 자동 확대하지 않는다.

## 확인과 남은 항목

첫 Root checkpoint의 기존 postprocess transaction·Airport plan·backend 회귀는 34 PASS,
Ruff와 해당 5개 source의 strict mypy가 통과했다. 이는 mocked 단위 회귀이며 실제 PG의
전체 rollback·동시성·commit 응답 유실 증거가 아니다.

Rest SQL/collector 연결, 전체 source 통합, 두 독립 적대 리뷰, 실제 격리 PG·두 worker,
새 golden/최소 ACL, 전체 CI와 최종 live/UI가 남았다. 기존 431 후보·운영 시험 결과로
432 시험을 대체하지 않는다. CPU/RSS·잠금 대기와 처리량은 실제 두 writer 시험에서 계량한다.


## 두 번째 통합 전 checkpoint

초안 PR은 [#1418](https://github.com/digitie/kor-travel-map/pull/1418)이다. 기존 transaction/
plan/backend 34개와 새 coordinator·runner 65개를 합친 99개가 3.31초에 통과했다.
definitions/assets/resources 기존 43개는 3.97초, lazy capture resource 1개는 1.88초에 통과했다.
이 143개는 서로 다른 단위/구성 시험이며 실제 PG 수용과 구분한다.

처음 새 runner 시험은 아직 작성되지 않은 runtime 모듈 import에서 중단됐다. 의존 모듈을
연결한 뒤 위 시험을 통과했으며 원 실패 로그는 보존했다. 초기 Docker 배선에 추가했던
별도 Rest receipt 생성 호출은 제거했다. 기존 receipt가 전체 설치 파일을 지문으로 가지므로
Rest도 이를 검증해 재사용하며, 별도 receipt나 미구현 함수를 만들지 않는다.

실제 PG 시험 초안에는 5단계별 일반 오류/취소 후 18개 상태표 전체 rollback, 성공 commit 뒤
응답 경계 오류와 원 receipt 재사용을 넣었다. 빈 finding만으로 행 저장 rollback을 수용하지
않도록 실제 converter의 warning과 이전 stale finding을 구성했다. 현재는 소스·collect 단계다.
Rest 전체215·서로 다른 DS의 두 physical writer와 공유 topic 대기는 별도로 남아 있다.

공개 UI 13개 시험은 배포할 Map `df877690`·PinVi `9ebb588a`로 source pin만 정렬했다.
Root/T가 원 시험 세 파일과 허용 치환 외 전체 동일함을 검산했다. 배포의 실제 revision431,
컨테이너7개·권한·고정 버전 확인 전에는 실행하지 않는다. 이 준비를 운영 PASS로 표현하지 않는다.


## 배포 설정의 기본 비활성 계약

code-server Compose에 `KOR_TRAVEL_MAP_AIRPORT_SNAPSHOT_ENABLED`와
`KOR_TRAVEL_MAP_REST_SNAPSHOT_ENABLED`를 각각 기본 `0`으로 전달한다. 예제 env에도 명시한다.
이 변경은 기존 Airport와 새 Rest 모두를 OFF로 유지하며 실제 운영 설정을 바꾸지 않는다.
`1`은 검증된 immutable image의 전체 설치 receipt·정확 DS quota가 준비된 환경에서만 쓴다.
API/UI에는 이 opt-in을 주입하지 않으며 child/root seal까지 한 TX라고 표현하지 않는다.


## 431 운영 배포 정산

Map `df8776903c8ef54fc1e6ad89edfc5c3dd0934aed`·PinVi
`9ebb588ae425e5b09b613f0fed69b94eb1f34592`를 공식 Manager `0889d3b4`로 배포했다.
transaction `04684955-7490-4e95-9d61-91aa7da75ced`는 1872.74초에 committed,
실제 DB431/Pin0102·컨테이너7개 healthy·고정소스/권한/원root env 일치를 확인했다.

공개 UI UUID `1bc9d1efb9954683a8e9e107bdcf566c`는50.277초에13개 모두 통과했다.
새 두 session의 login/logout·보호401·browser process0/profile삭제·자원한도와 원env 불변을
검산했다. 이전 공개3FAIL·원 미확인 잔류session의 경계는 보존한다. 기존37개 RUNNING만
복원했고 새 기능 활성화는0이며 PinViWeatherOFF를 유지했다. 복원 뒤 fresh431/7healthy도 정상이다.

배포 전 Map·PinVi backup의 scratch복원은 verified다. Map은 동일revision에도 catalog
소유권·ACL 차이가 있다는 비차단경고를 보존하며 exactcatalog 복원 성공이라고 표현하지 않는다.
이 배포 완료는432의 실제215 apply/원자성·두writer·최종CI/live 완료와 별개다.
원장 `map431-root-operating-public13-restoration-closure-r1.json`과 각각의 실제 receipt를 구분한다.


## 세 번째 checkpoint: 실제 DB 시험 전 소스 검증

원자적 TX 안의 Rest fresh reader는 외부 30초 설정을 그대로 받지 않고 기존의 더 짧은
값을 보존하면서 statement 3초·lock 1초로 제한한다. 정상 읽기 후에는 원 설정을 돌리고,
SQL 오류·취소는 추가 SQL 없이 원 오류를 전파해 전체 TX를 rollback한다. 최초 반례
5개 실패를 보존했고 수정 후 44개가 통과했다. 두 명이 변경을 독립 검토했다.

Rest quota는 활성 정본 dataset에만 8MiB·16개로 초기화하며 global/Airport 한도와
사용량은 바꾸지 않는다. 215개 owned fixture의 논리 예약량은 최대 744,944바이트였다.
이는 실제 HTTP·PG 처리 속도나 프로세스 RSS가 아니다. fresh migration의 원 quota를
시험 준비 코드가 덮어쓰기 전에 읽어 검증하고, canonical installer로 strict guard를
설치한 뒤 새 runtime RO TX에서 33개와 inventory=true를 검증하도록 fixture를 보강했다.

통합 순수 회귀는 350개가 10.50초에 통과했다. core/Dagster strict mypy 244개 source와
실제 CI 경로의 Ruff도 통과했다. 저장소 전체 Ruff에는 변경하지 않은 docs/handoff 및
scripts의 기존 7개 오류가 남는다. 이를 실제 CI 경로 통과와 구분하며 원 로그를 보존한다.

현재 실제 432 PG 시험은 아직 0회다. 다음은 원자성 11개와 strict guard·원 quota 검증,
이후 Rest215·쿼터/GC·서로 다른 dataset 두 physical writer 시험이다. 새 golden/최소 ACL,
현재 커밋의 전체 CI·최종 live/UI와 배포도 남아 있으며 소스 리뷰 통과로 대체하지 않는다.


## 실제 원자성 11개와 공식 schema432 수용

커밋 `cb04509d`의 실제 owned PG 시험 11개가 통과했다(console 20.73초, XML 20.246초).
5단계별 오류/취소 후 18개 상태표의 rollback과 동일 plan 재실행, 성공 commit 뒤 응답 경계
유실의 SDK0 복구를 확인했다. seed 전 원 quota3행·사용량0 및 strict guard33/inventory
단언도 실제 통과했다. 물리 wire 유실·Rest215·두 writer·쿼터 소진/GC 수용은 별개로 남는다.
정확 CID/UUID/global label0·볼륨1개 부재를 재확인했고 원 실행/SDK/source 지문을 보존했다.

package migration graph 누락은 별도 검사에서 1실패·28통과로 드러났다. 정본 생성기로
기존 entry를 모두 보존한 채432→431 한 entry만 추가했고29개가1.25초에 통과했다. 두 명의
독립 검토 뒤 `c8836817`에 반영했다. 원 실패와 이전 실제 시험의 graph431 사실을 보존한다.

`c8836817`의 별도 fresh 공식 bootstrap→head→dump→정본 재덤프 비교는1개가27.459초에
통과했다(wrapper34.994초). runtime reconcile과 strict 자동 설치는0이다. 새 schema 지문은
`a55cf046257b5c4edda3e5c1a4abee8e0b3cb256d08d88fbffcca6450f060eb3`이며 실제 bytes를
`alembic/head-schema.sql`에 복사했다. 새 helper FUNCTION/ACL2개와 기존4함수/receipt TABLE
5개 변경 외 전체 블록이 보존되며 역치환하면 원431 전체 bytes와 일치한다. quota INSERT는
schema-only dump에 포함되지 않는다. 실제 startup ACL/metadata2개와 후속215·동시성,
최종 CI/live/UI 및 배포가 남아 있어 아직 완료나 운영 활성화로 표시하지 않는다.


## 실제 startup ACL·metadata 수용

`44c884c4`의 별도 fresh owned DB에서 정본 schema 검사2개가 모두 통과했다
(console18.57초/XML18.071초, wrapper25.322초). canonical runtime reconcile 뒤 Service
계정의 startup 경계 검사와 새 private helper 직접 EXEC 차단, snapshot private 표 무권한,
strict 자동 설치0·원 globalquota를 확인했다. 정본 `command.check`와 mapped CHECK 비교도
통과했다. 원9개 import·2571개 Git파일·SDK53 전후 일치와 정확 CID/UUID/global0·볼륨
부재를 검산했다. 원장 `map432-schema-acl2-owned-r2-t-actual-acceptance.json`을 보존한다.

공식 dump 반영 뒤 관련 source 회귀는82개 PASS/정본 조건부1skip(1.73초)다. 이를 actual
PG2개와 합쳐 중복 없는 전체 검사 수라고 표현하지 않는다. 실제 대량 적용·쿼터 소진/GC·
두 physical writer·프로세스 종료/복구·최종 CI와 UI·배포는 계속 진행 중이다.


## 실제 Rest 시험 구현과 CI 반례 정리

등록·215/쿼터/GC6개, 복구3개, 두 writer2개를 별도 파일에 구현하고 두 명씩 독립 소스
검토했다. 복구는 실제 DB backend 종료/전체 rollback·pool1 재사용, 잠금 뒤 late Geo
거부, 실제 Dagster run의 원 snapshot SDK0 재개를 검증한다. 두 writer는 서로 다른
Airport/Rest backend와 미commit TX의 수명 겹침, 실제 blocker·공유 topic 대기 및 두
commit 결과를 확인한다. 이는 SQL CPU 실행의 동시성·처리량 증가를 미리 증명하지 않는다.
모든 실제 Rest 시험은 아직 미실행이며 A215/BquotaGC/복구/두writer를 각각 기존150초
owned 실행으로 분리한다. backend CPU/RSS는 미측정, client wall/CPU와 SQL roundtrip은
구분 기록한다. 첫 observer SQL의 닫는 따옴표 누락은 적대 리뷰에서 발견해 최소 수정했고
원 source/HOLD와 소스 반례를 보존했다.

`44c884c4`의 원격 Python3개 CI는 각각4실패·4421통과·7skip이었다. 새 fetcher 명시 목록,
계수 전이의 generic 함수명 충돌, 저장 Geo 재사용 helper의 bare 호출 구조, provider 표의
등록 누락을 보완했다. 신규 private 이름만 고유화하며 기존 resource·Airport·검사기 단언과
예외 목록은 보존했고 계측 하한을1 높였다. 관련141개 PASS/기존2skip·Ruff/mypy를 확인했다.
새 진입점도 기존 transport 요청별 counter를 공유하며 실제 HTTP mock 계수 검사를 유지한다.
원격 CI 재통과는 새 source checkpoint 뒤 별도 확인한다. 이전402개 통합 순수 회귀와
현재141개는 중복이 있어 합계로 보고하지 않는다.


## 실제215 첫 실행의 clock 오라클 반례

`cc78cf37`의 A215 첫 owned 실행은1실패(68.73초)다. 실제 apply/후처리 뒤 검증 루프의
첫 item에서 head `observed_at`을 artifact `fetched_at`과 같다고 비교한 단언이 실패했다.
seal과215개 전체 후검사는 미도달했으므로 전체215 성공으로 수용하지 않는다. 원 source와
실패 log/XML, 정확 CID/UUID/global0·볼륨 정리를 보존했다. 실패 후 별도 RO 검산에서
source2574개와SDK53개 전후 일치를 확인했다. runner의 정상 post 검사는 미도달한 사실도
`map432-rest215-failed-r1-root-post-source-acceptance.json`에 구분한다.

정본 DTO/loader/native batch를 세 명이 대조했다. `SourceRecord`의 clock은 `fetched_at`과
`imported_at`이고, head의 `observed_at`은 후자를 저장한다. 동일 entity/rawhash의 immutable
record는 `DO NOTHING`으로 원 fetched/imported 시각을 보존한다. 새 수집 시각은 artifact와
context에 별도로 남는다. 잘못된1개 기대값을 head==원artifact imported_at로 정정하고
기존 current_record 전체 보존·새artifact fetched 시각을 명시 검사한다. 제품·SQL·상한은
변경하지 않는다. 다른5개 시험과 기존 검증을 유지하고 두 명 검토 뒤 전체를 재실행한다.

원실패의 locked reader client roundtrip은2.337초(실제 설정statement3초/lock1초),
decode0.247초·assessment2.116초였다. 이는 SQL 서버 CPU/RSS나 전체215 처리 성공 시간이
아니며 timeout 실패도 아니다. 첫 실패의 partial 관측을 최종 성능 개선으로 보고하지 않는다.


## 실제215 재검증과 물리 두 writer 수용

`7651cc39`의 새 owned A215는1개 PASS(console70.59초/XML70.089초)다. 215개 전체의
원 record 보존·head import 시각·14 counter·retired0·필수 후처리와 별도 seal을 확인했다.
논리 예약744,997바이트, artifact735,271바이트/context1,534바이트이며 atomic15.649초,
client 전체40.633초/CPU23.180초다. reader roundtrip2.544초(statement3초/lock1초),
decode0.245초/assessment2.099초다. backend CPU/RSS와 실제 upstream HTTP 성능은 미측정이다.
원 실패를 보존하고 `map432-rest215-r3-root-actual-acceptance.json`으로 새 실행을 구분한다.

같은 source의 별도 물리 두 writer 시험도2개 모두 PASS다(개별15.460초/1.542초).
Airport/Rest backend의 미commit TX가 겹치고 실제 topic blocker를 기다린 뒤 양쪽 결과와
revision·receipt·별도 seal이 보존됐다. SQL CPU 실행의 동시성이나 운영 처리량 증가를
뜻하지 않는다. source2574개/SDK53개/import54와 정확 CID/UUID/global0·볼륨 부재를 확인했다.
원장 `map432-two-writer-root-actual-acceptance-r1.json`에 원8개 산출물의 지문을 검산했다.

B quota/GC 첫 실행은4FAIL/1PASS다. SQLSTATE 뒤 helper에 ExceptionInfo 자체를 전달한
fixture3건과 tracking lineage 잠금 없이 job을 변경한 fixture1건을 분리했다. 실제 SQLSTATE
23514/53000은 도달했지만 원 constraint/GC 후검사는 미도달해 수용하지 않는다. 복구 첫 실행은
backend 종료·rollback·pool 재사용1PASS, lateGeo fixture의 직접 stamp 수정 권한 가드와
뒤따른 active owner로2FAIL이다. SDK0 재개 성공으로 확대하지 않는다. 두 fixture 수정은
기존 guard·한도·제품 코드·검증 단언을 유지하며, 독립 리뷰 뒤 재실행한다.
최종 CI·후보 live/UI·머지·배포와 Common/W/T 후속 전파는 아직 남아 있다.


## quota/GC·복구 fixture 재검증

`b18470d5`의 새 owned quota/GC는5개 모두 PASS(console61.09초/XML60.375초)다.
동일 등록이 잠긴 quota와 무관하게 원 예약을 보존하고, 교차 profile23514·고정 row/byte
한도53000 및 정확 constraint를 확인했다. 초과 시 전체 TX rollback, 실행 중 GC 보존과
정본 FAILURE 후 정확 예약 반환·원 jobs 보존도 통과했다. 원4FAIL/1PASS는 보존한다.
원장 `map432-rest-quota-gc-r3-root-actual-acceptance.json`으로 새 실행을 구분한다.

같은 source의 별도 복구 시험은3개 모두 PASS(console18.57초/XML18.064초)다.
정확 own DB backend 종료 뒤18개 상태표 rollback·pool1 재사용, 적용 전 late Geo stamp
변경 거부, 실제 같은 Dagster run의 postprocessed 원 snapshot SDK0 재개를 확인했다.
이 결과는 Dagster worker OS 프로세스 SIGKILL이나 물리 wire 단절 시험을 뜻하지 않는다.
원1PASS/2FAIL을 보존하며 `map432-rest-recovery-r3-root-actual-acceptance.json`에 분리했다.
각 실행의 원8개 산출물·source2574개/SDK53개와 import52/54를 검산했고,
정확 CID/UUID/global0·소유 볼륨 부재도 확인했다. 제품·guard·자원 한도 변경은 없다.

앞의 실제 PG 시험들은 별도 source/fixture와 목적을 가진다. 기존 generic protocol의
실물 검증과 Rest에 새로 추가한 물리 pair를 구분하며 S5 일곱 시나리오 전체를 이 두
writer 한 시험으로 대체하지 않는다. 원격 CI 및 최종 후보 live/UI와 머지·배포는 계속 남는다.


## 설계 대조에서 찾은 추가 물리 검증

앞의 실제 결과와 별개로 S5의 동일 member 동시 등록, 이전 read와 다른 worker seal 사이
경합과 적용 중 GC의 실제 대기도 물리 barrier 시험을 추가한다. 현재 두 writer의 whole wall은 topic 첫 취득부터
commit까지의 전용 계량이 아니며 CPU/RSS도 미측정이다. 테스트의 정본 SQL 호출 전후와
commit 응답의 시각을 이용한 구간 경계, controlled hold, 정확 own backend·container의
읽기 전용 자원 계측을 보강한다. 기존 가드·한도·정본 제품 경로를 바꾸지 않는다.
이 추가 검증과 최종 CI/UI·머지/배포가 남으므로 T-CWRITE04 전체 완료로 표시하지 않는다.


## 추가 경합·자원 관측 시험의 소스 검토

같은 member의 두 Service 등록에서 immutable1개·quota한번·첫 nonce만 반환, 이전 read 뒤
다른 Service의 seal COMMIT과 실제 claim 거부 사이 SDK0 재개, 적용 중 GC가 정확 writer를
기다리다 own backend 종료 후 입력·예약을 보존하는 세 node를 추가했다. 기존11개 검증 단언과
정본 가드·quota·SQL/pytest 한도는 보존했다. GC 경합의 입력은 fresh이므로 age/lease/running
각 단독 보호는 이전 B5와 구분한다. 세 새 node와 추가 계측은 아직 실제 실행 전이다.

두 writer 시험은 실제 SQL 호출 전후와 coordinator COMMIT ACK의 client 시각, controlled
hold, client process CPU/lifetime RSS highwater를 기록한다. 별도 읽기 전용 sampler는
소유된 정확 CID/두 backend PID와 process start ticks를 고정해 실행 전후 CPU ticks·RSS
표본 및 container CPU/메모리를 구분한다. 두 profile의 baseline/final 확인을 받으며 원
barrier/blocker·30초TX/1초lock·0.8초observer 및 owned150/160/15 한도는 유지한다.
client 관측 구간은 backend의 실제 lock 취득/해제 시각 자체가 아니며, 표본 RSS는 진짜
lifetime peak나 운영 효과가 아니다. 새 handshake가 없는 CI에서는 외부 계측 IO를 수행하지 않는다.

적대 리뷰에서 찾은 계측 JSON 부분 공개와 정리 단계 첫 오류 뒤 회수 누락을 보완했다.
완성 tmp fsync 뒤 단일 publisher가 원자적으로 공개하고, 각 listener/plan/pool 회수를 시도하며
기존 primary 또는 첫 오류 객체를 보존한다. source·정리 fault의 순수 검증과 두 독립 리뷰를
실제 PG·자원 수용으로 혼동하지 않는다. source를 동결한 뒤 세 경합과 계측 양 profile을
각 owned 실행으로 확인하고 최종 CI·후보 UI·머지/배포를 진행한다.

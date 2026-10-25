# Rest431 명시 reader의 첫 source 경계

## 현재 범위

승인된 [431 설계](2026-10-25-rest-area-snapshot-profile.md)를 최종430 후보7f40 위에
상속했다. 이번 source는 새 `RestAreaGeoFacts`와 전용 순수 시험만 추가한다.
SQL/migration·decoder·SD·등록·collector·운영 권한·flag는 아직 연결하지 않았다.
기존 Airport427/430 코드·공통 projection·SDK converter는 변경하지 않았다.

Geo pins domain은 `transport-rest-area-geo-v1`, 지문 framing domain은
`kor-travel-map:transport-rest-area-geo-evidence:v1` 뒤 NUL로 고정한다.
address12개 원필드 순서·dataset/source/record/hash/Feature·정확 NDR 2D POINT4326·
Geo version/data token·called outcome·원 aware clock을 길이 구분 SHA256에 결박한다.
동일 필드라도 Airport 지문과 같지 않다. 지문 자체는 DB 출처/현재 token 권한이 아니다.

원 payload hash는32hex, 최종 Geo digest는64hex다. 정본 Rest dataclass→기존 public
native builder→실 SourceRecord/hash/key로 양성 계약을 확인했다. 외부 tzinfo는
utcoffset hook 전에 거부하고 UTC/fixed offset/정확 Asia/Seoul clock만 지원한다.
기존 Airport API/한도/Geo 모델의 의미는 그대로다.

순수 Geo 새31개+기존 Airport28+Transport native47 합집합106PASS1.61s,
strict mypy1 PASS다. 첫 import 정렬2건의 Ruff 실패는 수정 전 로그로 보존했다.
이 결과는 reader 실행·215 fit·기존 저장 projection 적격성 증거가 아니다.

## 다음 작은 구현

후보 A whole RR를 먼저 구현한다. 신규 Rest 전용 reader는 item256, metadata/encoded
각4MiB를 실험 후보로만 고정하고 statement3초/lock1초 및 전행 거부/EOF를 유지한다.
두 scalar(name/phones)와 나머지23개 원 의미/lineage/clock을 검증하며, 최초 mixed scalar
history는 명시 EX 진단으로 거부한다. raw7은 정본 Rest normalizer와 converter로 복원한다.
새 typed SD의 정확 owner/search_path/PUBLIC revoke/runtime EXEC와 startup signature를
같은 checkpoint에서 배선하며 feature/rawtable 권한은 늘리지 않는다.

W는 신규 Rest codec 및 좁은 private codec primitive만 소유한다. J는431SQL·명시
reader/evidence·전용 시험과 필요한 typed signature metadata를 소유하며 서로 파일을
되돌리지 않는다. SQL 두 source 리뷰 전 실행0이다. 실제 계량에서 A의 문제가 확인되기
전에는 chunk 후보 B를 구현하지 않는다. 등록/수집/후처리·운영 연결은 다음 단위다.

최종 source 검증 로그는 `map431-rest-geo-first-source-r2.log`
(SHAc9b0f04f2225b526f17ff795698ac164ac570c9e646c1396263ec831cccf64e9)이며
Ruff/check-format·strict mypy1·문서13PASS도 확인했다.

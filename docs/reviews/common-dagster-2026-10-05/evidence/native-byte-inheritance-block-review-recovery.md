# Native byte inheritance 하니스 독립 초기 검토

판정: **BLOCK — P2 두 건**. 대상은 ignored `map-native-byte-inheritance.py` SHA256 `a936839febc9446a9e9eaeda22e0e41ff16ac6c6b8cadc0eb81417ceb5744a81`다. 제품 FULL 판정을 변경하지 않는다.

## 직접 재현

1. **P2 — 현재 이미지와 설치 버전 증거가 연결되지 않음**. 24–25행은 현재 named container의 Dagster 버전만 읽는다. 최종 attestation의 image_id와 실제 조회 대상을 비교하지 않는다. 기존·최종 attestation과 native 입력이 모두 정상이고 현재 container가 다른 이미지지만 Dagster 1.13.24인 자체 local mock에서 helper가 PASS를 썼다. 최종 이미지의 설치 버전 증거로 사용하려면 같은 read-only 조회에서 image ID를 버전 조회 전후 확인하고 최종 attestation과 일치시켜야 한다.
2. **P2 — immutable 출력 생성의 TOCTOU**. 26행의 exists 확인과 27행 write_text 사이에 다른 writer가 파일을 만들면 기존 bytes를 덮어쓴다. 자체 메모리 filesystem mock에서 exists는 false였고 write 직전 이전 receipt가 생겼으며, helper가 이를 덮어쓰고 PASS를 썼다. 원자적 exclusive open('x')가 필요하다.

원래 소스는 변경 중인 파일에 의존하지 않도록 본인 cache 사본으로 재구성하고 SHA256이 위 최초 bytes와 정확히 같은 것을 확인한 뒤 mock을 실행했다. 두 mock 모두 실제 SSH·Docker·Git subprocess를 실행하지 않았고 실제 출력 파일도 쓰지 않았다.

## 적절한 범위와 미실행

old image/native receipt와 old attestation의 연결, 설치 source hash dictionary 비교, Common 모듈 hash/commit 비교, Map 전체 diff 중 제품 변경이 API query와 C7뿐인지 확인하는 구조는 적절하다. “이전 실제 이미지에서 native fault 실행, 새 이미지 fault 실행은 주장하지 않음”과 새 API query/C7의 별도 검증 요구도 적절하다. 최초 shlex.join은 고정 Python metadata 명령의 shell quoting을 보존한다.

outer Python compile PASS. 당시 최종 ticks runtime attestation 및 새 inheritance 출력은 ABSENT였다. 운영 입력 생성·원격 호출·fault 재실행·운영 변경은 NOT_RUN. 기존 native PASS 입력의 status/field 구조와 hash만 읽었으며 peer 원문은 읽지 않았다.

이 원문은 이후 수정에 맞춰 덮어쓰지 않는다.

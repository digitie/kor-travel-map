# ADR115 제한 scalar projection 검증

## 적용 범위와 운영 제한

412는 기존 Feature와 기존 primary source/link의 `core.name`, `place.phones`만 지원한다.
불변 정책 header의 명시 rank/normalizer/presence가 모든 연결에 준비되어야 한다. 정책 seed와
운영 활성화는 0건이다. 활성화는 schema 관리자만 할 수 있고 runtime/UI에는 열지 않는다.
일반 수집에 자동 배선하지 않으며 mixed legacy writer 전수 preflight 전 production cutover는
금지한다. 전체 dataset/region 동시 수집 전환 완료가 아니다. Geo·identity/link 변경·retire·merge,
한 source entity가 여러 Feature에 연결된 경우, 이미 활성인 fieldset의 제거/교체는 거부한다.
같은 fieldset의 정책 revision 변경도 새로운 완결 후보 검증을 통과해야 한다.

R1 값 원본/hash/시각과 R2 검증 head/hash/시각을 분리해 carry-forward한다. cross-provider
winner는 조회 도착 시각을 우선하지 않고 명시 rank와 안정 provider/dataset/entity/hash 순서를
사용한다. active override는 effective에 우선하고 최신 base는 따로 유지해 revoke에 사용한다.
유효한 applying TX·manifest·membership·dataset 권한을 확인한 scoped capture/recompute만
옛 전역 fence를 생략한다. head만 바꾸거나 legacy lower provider가 base/effective를 덮으면
같은 transaction의 deferred 정합 검사로 거부한다.

기본 OFF에는 scalar trigger가 없고 기존 base validator도 바꾸지 않는다. 최초 관리자
activation은 EX protocol과 정렬 table locks 아래 trigger를 설치한다. 이후 statement epoch
barrier와 활성 관계에만 queue하는 deferred guard를 사용한다. 활성 상태의 비용이 0이라는
주장은 하지 않는다. 기존 SQL 직접 진입점의 protocol-first 전수 보강은 별도 413 단위다.

## 실제 정확성 검사

소유 UUID/label을 검증하는 PostGIS 컨테이너 한 개씩만 사용했다. 1.5 GiB 메모리·2 CPU·
256 PID 상한이며 공유 DB/운영 DSN/운영 데이터는 사용하지 않았다. 실제 application bootstrap과
정본 runtime ACL reconcile 뒤 fresh runtime pool의 session/current 역할을 검증했다.

- unit 18 PASS, Ruff/strict mypy PASS.
- owned PG 정합성 16 PASS/15.41초: 수집 순서 반전, R1 phone/R2 name, head-only commit 거부,
  explicit null rollback, lower provider legacy stomp 거부, dataset/역할 경계, shared entity 거부,
  Geo 좌표·주소·stamp 보존/변조 거부, override/revoke, old RR epoch 40001, fieldset 변경 원자 거부.
- 정적 migration role gate의 tuple 마지막 RESET을 schema owner SET으로 정산한 뒤
  `tests/lint` 전체 369 PASS/기존 skip 6/29.97초.
- 공식 `test_head_schema_artifact_matches_head`를 실제 head에서 재생성하고 원문 비교하며,
  같은 공식 metadata clean 검사도 수행한다. 로컬에서는 컨테이너 resource bound fixture만
  대체하고 공식 검사 함수/덤프/정규화/role은 재사용한다. 최종 CI는 원래 수집 경로로 확인한다.

초기 실패도 성공으로 합치지 않았다. 첫 migration은 32자 version 열보다 긴 revision명으로
실패해 짧게 고쳤고, 다음은 runtime closed-world table inventory 누락을 정본 metadata/ACL로
수정했다. Geo 검사는 BEFORE 단계의 generated 열 NULL을 입력 변경으로 오판해 실패했고,
직접 쓸 수 없는 generated 열만 비교에서 제외했다. fieldset 축소는 새 완결 정책을 준비하면
성공하던 반례를 실제 재현한 뒤 명시 거부로 수정했다. 각 실패 로그를 보존했다.

## 기본 OFF의 10k 비용 확인

실제 collector benchmark가 아닌 관리자 synthetic DB trigger 비용 검사다. 411과 412의
quiescent master에서 매번 fresh clone을 만들고 각각 3회 실행했다. source entity/record/head,
Feature/place/link/base 7표에 각각 10,000행을 넣고 DML·seal·commit을 나눠 관찰했다.
추가 scalar trigger는 6회 모두 0개이고 기존 validator의 함수 hash는 모두 동일했다.

| median | 411 | 412 |
| --- | ---: | ---: |
| DML 초 | 6.521 | 6.370 |
| seal 초 | 0.770 | 0.752 |
| backend CPU 초 | 7.23 | 7.08 |
| backend RSS 최대 표본 MB | 75.55 | 75.37 |
| AfterTrigger total/used bytes | 286912 / 261688 | 286912 / 261688 |
| WAL insert MB | 49.532 | 49.849 |

1 PASS/60.50초이며 원본은 `audit-reports/2026-10-24-operations/map412-off-cost-attempt1.json`과
같은 이름의 `.log`에 있다. RSS는 peak 전체를 추적한 값이 아니라 세 시점의 최대 표본이고,
shared page가 포함된다. WAL은 cluster insert counter이며 서버 cache도 통제하지 않았다.
따라서 로컬 수치 차이를 운영 ARM CPU/RAM 개선율이나 실제 collector 성능으로 해석하지 않는다.

최종 독립 적대 리뷰 2인과 정확 CI, 상위 native 갱신 진입점의 합집합 수용은 별도 gate다.
Weather·Transport 전파는 Map 실측·정확성 수용 뒤 진행한다.

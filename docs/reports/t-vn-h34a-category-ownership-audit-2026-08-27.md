# T-VN-H34A — MOIS 인허가 분류와 여행 시설 분류의 책임 경계 조사

> 조사 기준: 2026-08-27, Map `origin/main` `fe6b45961dd95721d6e92d51da2c9dd13fd35365`.
> 이 문서는 로컬 source·문서만 읽은 설계 조사다. 운영 DB, canonical CSV, provider 원천 데이터,
> Feature 및 curation link를 읽거나 바꾸지 않았다.

## 결론

`Feature.category`를 MOIS 인허가 업종에서 일괄 또는 사례별로 덮어쓰는 것은 허용하지 않는다.
MOIS의 업종은 인허가 사실의 정본이고, 같은 물리 시설의 여행자용 성격을 완전하게 표현한다는
보장이 아니다. 따라서 `진해보타닉뮤지엄`처럼 공식 curation의 장소명·주소와 연결 자체는 맞지만
인허가 업종이 `rest_cafes`여서 식음 카테고리로 보이는 사례는, 현재 증거만으로는 provider 오류가
아니다.

후속 보정은 다음 두 갈래를 먼저 구분해야 한다.

1. MOIS가 인허가 원문을 잘못 해석한 경우에는 `python-mois-api`에서 원문·모델·slug 의미를
   고친다. Map은 그 public contract를 소비한다.
2. MOIS 인허가 원문은 맞지만 여행 지도에 별도 시설 성격이 필요한 경우에는, Map의 명시적
   **큐레이션/표시 분류 정책**을 별도 설계한다. 이 정책은 source category를 변경하거나
   `python-mois-api` 전용 wrapper·별칭을 만들지 않아야 한다.

현 단계에서 어느 갈래인지 판정할 raw record와 전수 범위가 없다. 그러므로 실제 category 수정,
자동 재분류, CSV 수정, import 실행은 이 조사 범위에 포함하지 않는다.

## 확인한 정본과 의미

| 정본 | 확인한 사실 | H34A에 대한 의미 |
| --- | --- | --- |
| `python-mois-api`의 local catalog | `rest_cafes`는 `식품_휴게음식점 데이터 조회`, `museums_and_art_galleries`는 `문화_박물관 및 미술관 데이터 조회`라는 서로 다른 인허가 서비스다. | service slug는 시설의 관광적 정체성이 아니라 인허가 서비스의 분류다. |
| `kortravelmap.providers.mois` | `PROMOTED_CATEGORY_BY_SLUG`은 `rest_cafes → 02020100`, `museums_and_art_galleries → 01040000`처럼 slug 하나에 category 하나를 고정한다. name·주소·공식 curation 이름으로 source category를 재해석하지 않는다. | 현재 변환은 의도적으로 원천 업종을 보존한다. 특정 시설명을 근거로 이 mapping을 바꾸면 같은 slug의 정상 row까지 바뀐다. |
| `scripts/h25b_verify_links.py` | category 축은 관광 캠페인 link의 명백한 모순을 찾는 **반증** 축이며 writer가 아니다. `02020100`은 그 축에서 모순으로 보고된다. | curation link가 틀렸다는 뜻과 Feature가 실제 시설 성격을 못 담는다는 뜻을 분리해야 한다. |
| `docs/tasks.md`의 H34 처리 이력 | `진해보타닉뮤지엄`은 이름·주소가 맞고 Feature가 하나뿐이라 link를 유지했다. 해결되지 않은 것은 그 Feature의 category다. | H34A는 link 해제나 자동 재연결 task가 아니다. |

## 이번 조사에서 확정한 책임 경계

### 1. provider의 인허가 의미를 Map에서 재정의하지 않는다

`python-mois-api`가 공급하는 service slug와 record field의 의미는 provider가 정한다. Map은
`MoisLicensePlaceRecord` 구조 Protocol을 통해 그 record를 받고, 여행자용 이름 유사도나
curation membership으로 slug를 다시 정하지 않는다. 이는 provider 정합성 1차 책임을 provider에
두는 ADR-044 및 `docs/architecture/provider-contract.md`의 규율과 일치한다.

따라서 다음은 H34A의 해법이 아니다.

- `rest_cafes` 전체를 박물관·미술관·수목원으로 변환하는 변경
- 시설명 keyword를 이용해 MOIS category를 덮어쓰는 Map 내부 변환
- MOIS 전용 physical column, adapter, wrapper, alias의 신설
- H25B link verifier 또는 CSV apply script에 category writer를 섞는 변경

### 2. 여행자용 시설 성격이 필요하면 별도 정책·근거가 필요하다

공식 curation은 사람이 선정한 장소와 Map Feature 사이의 관계를 말할 수 있지만, 그 자체로
source provider의 인허가 category를 변경할 권한이나 근거가 되지 않는다. 여행 지도에서 별도
표시 분류가 필요하다는 결론이 나면, 후속 설계는 최소한 다음을 명시해야 한다.

- 원천 category와 표시/큐레이션 분류의 이름·목적·우선순위
- 어떤 public/curated source가 그 분류를 입증하는지와 변경 이력
- provider 동기화가 원천 category를 다시 적재해도 정책이 손상되지 않는 저장 경계
- public/admin API와 Map UI가 어느 값을 filter·marker·상세 표시에 쓰는지
- 자동 적용 범위, 사람 승인, 되돌릴 수 없는 변경 없이 수행할 preview/receipt

이것은 현재 `Feature.category` overwrite의 작은 bug fix가 아니라 data model·API·운영 정책
결정이다. 실제 설계는 ADR과 별도 Map PR로 진행하고, schema/API 변경이 있으면 Wave 2의
2인 적대 리뷰를 적용한다.

## 아직 확인하지 않은 것과 다음 조사

이번 문서는 운영 데이터에 접근하지 않았으므로 다음을 주장하지 않는다.

- `rest_cafes`에 들어간 문화 시설의 전수 건수 또는 이름 목록
- `진해보타닉뮤지엄`의 실제 MOIS raw record가 source 오류인지 여부
- 표시 분류가 필요한 다른 service slug와 그 우선순위
- canonical CSV 또는 기존 curation import 결과의 현재 운영 반영 상태

H34A의 다음 read-only 단계는 승인된 source snapshot 또는 n150 read-only 경계에서 다음을
재현 가능하게 산출하는 것이다.

1. 공식 curation에 연결된 MOIS Feature 중, 캠페인 성격과 source category가 충돌하는 후보를
   이름·주소·source slug·원천 record reference와 함께 목록화한다.
2. 각 후보를 원천 해석 오류, 정상 인허가이지만 표시 정책 필요, 근거 부족의 셋으로만 분류한다.
3. 첫 두 그룹마다 provider PR 또는 Map 정책 ADR/PR 중 정확한 소유자를 지정한다.

이 산출물은 운영 mutation 없이 끝나야 하며, H34B의 preview → immutable plan → `If-Match` commit
→ public REST/UI receipt와 분리한다. `300` baseline 이전 revision 복구나 일반 application data
무결성 대조는 어느 단계의 완료 조건도 아니다.

## 후속 작업 분리

| 후속 단위 | 시작 조건 | 완료 기준 |
| --- | --- | --- |
| H34A 후보 전수 조사 | 승인된 read-only source snapshot 또는 n150 read-only 접근 | 후보·원천 record reference·책임 경계가 재현 가능하게 기록됨 |
| provider 정합성 수정 | 특정 raw record가 provider 해석 오류임을 확인 | `python-mois-api`의 별도 PR과 Map 소비 검증 |
| Map 표시/큐레이션 분류 설계 | 원천은 정상이나 여행자용 별도 의미가 필요하다고 확인 | ADR, data/API ownership, 2인 적대 리뷰, 구현 PR |
| H34B 운영 import | trusted installer가 현재 후보를 공식 활성화하고 admin write 경계가 준비됨 | preview·immutable plan·commit receipt·public REST/UI 검증 |

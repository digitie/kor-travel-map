# ADR-125 — Feature 대표 원천은 "가장 먼저 붙은 primary 연결"이고, 쓰기와 같은 transaction에서 유지되는 표에서 읽는다

상태: 제안·구현 PR (2026-11-27, 소유자 승인 설계 변경). 배포 뒤 F10 0건·관리자 정렬 실측으로
accepted로 올린다.
부분 대체: `docs/architecture/performance.md` §9.3.3의 "denormalized primary provider/dataset 유지
열은 새로 만들지 않는다"(검토 기록) — 그 문단의 "유지 컬럼 권고"를 채택하되 열이 아니라 표로 둔다.

## 배경

Feature에는 `source_role='primary'` 연결이 여럿일 수 있다(병합으로 보존한 원천). 관리자 목록
(`GET /v1/admin/features`)의 `sort=provider`·`provider_dataset_id` 필터·표시, 공개
`/features/nearby`의 `primary_provider`·`providers` 필터, dedup 검토 목록이 그중 하나를
"대표 원천"으로 골라 쓴다. 규칙은 "head가 가장 최근에 관측된 primary"
(`ORDER BY head.observed_at DESC, sr.imported_at DESC, sr.source_record_key`)였고 읽을 때마다
원천 계보 다섯 표(`source_links → source_entities → provider_datasets → source_entity_heads →
source_records`)에서 다시 골랐다.

prod 읽기 전용 실측(2026-11-27, Feature 44.2만, primary 연결 44.3만):

| 질의 (jit off, 리터럴 계획) | 시간 | 비고 |
|---|---|---|
| `sort=provider` 첫 페이지 (#1561 집합 선택) | 2.7 s (냉 6.5 s) | hash 노드 127 MB, 정렬 50 MB |
| `sort=provider` + `provider_dataset_id`(MOIS 20만) | 2.0~2.4 s | 같은 집합 선택 |
| `sort=name` + 드문 dataset(knps_shelters 22건) | **19~44 s** | `lower(name)` 색인을 걸으며 행마다 대표 원천 LATERAL |
| `sort=name` + 흔한 dataset(MOIS) | 9 ms | |

그리고 규칙 자체가 흔들렸다. primary가 둘 이상인 Feature는 817건(전부 서로 다른 provider 둘·셋 —
박물관 표준데이터+TourAPI 341, 국가유산+TourAPI 194, …)이다. 관측 시각 규칙은 가장 자주 적재되는
쪽(TourAPI, 11-26 관측)을 고르므로 817건 중 729건이 TourAPI였고, 다른 dataset이 적재되면 그쪽으로
바뀐다. 관리자가 provider로 정렬한 목록에서 행이 적재 주기에 따라 자리를 옮긴다. 이 규칙을 쓰기
시점에 유지하려면 **모든 head 관측 갱신**(전량 적재마다 수십만 행 — 가장 뜨거운 쓰기 경로)에
trigger를 걸어야 한다.

## 결정

1. **규칙: 대표 원천 = primary 연결 중 가장 먼저 붙은 것.** `ORDER BY sl.created_at,
   sl.source_entity_key COLLATE "C"`(`pk_source_links`의 둘째 열이라 Feature 안에서 동률 없음).
   관측 시각·record는 보지 않는다. 규칙의 유일한 정의는 view `feature.feature_primary_source_rule`
   (`DISTINCT ON (feature_id)`)이고, trigger·migration backfill·정합성 검사가 모두 그것을 읽는다.
   규칙이 기대는 값은 `source_links`의 (feature, entity, role, created_at)과 불변 식별
   (`source_entities.provider_dataset_id`는 `trg_source_entities_identity_and_seen_at`,
   `provider_datasets.provider`는 `trg_provider_dataset_identity_immutable`이 갱신을 거부한다)뿐이다.
   - 바뀌는 것: 817건 중 730건의 대표 provider(대부분 TourAPI → 박물관 표준데이터·국가유산·MOIS 등
     먼저 붙은 원천). primary가 하나인 44.1만 건(99.8%)은 그대로다.
2. **쓰기 시점 유지는 DB trigger로 한다(코드 경로마다 고치지 않는다).** `source_links` 쓰기는
   Python repo(적재·병합·테마 부착), SQL procedure(소유자 넷 — `curation_command_owner`의
   `UPDATE(feature_id)`, `manual_provider_dedup_procedure_owner`의 `UPDATE`, `feature_state_procedure_owner`의
   `UPDATE(source_entity_key)` …), `features` 삭제의 FK cascade, migration에 흩어져 있다. 경로마다
   "같은 transaction에서 대표를 다시 계산"을 심으면 정본이 경로 수만큼 생기고, 새 경로가 빠뜨리면
   조용히 어긋난다. trigger는 모든 경로(replica 역할 포함 — `ENABLE ALWAYS`)를 한 정의로 덮는다.
   - `source_links` 문장 trigger 셋(INSERT·UPDATE·DELETE, transition table)이 **primary 연결이
     실제로 바뀐** Feature만 모은다. UPDATE는 규칙이 보는 열이 바뀐 행만 센다 — 적재의 같은 값
     upsert·`confidence`만 바뀐 갱신·enrichment 연결 쓰기는 사본을 건드리지 않는다.
   - `features` 행 trigger(INSERT·DELETE)는 사본 행의 생성·삭제만 한다(새 Feature는 아직 연결이
     없다). TRUNCATE trigger 둘이 정리 경로를 맞춘다.
   - 재계산 함수 `feature.refresh_feature_primary_sources(uuid[])`(`SECURITY DEFINER`, PUBLIC 실행권
     회수): ① 사본 행 보장 ② 그 행들을 `feature_id` 순서로 `FOR UPDATE` ③ 사라진 Feature 행 삭제
     ④ **새 문장(새 snapshot)**에서 규칙을 다시 계산해 다른 값만 갱신. ②가 ④ 앞이라 같은 Feature의
     서로 다른 연결을 두 transaction이 함께 바꿔도 뒤에 온 쪽이 앞의 commit을 기다렸다가 그것을 보고
     계산한다(READ COMMITTED에서 여러 행에서 유도한 값의 write skew를 막는다 — 시험
     `test_concurrent_link_writes_on_one_feature_serialize`). REPEATABLE READ 이상의 writer는 ②에서
     직렬화 실패(40001)로 끝난다 — 어긋난 값을 남기지 않는다.
   - 잠금 순서: 사본 행은 **잎(leaf) 잠금**이다. trigger가 원본 쓰기 문장의 끝(그 문장이 잡을
     잠금을 다 잡은 뒤)에서 잡아 commit까지 쥔다. 사본 행을 잡는 것은 이 trigger들뿐이고 한 문장
     안에서는 `feature_id` 순서라 trigger끼리 한 문장으로는 교착하지 않는다. 사본 행 대기는 같은
     Feature의 primary 연결을 두 transaction이 동시에 바꿀 때만 생긴다. 새로 생길 수 있는 교착은
     하나 — 두 transaction이 **여러 문장에 걸쳐** 공통 Feature 둘 이상의 primary 연결을 반대 순서로
     바꿀 때다(종전에는 서로 다른 연결 행이면 막히지 않았다). PostgreSQL이 40P01로 한쪽을 끝내므로
     틀린 값은 남지 않는다. 그런 동시 쓰기는 이미 Feature 쓰기 잠금(`feature-write:<id>`·ADR-111
     gate·ADR-115 범위 잠금)이 차례로 세우는 경로들이라 실제로 마주칠 모양은 아니다 — 배포 뒤
     40P01 로그로 확인한다.
3. **열이 아니라 표다.** `feature.features`에 열을 두면 ① `trg_features_row_revision`이 모든
   UPDATE에서 `row_revision`(ETag·`If-Match`, ADR-109·119의 지문 축)을 올린다 — 원천 연결 변경이
   Feature 내용 변경으로 보여 관리자 편집이 409를 맞고 PinVi 조정이 흔들린다. ② 연결 쓰기마다
   `features` 행 잠금을 새로 잡는다(지금 연결만 쓰는 경로가 있다). ③ 넓은 `features` heap(379 MB)에
   색인 둘을 더해 갱신의 HOT 여지를 줄인다(T-READ-07). 455(`feature_cluster_points`)가 같은 판단으로
   좁은 파생 표를 택했다. Feature당 한 행이라 관리자 목록은 내부 조인으로 걷는다(빠진 행은 F10이
   잡는다).
4. **표 `feature.feature_primary_sources`**: `feature_id uuid PK, source_entity_key, provider_dataset_id,
   provider`(원천이 없으면 셋 다 NULL — CHECK). `provider`는 정렬 색인을 위한 정본 사본이다(식별 불변).
   표시용 `dataset_key`는 정본 `provider_datasets`에서 조인한다. FK는 두지 않는다(purge 증거 포획이
   `features` 자식을 훑는다 — 455와 같다).
   - 색인 `idx_feature_primary_sources_provider_keyset ((COALESCE(provider, '')), feature_id)` —
     `sort=provider` keyset(정렬 키·동률 깨기 둘 다 색인 열). 목록 SQL은 이때 `ps.feature_id`를 id로
     내보내 keyset 행 비교가 색인 열 그대로다.
   - 색인 `idx_feature_primary_sources_dataset (provider_dataset_id, feature_id)` — dataset 필터.
5. **읽기는 사본만 본다(규칙을 다시 계산하는 곳이 없다).** 관리자 목록(키 단계 정렬·필터, 꾸밈
   단계 표시), nearby(page 행 표시·`providers` 필터), dedup 검토 목록 둘(`psa`·`psb`). 공용 조각은
   `kortravelmap.infra.primary_source`. 관리자 상세의 원천 목록 순서(primary 먼저·관측순)는 "대표"가
   아니라 전체 원천의 나열이라 그대로 둔다. 지도 bbox의 `providers` 필터는 "primary 중 하나라도"라는
   다른 뜻이라 그대로 둔다.
6. **정합성 검사 F10**(ERROR, `infra.consistency`): 사본과 규칙 view를 전수 대조한다 — 사본 행이
   없는 Feature, 고아 사본 행, 값이 다른 행. trigger가 같은 transaction에서 맞추므로 정상이면 언제나
   0이다(F3과 같은 파생 상태 신뢰 관측). prod 규모 합성 자료에서 3.2 s.
7. **migration 459는 한 transaction이고, 쓰기를 막는 창을 따라잡기 한 번으로 줄인다.**
   ① 표·view·함수·색인(뜨거운 표 잠금 없음) → ② trigger 없이 5만 행 조각 backfill(`features`·
   `source_links`는 읽기만 — 적재 계속) → ③ trigger 생성(`SHARE ROW EXCLUSIVE`, `lock_timeout` 5 s —
   진행 중 적재가 있으면 통째로 되돌아가고 다시 돌린다) → ④ 같은 조각으로 따라잡기(②동안 생긴 새
   Feature·지운 Feature·바뀐 연결). 쓰기 대기는 ③~commit뿐이고 읽기는 막지 않는다. 조각은 문장
   하나의 메모리·시간을 묶는다(prod 규칙 전체를 한 번에 계산하면 정렬이 worker마다 83 MB를 디스크로
   흘렸고, 5만 행 조각은 3 MB quicksort다). 이 저장소 migration은 한 transaction이라(447 설명 — 중간
   commit은 재시도 불가한 반쪽 상태) autocommit 조각 commit은 쓰지 않는다.

## 대안

- **관측 시각 규칙을 그대로 유지**: `source_entity_heads` UPDATE마다 trigger(전량 적재마다 수십만 행),
  817건의 대표가 적재 주기에 따라 계속 바뀐다. 기각.
- **쓰기 경로마다 애플리케이션이 같은 transaction에서 갱신**: 정본이 경로 수만큼 생기고 SQL
  procedure 네 소유자·FK cascade까지 고쳐야 한다. 새 경로가 빠뜨리면 조용히 어긋난다. 기각.
- **`features`에 열**: 위 결정 3. 기각.
- **materialized view + 주기 refresh**: stale 창이 생기고(관리자가 막 병합한 Feature가 옛 대표로 보임)
  refresh job이 하나 더 는다. 기각.
- **`provider_dataset_id`만 저장하고 정렬 때 provider를 조인**: 색인이 provider 순서를 못 낸다(80개
  dataset의 provider 순서는 id 순서가 아니다). 기각.

## 결과·측정

prod 규모 합성 자료(Feature 44.2만, 실제 dataset 분포, 원천 없는 91건·primary 둘 817건, 로컬 PG18
testcontainer, work_mem 64 MB, jit off, 같은 질의를 옛 코드와 새 코드로 렌더링) — 수치는 journal
2026-11-27 절이 정본이다.

| 질의(첫 페이지 51행) | 옛(#1561) | 새 | 비고 |
|---|---|---|---|
| `sort=provider` asc | 7.6 s, 정렬 87 MB | **3.9 ms**, 25 kB | 색인 keyset, 버퍼 읽기 0 |
| `sort=provider` desc | 7.6 s | **2.5 ms** | 같은 색인 역방향 |
| `sort=provider` 22만 번째 행 cursor | 5.6 s | **3.0 ms** | keyset 행 비교가 색인 열 |
| `sort=provider` + MOIS(20만) 필터 | 3.6 s | 298 ms | dataset 색인 → top-N 정렬(아래 남은 일) |
| `sort=name` + 드문 dataset(22건) | **28.8 s** | **2.1 ms** | dataset 색인 → 22행 정렬 |
| `sort=name` + MOIS 필터 | 10.6 ms | 3.8 ms | |
| `sort=name` 무필터 | 5.0 ms | 3.2 ms | 회귀 없음 |
| `sort=kind` | 128 ms | 127 ms | 대표 원천 무관 — 회귀 없음 |

정합성 검사 F10 전수 3.2 s, 0건. 사본 표(heap+색인 셋)는 추정 약 100 MB다(시험 상자 실측 244 MB는 같은 transaction의 삭제·재삽입
bloat를 포함한다).
같은 상자에서 통합 시험이 함께 돌아 절대값은 흔들린다 — 옛/새 비율이 판단 근거다.

쓰기 비용(같은 자료):

| 쓰기 | trigger 없이 | trigger와 | 비고 |
|---|---|---|---|
| primary 연결 44.2만 행 INSERT(한 문장) | 101 s | 89 s | 사본 44.2만 행 갱신 포함 — 차이가 잡음 안 |
| 같은 값 UPDATE 21.6만 행(적재 upsert 모양) | 47.5 s | 26.7 s | 규칙 열이 안 바뀌면 사본을 안 건드린다 |
| `created_at` 바뀐 UPDATE 5만 행 | 6.3 s | 11.2 s | 바뀐 primary 연결 하나당 약 0.1 ms |

(시험이 함께 돈 상자라 앞의 두 줄은 잡음이 차이보다 크다 — 비용은 "규칙이 실제로 바뀐 Feature 수"에
비례하고, 같은 값 적재에는 transition table 비교만 남는다.)

## 남은 일

- `sort=provider` + 큰 dataset 필터(MOIS 20만)는 298 ms다 — dataset 안에서는 provider가 하나라 정렬이 사실상
  `feature_id` 순인데 planner가 dataset 색인으로 20만 행을 모아 top-N 정렬한다. 필요하면 키 단계에서
  필터가 있을 때 정렬 키를 `(provider_dataset_id, feature_id)` 색인 순서로 바꾼다(같은 결과). 지금은 종전
  3.6 s보다 빠르므로 두었다.
- `issue_count` 정렬·`has_issue` 필터의 쓰기 시점 유지는 하지 않았다(#1561 뒤 prod 0.55 s, 열린 이슈
  1,768 Feature). 이슈 표 trigger로 같은 모양이 가능하나 이슈 상태 쓰기 경로(검출 job·관리자 종결)가 다르고
  효과가 작아 별도 결정으로 남긴다.

## 배포

migration 459를 싣는 API 이미지 회전(entrypoint가 `alembic upgrade head`). OpenAPI 변경 없음.

- 시간 추정(prod): backfill 조각 9개 — prod에서 조각 하나의 규칙 계산 0.29 s(읽기 전용 실측), 삽입
  포함 합 5~8 s(쓰기 막지 않음). 따라잡기 3~5 s — prod 조각 규칙 계산 0.29 s × 9에 사본 비교를 더한 추정(합성 자료·부하 상자에서는
  17 s였다. 이 동안 `features`·`source_links` 쓰기만
  대기). 전체 10~20 s.
- 잠금: ③부터 commit까지 `features`·`source_links`에 `SHARE ROW EXCLUSIVE` — 읽기(공개·관리자
  조회)는 막지 않고 쓰기(적재·병합·관리자 편집)만 기다린다. 적재 큐·Dagster run이 도는 중이면
  ③이 5 s 안에 잠금을 못 얻고 migration 전체가 되돌아간다 — 적재를 멈춘(또는 빈) 창에서 회전한다.
- 확인: 회전 직후 관리자 정합성 검사(F10 0건), `GET /v1/admin/features?sort=provider` 첫 페이지·깊은
  페이지·`provider_dataset_id`(드문 dataset) + 이름 정렬이 100 ms 안쪽인지, n150 API 로그의
  `slow_request route=/v1/admin/features`.
- 되돌리기: forward-only. 표·trigger를 걷는 것은 forward revision이다(옛 코드는 표를 읽지 않으므로
  이미지만 되돌려도 동작한다 — trigger는 남아 사본을 계속 맞춘다).

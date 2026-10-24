# 국가유산 native 수집의 적격성 선행 계약(A1)

## 범위

국가유산 본체는 public `HeritageKey.natural_key`(종목·지정번호·시도)를 source identity로
쓴다. MCST의 이름·주소 기반 identity와 달리 일반 이름 변경을 같은 원천으로 비교할 수 있다.
기존 converter signature·실수집 호출·SQL·정책·Geo·whole-TX snapshot seal은 바꾸지 않는다.
명시 name presence와 pure 진단만 추가한다. 실제 collector 배선/동시쓰기 완료가 아니다.
운영 flag OFF/정책 seed0/운영 변경0을 유지한다.

`heritage_items_to_bundles`가 검증한 이름만 `core.name` supplied로 선언하고
`krheritage-name-v1` revision을 붙인다. 전화·주소·파생 category/marker·기본 None의 존재를
추정하지 않는다. 행사 변환기는 이 name presence를 받지 않는다.

## 저장 projection 복원

`rebuild_heritage_projection`은 provider HTTP facade나 범용 호출 전달 wrapper가 아니다.
Map이 이미 저장한 flat typed projection의 복합 key3개·manager를 public DTO 입력의
중첩 key·owner로 되돌리는 Map 전용 seam이다. caller는 정본 public
`HeritageDetail.model_validate`를 직접 넘긴다. parser/XML/발표 시각을 새로 구현하지 않는다.

기존 public converter를 다시 호출하여 원래 raw/hash/source key/entity가 정확히 일치하는지
확인한다. 필드 전수/스칼라 type/1MiB·좌표 유한성/완전한 composite key를 먼저 검증하므로
unknown/deep/과대 raw를 조용히 버리지 않는다. 기본 place projection 이외의 GIS 확장 필드는
거부한다. 원 source의 fetched/imported clock은 반환 bundle에 그대로 보존한다.

Geo 증거는 caller가 별도 확보한 old/new 모드·token·Address·stamp 지문을 받는다. resolved는
이 네 증거가 완전해야 하며 모두 같아야 한다. not_requested는 실제 Geo 미요청 경로만 뜻한다.
증거 누락을 not_requested로 꾸며서는 안 된다. 실제 bundle의 GeoAttempt/AdminEvidence/
files가 있으면 거부한다. 이 pure 입력은 DB 권한/실제 stamp 조회를 증명하지 않는다.

## 적격성 판정

`assess_heritage_name_refresh`는 이전 normalizer revision을 알아야 하며 current bundle도
같은 raw를 정본 converter로 복원한 출력이어야 한다. current name/alias 등을 임의 변경하면
거부한다. 비교는 현재 effective Feature 대신 이전 provider projection을 재정규화한 값이다.
따라서 override/다른 source winner에 가려진 변화를 안전하다고 오인하지 않는다.

이전·현재 사이에 허용하는 것은 이름과 새 관측 감사 시각 차이뿐이다. 비교에서 명시 분리하는
감사 시각은 Feature.created_at/updated_at, SourceRecord.fetched_at/imported_at,
SourceLink.created_at이다. raw/key/hash는 별도 검증한다. 파생 alias는 Feature.feature_id,
place detail.feature_id, SourceLink.feature_id 세 곳을 명시 분리하되 실제 category/주소/kind/
parent/marker/subtype/link 속성은 전수 비교한다. canonical UUID/claim/membership/epoch는
적용 TX에서 반드시 다시 검증해야 한다.

이름 외 저장 raw projection도 그대로여야 한다. 첫 회귀에서 원천 주소가 달라도 동일 Geo가
최종 DTO 주소를 덮어 가리는 반례가 1FAIL/87PASS로 발견되어 보완했다. 이름에 왕릉 키워드가
생겨 category/marker/alias가 함께 바뀌면 부적격이다. 이미지가 있으면 alt_text도 이름에
의존하므로 현재 한정 helper 범위에서 부적격이다. 미지원 변화는 legacy loader로 자동 fallback
하지 않는다. active policy에서는 동일값 link UPSERT도 거부되는 기존 계약을 유지한다.

결과의 eligible은 비교 진단일 뿐 apply 승인이 아니다. `requires_database_verification=True`,
`collector_ready=False`를 항상 유지한다. 내구 fetch artifact, 실제 SDK/Geo context 영속화,
동일 의미 EX 경로, full field/Geo/file/link/create·root retire/seal 지원은 별도 후속이다.

## 확인한 증거와 남은 gate

- 전용 WT에서 codegraph 최초 init을 수행했고 converter 영향도25개를 확인했다. 공유 index는
  변경하지 않았다. dynamic `_transform_reusing_geo`→converter actual asset은 직접 정적 대조했다.
- 신규 pure 진단·기존 converter·실 SDK 모델/Map fetcher 계약을 같은 최종 실행에서
  **90 PASS/1.63초** 확인했다. public SDK는 pyproject 정본 pin
  `e1b346f70dd90f68247776fe14ad39b0a90db763` 고정 archive와 의존성을 `/tmp` 전용
  target에 설치했다. 공유 venv는 변경하지 않았다. public model은 실제 실행하고 fetcher는
  기존 public search/list/details service fixture 경계를 대체했다. 외부 HTTP/DB는 0이다.
- 기본 CI는 provider extra를 설치하지 않으므로 SDK 계약 모듈은 명시 skip한다. 이를 SDK
  성공으로 세지 않고 위 고정 provider 설치 실행을 별도로 수용한다. Protocol 단위는 기본
  CI에서도 실행한다. 인벤토리/Protocol lint는27 PASS/기존 sibling 부재1skip이다.
- import 오류(ProviderFieldPresence 경로), 시험 Settings import 오류 등 선행 실패도 실제
  실행 전에 수정했다. 앞선 checkpoint의 SDK 의존성 부재를 이번 정상 설치 검증과 섞지 않는다.
- strict mypy2개·Ruff는 통과했다. 전체 lint/import 계약·정확CI·독립2리뷰는 진행 중이다.
  실제 PG/HTTP/UI/worker 복구/운영 활성화를 이번 pure 계약 증거로 대체하지 않는다.

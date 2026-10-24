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
  **98 PASS/1.54초** 확인했다. public SDK는 pyproject 정본 pin
  `e1b346f70dd90f68247776fe14ad39b0a90db763` 고정 archive와 의존성을 `/tmp` 전용
  target에 설치했다. 공유 venv는 변경하지 않았다. public model은 실제 실행하고 fetcher는
  기존 public search/list/details service fixture 경계를 대체했다. 외부 HTTP/DB는 0이다.
- 기본 CI는 provider extra를 설치하지 않으므로 SDK 계약 모듈은 명시 skip한다. 이를 SDK
  성공으로 세지 않고 위 고정 provider 설치 실행을 별도로 수용한다. Protocol 단위는 기본
  CI에서도 실행한다. 인벤토리/Protocol lint는27 PASS/기존 sibling 부재1skip이다.
- import 오류(ProviderFieldPresence 경로), 시험 Settings import 오류 등 선행 실패도 실제
  실행 전에 수정했다. 앞선 checkpoint의 SDK 의존성 부재를 이번 정상 설치 검증과 섞지 않는다.
- 최종 합집합 strict mypy3개·Ruff·import4를 확인했고 정확CI·독립2리뷰는 진행 중이다.
  실제 PG/HTTP/UI/worker 복구/운영 활성화를 이번 pure 계약 증거로 대체하지 않는다.

## 두 적대 리뷰 경계의 보완

첫 fbff 후보는 current link의 record key를 의미 비교에서 분리했기 때문에, 잘못된 link key도
canonical 진단에서 놓쳤다. source link key/Feature alias가 current record/Feature와 정확히
일치하는지 별도 검증했다. current DTO 전체의 임의 detail payload도 raw 검사만으로는
제한되지 않아 `model_dump` 전에 shallow Pydantic 순회로 입력 총1MiB·8192노드·깊이64를
검사한다. 노드/JSON 구분자 예산은 보수적으로 계산한다. over-budget/deep/unknown object·
비유한 값은 거부하며 shared infra를 import하거나 whole DTO를 먼저 복사하지 않는다.

수정 전 old/타 record link 및 deep/node/byte 세 가지 복사 전 거부 회귀는 **4 FAIL/0.96초**였고
원로그를 보존했다. 당시94개 실행에 같은 회귀를 포함했다. 이 문제는 pure 진단의 정합성과
자원 제한 문제이며 실제 collector/DB 오류를 새로 관찰한 것으로 표시하지 않는다.

작업 후 journal/resume와 내부 변경 CHANGELOG를 추가했다. A1 단독에서는 cap 안이었으나
검토된 EX 부모 dcb92934를 합성하면 journal225349B로225280B를 넘었다. tasks-rule§8에 따라
2026-10-01 가장 오래된 한 절5764B를 journal-2026-10a.md로 원문 이동했다. SHA256은
`ffe1b6c06892402d17b38e34fd511c358fd7be7c0e0acf2460d0d9bdc6bdb58d`이며
본문 원문/상대 링크 변경0이다. 절 뒤 빈 분리줄1B는 live에 유지해 부모 전체를 복원할 수 있다. 양쪽 상단·기존 본문·CHANGELOG 항목을 모두 보존했다.
EX 소스/시험/report는 dcb 부모 blob 그대로이며 이 합성이 EX 개별 CI/UI gate를 대신하지 않는다.


추가 root 리뷰에서는 plain Enum.value의 과대 객체와 model_copy의 미선언 필드가 첫 guard를
우회하는 경계를 발견했다. 두 반례는 수정 전 **2 FAIL/0.93초**로 보존했다. Enum.value도
같은 walker에서 제한하고, BaseModel의 공식 iterator를 lazy하게 직접 순회해 실제 push마다
남은 노드/stack 예산을 확인한다. dict(model) 전체 복사는 제거했으며 미선언 필드는 첫 발견에
거부한다. 당시96개 실행은 이 두 반례를 포함했고 이전 수치와 합산하지 않는다.

추가 자유 payload의 외부 BaseModel computed field/serializer가 사전 검사 뒤 과대 문자열을
만드는 반례도 **2 FAIL/0.92초**로 보존했다. 이 진단이 실제 사용하는 정본 DTO 9개만
class identity로 허용하여 임의 모델·그 하위 클래스는 model_dump 전에 거부한다. module
prefix를 신뢰 경계로 쓰지 않는다. 최종98개는 두 직렬화 반례에서 serializer 미실행을 확인한다.
이 검사는 JSON 표현의 형태·타입과 정본 DTO 입력 한계를 검증하며, 악의적인 Python 런타임
전체를 sandbox하거나 monkeypatch를 방어한다는 보장은 아니다.

기존 native artifact의 별도 `_check_artifact_budget`에는 Enum.value와 BaseModel 사전
복사 예산의 후속 검토가 남는다. root의 Enum 과대값 실제 반례가 확인됐고 직렬화 후1MiB만
보장하므로 기본 OFF를 유지하며 운영 opt-in 전 반드시 수정·수용해야 한다. A1의 model_dump와
native의 dict+JSONEncoder 방식은 달라 이 변경에서 guard를 무작정 공용화하거나 수정하지 않았다.

최종 EX 부모와의 집중 실행은 **114 PASS/28.98초**이며 A1·고정 SDK98개와 기존 native/EX16개를
같은 실행에서 확인했다. native/EX의 실제 PG는 2CPU/1.5GiB 제한 소유 fixture를 사용했고
실행 후 해당 scalar fixture 잔존0을 확인한다. A1 pure 진단이 새 실제 collector 경로를 실행한
것은 아니다. 외부 provider HTTP/운영 호출은0이며 EX의 별도 CI/UI gate를 대체하지 않는다.

합집합 전체 lint와 archive 링크는 **377 PASS/기존6skip/29.57초**다. 최종 문서 변경 후
문서 상한·redaction·archive 링크를 다시 확인한다. 정확 CI/두 최종 리뷰는 별도 대기다.

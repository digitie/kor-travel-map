# 제한된 현재 입력집합 capture(428, 구현 중)

## 범위와 상태

기존 `current_provider_curation_input_set`의 네 집계값과 hash/date/정렬 계약을
보존하면서, 전체 현재집합이 작은 안전한 형태인지 먼저 검사하는 내부 함수를 추가한다.
이 checkpoint는 설계·진행 문서만 공개한다. SQL·migration·시험 코드는 작업 중이며
아직 source review/실제 PostgreSQL/공식 oracle/CI 수용 전이다. 427 reader를 부모로
예약했으며 부모 migration을 상속하기 전 전체 graph와 실제 DB 시험을 실행하지 않는다.
새로운 공개 API/DTO나 collector 호출, RC 전환, SH 활성화는 없다.

## 검사 순서와 예산

동일 statement snapshot에서 payload를 읽지 않는 관계 열기, 정확 heap/상속 및
feature_places의10열 catalog 확인, MAX+1 수량, 가변열 storage metadata, 개별 형태,
개별 encoded 행과 전체 encoded 크기, 마지막 정본 aggregate 순서다. 현재 entity는
1..2730개, 저장 가변열 합256KiB, 행 encoded256KiB, 전체 encoded1MiB를 넘으면
전체 거부한다. 빈 집합이나 일부 membership/lineage 누락도 성공으로 포장하지 않는다.

압축된 가변열은 거부한다. text는256 UTF8바이트, phones는1차원/lower1/32개 이하,
각 원소256바이트, 전체8KiB다. business_hours는SQLNULL만 지원한다. 나머지 세 JSON은
각8KiB 이하의 object이며32키 이하, key와 string 값은각256바이트, 값은 string 또는
JSONnull만 지원한다. 숫자·bool·배열·중첩 object를 text로 확장하지 않는다.

대상은 active place와 단일 primary/all-role link다. 다른 subtype, 공유 Feature,
존재하는 모든 operator override는 거부한다. 실패는 이유와 NULL 집계4개로 돌려준다.
성공값은 기존 canonical 함수를 그대로 호출한 네 값이다. STABLE의 snapshot 일관성은
외부 수집 EOF, provider 전체성, 입력과 DB의 동등성, P/L 이후 fresh RC 검증 또는
쓰기 권한을 증명하지 않는다. index 비교·실행계획·DB 전체 작업 메모리의 엄격 상한이나
실측 RSS 개선을 이 예산으로 주장하지 않는다.

## 권한과 검증 계획

새 함수는 schema owner의 고정 search_path SD이며 curation command owner만 호출한다.
내부 JSON helper는 runtime/PUBLIC에 공개하지 않는다. metadata helper의 필요한 owner간
EXECUTE만 추가한다. 기존 raw table 권한, 정본 함수 본문과 호출자는 보존한다.

설계 r6는 두 독립 검토를 통과했다. migration fake-bind 시험16 PASS/0.42초는
P-first, 의존 함수 지문/속성 확인, 유한 timeout과 원 설정 복원만 검증한 단위 결과다.
실제 PG 성공이나 메모리 개선 증거로 합산하지 않는다. 구현 후 정상 네 값 일치,
압축/숫자 확장/형태·수량·예산·catalog·override 거부, 실제 LOGIN 권한과 공식 schema
oracle을 확인하고 두 적대 리뷰 및 정확 head CI를 통과해야 한다.

후속 전체 caller/엄격 SH guard/부모 잠금 순서/내구성 복구와 두 실제 수집기 동시
apply·finish는 아직 미완이며 Common·Weather·Transport 전파도 그 수용 이후다.

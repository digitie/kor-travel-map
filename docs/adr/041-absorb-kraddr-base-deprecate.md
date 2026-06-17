# ADR-041: `python-kraddr-base` 코드 본 라이브러리로 흡수 — kraddr-base 폐기 예정

- **상태**: accepted (PR#33, 2026-05-27)
- **날짜**: 2026-05-27
- **결정자**: 사용자

### 컨텍스트

ADR-023에서 `python-kraddr-base.categories` 모듈을 `kortravelmap.category`로
이전 완료(PR#18). 다른 kraddr-base 모듈(`address`, `domain`, 일부 utility 함수)
도 본 라이브러리 외에 사용처가 없거나 적음. `python-kraddr-base` 자체를 폐기하고
필요한 코드만 본 라이브러리로 흡수.

**중요 제외**: `PlaceCoordinate`는 본 라이브러리의 `dto/coordinate.py` `Coordinate`
와 책임 중복 + EPSG/Decimal 처리 정책 충돌 → **가져오지 않음**. 호출자 측에서는
`kortravelmap.dto.Coordinate`만 사용.

### 결정

- **흡수 대상**(예시, 실 작업 시 kraddr-base 전수 survey 후 PR 단위):
  - `kraddr.base.address` — `Address` 모델 + 한국 주소 정규화 helper. 본 lib
    `dto/address.py`와 머지(필요 필드만 추가).
  - `kraddr.base.domain` — 도메인 분류 enum/helper. `category` 모듈에 흡수
    or `dto/_enums.py`로.
  - utility 함수(예: `kraddr.base.utils.normalize_bjd_code`,
    `clean_phone_number` 등) — `core/normalize.py` 또는 `core/strings.py`
    신규 모듈로.
- **제외 대상**:
  - `PlaceCoordinate` — `kortravelmap.dto.Coordinate`로 단일화. 호출자가
    명시적으로 ergonomics에 맞춰 변환.
- **`python-kraddr-base` 라이브러리는 본 흡수 PR이 모두 머지된 후 GitHub
  repo archive**. v2 마지막 release에 deprecation note.

### 근거

- kraddr-base는 현재 본 라이브러리 + TripMate apps 외 호출자 없음 → 별도
  유지비용 회피.
- 코드 흡수 시 import 경로가 짧아짐 (`from kortravelmap.core import normalize_
  bjd_code` vs `from kraddr.base.utils import normalize_bjd_code`).
- `PlaceCoordinate`를 가져오지 않는 것은 단일 책임 — 좌표 DTO는 본 lib가
  source of truth.

### 결과 (긍정)

- 외부 의존 패키지 1개 감소 → install / version pinning 단순화.
- 본 라이브러리 안에서 한국 주소/좌표/도메인 helper가 한곳에 모임.

### 결과 (부정)

- 흡수 PR이 코드 옮김 + import path 변경 + 테스트 회귀까지 포함 → 큰 PR.
- 완화: 모듈 단위로 PR 분할 (address PR / domain PR / utils PR).

### 후속

- `python-kraddr-base` 저장소 전수 survey PR(Sprint 4 진입 prep).
- 흡수 모듈 단위 PR 3~5건 (`docs/kraddr-base-absorption.md`로 추적).
- `python-kraddr-base` deprecation note + archive (Sprint 5 종료 시).
- `pyproject.toml` `python-kraddr-base` git URL 제거 (마지막 흡수 PR과 함께).
- `docs/kraddr-base-types.md` superseded note.

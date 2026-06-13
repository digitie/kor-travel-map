# cross-repo 정합성 audit 체크리스트 (분기 1회, T-217d)

TripMate 생태계 4-repo(kor-travel-map · TripMate · kor-travel-concierge ·
kor-travel-docker-manager)의 계약/문서 drift를 분기 1회 점검한다. 2026-06-10 검토에서
드러난 사고 패턴("krtour HTTP 미존재" stale 전제, batch `items` vs `found`,
admin base 12705 오인)의 재발 방지가 목적. 연동 지도 정본은
[`../integration-map.md`](../integration-map.md).

## 0. 준비 — stale 함정 회피 (필수)

- [ ] 각 형제 repo에서 `git fetch origin` 후 **origin/main 기준으로만** 실측한다.
      본 체크아웃 working tree는 수일~수주 stale할 수 있다(검토에서 133커밋 사고).
      대량 열람은 `git worktree add <tmp> origin/main --detach` → 끝나면
      `git worktree remove --force`.
- [ ] 산출(보고/이슈)에 각 repo의 **기준 commit hash**를 명기한다.

## 1. 계약 — 코드↔코드 대조

- [ ] **TripMate client ↔ krtour OpenAPI**: `apps/api/app/clients/kor_travel_map.py`의
      경로/파라미터/응답 파싱을 `openapi.user.json`과 대조 — 특히 batch `found`,
      in-bounds `max_items`, `meta.page.next_cursor`, problem+json `code`.
- [ ] **krtour fetcher ↔ kor-travel-concierge export**: `provider_fetchers.py`의
      경로(`/api/v1/features/*`)·`X-API-Key`·`{items,next_cursor,has_more}`·limit
      상한(agent `FEATURE_EXPORT_LIMIT_MAX`=krtour `kor_travel_concierge_feature_page_size`
      le)을 agent `routes.py`+`feature_export_service.py`와 대조. item 스키마
      (place/youtube/evidence/source_record + operation enum)와 상수 3종
      (provider/dataset_key/source_entity_type) 문자열 일치 확인.
- [ ] **포트/베이스**: TripMate env 기본값이 admin **API=12701**(12705는 UI)을
      가리키는지, agent/manager 포트가 integration-map §1과 일치하는지.
- [ ] **인증 헤더**: `X-Kor-Travel-Map-Service-Token`(krtour batch) / `X-API-Key`(agent) /
      kill-switch(admin) 사용처가 integration-map §3과 일치하는지.

## 2. 문서 — 전제 신선도

- [ ] 각 repo의 통합 문서 머리말이 "정본 링크 + view" 선언을 유지하고, 본문에
      제거된 경로/필드(`/tripmate/*`, `data.next_cursor`, batch `items` 등)가
      되살아나지 않았는지 grep.
- [ ] "상대 repo에 X가 없다/대기 중" 류 전제 문장을 전수 찾아 origin/main으로 재검증
      (DEC-01류 — 가장 흔한 drift).
- [ ] 외부 추적 task의 짝: 한 repo가 "외부"로 둔 task가 상대 repo 백로그에
      존재하는지 (krtour T-210b~e ↔ TripMate, krtour T-217a ↔ agent T-066 패턴).

## 3. 결정 전파

- [ ] 최근 분기의 ADR/결정(krtour `docs/decisions.md`, TripMate
      `docs/decisions*.md`, agent `docs/decisions.md`)이 상대 repo 문서·코드에
      반영됐는지 — 특히 계약을 바꾸는 결정(envelope/경로/필드명).
- [ ] `docs/integration-map.md` §1~4 표를 실측값으로 갱신(시스템/포트/정본 위치
      변동 반영).

## 4. 산출

- [ ] 발견 항목을 검토 보고서(`docs/reports/<topic>-YYYY-MM-DD.md`)로 정리 —
      불일치는 file:line 근거 + 어느 쪽을 고칠지(정본 우선) 명시.
- [ ] 수정은 repo별 PR(머지 여부는 사용자 결정), 의사결정 필요 항목은 별도
      decisions-needed 문서로 분리(2026-06-10 검토 형식).

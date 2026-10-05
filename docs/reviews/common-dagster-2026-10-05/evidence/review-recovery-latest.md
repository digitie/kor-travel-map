# 최신 main 병합 후 Map·PinVi 독립 FULL 연속 리뷰

- 날짜: 2026-10-05 KST
- 판정: **FULL 연속 PASS (Map·PinVi)**. 운영 제품·fixture byte 불변이며 문서 metadata delta에서 새 블로커 없음.
- Map 최신 base `0342034f020cc07af2094f216456f64e45e39ed2` → 후보 `c4d62a793ba69a60543fafda7442b3ba2c019ad1`.
- PinVi base `07cfef222c56d7e648c81b017aa8ffe4ccd1c386` → 동일 후보 `aa265cf1c3917b9d0e89316d06c35678d23757c2`.
- Common 제품 `1f8e339c7c79f86f8952b0d4c326ab4dae56bee8`.
- 고정 manifest SHA256: `949b602796ac14a73460d1b26085a61672cf019848e0cefe610daec37e73f1e9`.

## 직접 확인과 증거 연결

본인 ext4 `/home/digitie/.cache/recovery-review-map-main-c4d62a7`에 exact Map 후보를 Git archive했다. PinVi는 동일 exact HEAD의 이전 archive를 재사용했다. 최신 base 대비 Map 59파일·PinVi 13파일 전체 delta 경로와 manifest의 모든 파일 SHA256가 일치함을 직접 검증했다.

직전 독립 PASS 후보 `24de4f288b40b3fe9033b32fa91231ede60d4d44`부터 새 Map 후보까지 전체 Git diff는 다음 두 문서뿐이다.

- `docs/handoff/2026-10-05-shared-dagster-handoff.md`
- `docs/resume.md`

모든 다른 tracked 파일이 동일하므로 운영 Python/UI/Docker/spec/의존성·Dagster·HTTP·배치 소스뿐 아니라 새 integration fixture도 같다. 제품 FULL 판정은 본인 이전 전체 검토·직접 실행과 fixture 연속 검토의 유효한 증거를 재사용한다. 새 제품 테스트나 새 FULL 실행 수치로 중복 집계하지 않는다.

이전 불변 원문:

- `map-pinvi-final-closure-review-recovery.md`: SHA256 `e60fc4115dde0c64b8650dfe416e08efab28f9bbed20f278a4d750e8fe73b6b4`; R01–R06 FIXED와 본인 직접 pytest 1,517 PASS, 각 공격·미실행 경계.
- `map-pinvi-integration-closure-review-recovery.md`: SHA256 `522af1fd9537c62f19cb80e8913decc492bbb1bf5ea70dd379fecec65547ecb3`; 기존 assertion 310개 유지·1개 강화와 request factory/운영 middleware 직접 6개 경로 PASS.

원문은 수정하지 않았다. 상대 리뷰어 원문과 결과는 미열람이며 부모의 local PG/CI/native recovery/memory/live 실행을 본인 수행으로 더하지 않았다.

## metadata delta 평가

handoff와 resume의 Manager `e2a1a5b4`, transport `50d5636b` 표기가 일치한다. handoff는 Manager instance digest, logger/smoke deadline 보강·transport startup/redaction 후속과 남은 event-log 원문 경계를 구분한다. 기존 Map·PinVi 운영 pin을 새 후보의 배포 완료로 바꾸지 않는다.

디스크 과거 사용률·정리 이력과 90% preflight 실패 조건을 기록하고, 남은 이미지의 소유자 확인을 명시한다. resume은 n150 변경 전에 fresh preflight를 통과해야 한다는 기존 요구를 유지한다. 문서가 fresh preflight/guarded rebuild/live/merge를 완료로 승격하지 않는다.

이 검토는 Git 문서 metadata의 정합성과 제품 불변성을 확인한 것이다. Manager/transport의 현재 설치 commit, 실제 instance digest, 디스크 사용률 또는 과거 운영 작업 결과는 본인이 외부 운영 환경에서 확인하지 않았다. fresh preflight에서 이 상태를 재관측하는 것은 부모의 후속 운영 게이트다.

## 실행·미실행과 보존

직접 수행: Linux Git archive, base→candidate의 전체 경로·파일 SHA 검증, 24de→c4 전체 delta 2문서 확인, 변경 문서 내용 독립 검토. 제품·원본 설치·외부 서비스·Git index는 수정하지 않았다.

이번에는 제품/fixture가 동일하므로 pytest·factory probe를 다시 실행하지 않았다. 이전 직접 1,517 PASS와 6개 fixture 경로의 의미를 유지하며 새 실행 수치로 표시하지 않는다.

**NOT_RUN:** actual PostgreSQL/domain SQL, N150 fresh preflight·guarded paired rebuild·live UI/E2E, 최종 CI 확인, 실제 Manager/transport/디스크 상태 재관측, Docker/UI build, 운영 RSS/worker kill/shared production daemon. 이전 원문의 미실행 경계도 유지한다.

본인 exact manifest·검증 JSON 2파일을 Weather `.playwright-mcp/map-pinvi-latest-main-review-recovery-evidence/`에 byte 보존했다. preservation-manifest.json SHA256:

`a2832b239d65bb45fff93d428535fcedbeee2168148cce6eabb02998c6c9d98d`.

현재 고정 후보의 독립 FULL PASS는 연속 유지된다. 운영 gate 완료와 PR merge는 별도 결과다.

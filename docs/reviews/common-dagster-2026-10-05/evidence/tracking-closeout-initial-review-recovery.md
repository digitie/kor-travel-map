# 머지 후 추적 문서 — 최초 고정본 독립 좁은 리뷰 A

판정: **PASS (비차단 P3 문서 정정 2건 OPEN)**. 신규·잔여 P0/P1/P2는 0건이다. 이 최초 고정 원문은 수정하지 않으며 후속 3파일 정정은 별도 판정한다. 제품 작업은 실제 머지 완료 상태이고, 현재 docs-only 완료 원장 후속의 CI/PR/merge는 NOT_RUN이다.

## 고정 범위

manifest map-pinvi-tracking-closeout-review-manifest.json SHA256 5a2c82be4ed5fc55a47bc59630e5322c15737a79d68893cc41e69026658c8afa의37파일을 검토했다. 직접 SHA37/37 일치, 각 저장소의 전체 current diff 및 untracked 목록이 manifest와 대응하며 모두 docs 경로다. peer 원문은 열람하지 않았다.

세 codex/map-pinvi-merge-records checkout HEAD는 Common cb4d37823f88902f24b6f0e3362b77944e7b5e61 / Map 0e09574738bdebfa00f58f257a4d9ef67617b797 / PinVi 1c6d2837002461c1b95a9fddd4df2164387a8929다. 현재 변경은 unstaged narrative/task13개와 동일한 새 영수증8종의 세 저장소 복사24개다. staged 변경은 없다. git diff --check 세 저장소 PASS.

가이드3 hash는 이전 PASS와 동일하다: Common ed75f864e2719d1130e94013c58cda8b15d14fb87904bda50ea3c5758cee7c6d, Map 5d199456a2ee01e600f8359c444f487a215dbd2846cd9eaaed1d9acfed9fd525, PinVi 0494412105ff63ad8119c9c72220397da7019d2103b44ac7b1c1b748a91f7f31.

## 직접 머지·소스 보존 검증

현재 GitHub API를 gh api로 읽어 3PR의 merged=True/state=closed, 실제 SHA와 시간 및 tested head를 영수증과 대조했다.

| PR | tested HEAD | 실제 병합 SHA | merged UTC |
| --- | --- | --- | --- |
| Common28 | 082577a52d69d30cb813e4d920803eab126e322b | cb4d37823f88902f24b6f0e3362b77944e7b5e61 | 2026-10-05 21:38:57Z |
| Map1303 | 4acadf7bbd9d70d80bb3db8be4708095913e23ff | 0e09574738bdebfa00f58f257a4d9ef67617b797 | 2026-10-05 21:58:40Z |
| PinVi576 | 92d0f40e24c4b420e4d699eba4f2f98165e8e58f | 1c6d2837002461c1b95a9fddd4df2164387a8929 | 2026-10-05 22:01:29Z |

Git tree를 직접 대조하여 세 병합 commit의 전체 tree가 각각 tested HEAD와 같음을 확인했다. docs를 제외한 tracked blob/mode 집합은 frozen product a960/1a3/005와 각각227/1460/1136개가 그대로였다. Common·Map은 parent2이며 frozen source와 tested HEAD가 main merge의 ancestor다. PinVi는 parent1이고 original source/head가 squash main의 ancestor가 아님을 명시적으로 확인했다. 이를 merge ancestry 보존으로 설명하지 않는다.

현재 PinVi main ruleset17146781은 allowed_merge_methods=[squash], required_linear_history이며 required status는 Aggregate CI gate다. 실제 remote refs/tags/codex/pinvi-map-runtime-20261006은0058369c778f8c3357ee393e12e3447d7975cc1f, refs/tags/codex/pinvi-map-reviewed-20261006은92d0f40e24c4b420e4d699eba4f2f98165e8e58f의 commit이다. 원 feature branch codex/map-common-live-e2e도 reviewed92d를 가리키며 GitHub에 유지됨을 직접 확인했다. 이번 리뷰에서 ruleset 변경·tag/branch 생성·release 발행은 하지 않았다. 정책을 바꾸었다는 근거는 없고 현재 정책과 보존 영수증은 일치한다.

## CI 및 머지 후 영수증 대조

GitHub의 tested SHA 최신 check metadata에서 Common8/Map10은 모두 completed/success였다. PinVi의 integration4 및 Aggregate CI gate success도 직접 확인했으며 다른 skipped 또는 중복 trigger의 skipped check를 PASS로 합산하지 않았다.

실제 job metadata 및 logs를 읽어 다음 작성자 CI 요약을 직접 대조했다: Map glibc job111993381557은1138 passed/12 skipped, Alpine job111993381700은1132 passed/18 skipped; PinVi integration4 job111987068723은178 passed/543 deselected로 success다. 기존 integration4 job111981369332는 같은 workflow37375022437의 failure로 그대로 남아 있었다. 영수증의 이전 Ryuk DockerHub502 사유는 작성자 forensic이며 이 리뷰에서 과거 장애를 새로 재현하지 않았다. 읽은 CI 실행 수치는 본인이 테스트를 실행한 수치가 아니다.

final-postmerge-runtime-attestation.json SHA b05e125e782f851cc34ad73f45a19d551e74aebecc8983cec9e00d2afe83266f는 recorded_at22:02:51Z로 3PR 머지 이후다. status 및 두 unchanged/healthy booleans는 strict True이고 baseline8d998cecf435d270b704b5bb20912004d3143ce89b62a0dbe3710cefd737db99에 결박된다. nested runtime의6 containers 전체 identity/설치 source, deploy bytes·transaction·manager·Dagster head, sources는 baseline과 같았다. sources.recorded_at19:17은 committed generation의 시각으로 새로운 배포를 뜻하지 않는다. 최초 자체 검사에서 wrapper를 flat attestation으로 가정한 KeyError를 corrected nested-runtime 검증으로 바로잡았고 위 대조가 완료됐다.

postmerge runtime은 작성자가 실제 운영을 읽은 영수증을 본인이 로컬에서 비교한 결과이며 이번 요청에서 N150를 새로 호출하지 않았다. 이전의 독립 운영 source/image 검증·native byte inheritance·UI/D1D2/8PNG gate를 새로운 머지 HEAD의 신규 fault/live 실행으로 집계하지 않는다.

## 원장·링크·범위

3repo journal/resume 최신 절과3 closure/README append는 primary3 MERGED와 규칙상 PinVi squash, 원본 태그·branch 보존, frozen product 및 실제 운영 불변, old native의 관련 코드/버전 상속 범위를 설명한다. 실제 운영 worker fault나 RSS 감소율을 주장하지 않는다.

Common global T-319/T-216 IN_PROGRESS와 외부 transport/HAProxy 및 기존 global backlog는 보존한다. Map T-COMMON-DAGSTER/PinVi T-371은 active bullet에서 제거되고 completed entry가 추가됐다. 상대 링크422개는 대상 존재를 확인해 missing0이었다. 현재 추가 narrative와 JSON receipt37개에 private IP/URI userinfo/private-key 패턴 발견0. 규범 guide·제품 source·기존 raw evidence 수정은 없다.

## Finding

**TRACK-A01 / P3 / OPEN** — Map docs/tasks.md의 T-COMMON-DAGSTER 제목 bullet만 지웠고 바로 아래 들여쓴 “후보 구현 후 두 독립 적대적 리뷰·live·CI·merge를 확인한다”와 guide/tasks-acceptance 링크가 active 원장에 남았다. 앞선 열린 M05 task의 설명으로 렌더링될 수 있다. 해당 설명/참조도 완료 entry로 옮기거나 정리하여 active task의 scope를 정확히 유지할 것을 권고했다. 제품·실제 수용에는 영향이 없다.

**TRACK-A02 / P3 / OPEN** — Map/PinVi docs/tasks-done.md 새 entry는 3PR의 “exact CI·merge commit”을 확인했다고 표현한다. 실제 PinVi는 squash parent1이며 최신 journal은 이를 정확히 구분한다. 완료 entry에서도 Common·Map merge / PinVi squash 또는 병합 tree 대조로 용어를 명확히 할 것을 권고했다. 원본 SHA/tree 및 source refs는 정확하다.

작성자는 최초37manifest와 이 원문을 보존한 뒤 위 3파일을 고쳐 새 postfix manifest로 요청하겠다고 알렸다. 이 원문 시점 disposition은 OPEN이며 사후 수정으로 소급하지 않는다.

## NOT_RUN 및 다음 gate

이 요청은 primary Common28/Map1303/PinVi576가 머지된 뒤의 docs-only 추적 closeout이다. 완료 기록의 근거는 실제 머지/CI/운영 receipts이며 제품 작업 완료를 다시 미완료로 돌리지 않는다. 현재 docs-only 변경의 신규 CI·PR·merge 및 위 P3 postfix는 아직 NOT_RUN/검토 대기다.

제품 build·큰 suite·운영 재구축·native fault·UI·D1/D2를 재실행하지 않았다. 제품113·guide·PNG의 broad 재리뷰도 반복하지 않았다. 파일 수정·stage·commit·push·GitHub 설정·운영 mutation은 없었고 새 ignored 독립 원문만 작성했다.

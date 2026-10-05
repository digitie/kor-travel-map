# Map C7 vendor 입력 고정 후보 FULL 연속 독립 closure

검토일: 2026-10-06. 전문축: 복구·DB·메모리·격리·실패 전파 및 실제 C7 build 입력. 판정: 전체 고정113 blobs 범위 source FULL 연속 PASS. 실제 새 Docker build/operating rebuild/UI gate 성공 판정은 아니다.

고정 입력:

- map-pinvi-ticks-c7-reviewed-manifest.json SHA256 8837d075991f70a65d977eee4bd8c5b641f0b7653e1fbc116ad2204204db0f2f
- Common a960bdb114d99a2ac1b9608a77b240635806e551, baseline7dc1d6dda955b9b836cb3f24d6fd5bcd37fabe52
- Map1a3c4673790f51daa1a2f5ccf803d4e31673bad6, baselinea46d7b92c0e727805348e20d60fe188592e16477
- PinVi0058369c778f8c3357ee393e12e3447d7975cc1f, baseline07cfef222c56d7e648c81b017aa8ffe4ccd1c386

전체 봉인: immutable Git cat-file batch로113 blobs(Common35/Map63/PinVi15)의 SHA256을 직접 검증했다. 각 base→candidate 전체 diff path set은 manifest와 같다. 이전 ticks manifest9d53eed9d50fdc1c6f5044005efa0c9686303d91e9e14f08c28aad140f177d28의112 blobs는 모두 같은 SHA이다. 전체885→1a3 tree delta는 docker/c7-playwright.Dockerfile만이며 Common/PinVi delta0이다. C7 파일이 새로 manifest coverage에 포함되어 총113이 됐으며 원래 repository tree에는 있던 파일이다.

본인 exact Git archive: /home/digitie/.cache/recovery-c7-fixed-1a3c467-ff4gaifq/map.
verification.json SHA25631502beea77cb0acade5b37374718428498e4dd728b3b139be85c741bc6ee667.
원본 dirty checkout의 입력이나 peer 원문을 검토·실행 근거로 사용하지 않았다.

새 C7 delta 직접 검토: 한국어 설명 한 줄과 frontend/vendor COPY 한 줄만 변경됐다. COPY는 npm ci --workspaces 이전이며 frontend/package.json의 file:vendor 상대 경로와 일치하는 /work/packages/kor-travel-map-admin/frontend/vendor에 놓인다. base image digest, npm version, root/workspace manifest 및 lock, verify:npm-tree/verify:next-sharp, 이후 workspace COPY, C7 commit/base labels와 WORKDIR는 동일하다. Dockerfile-specific ignore가 없고 root .dockerignore는 vendor/tgz를 제외하지 않는다. 관련 build script는 root commit의 git archive를 context로 사용하고 root Dockerfile 경로와 C7_REPOSITORY_COMMIT을 명시한다. 새 COPY가 사람 dirty/untracked archive를 끌어들이는 경로를 추가하지 않는다.

본인 독립 결함·closure 재현: Dockerfile의 첫 RUN 이전 COPY를 own 새 cache layer에 재현했다. old885에서는 frontend의 두 file:vendor archive가 모두 없다. new1a3에서는 두 archive가 올바른 상대 경로에 존재하고 고정 Git archive와 byte 동일하다. 실제 npm registry/설치나 Docker build를 수행한 것으로 주장하지 않는다.

입력 검증:

- @kor-travel/ui0.1.0-dev.6 tgz SHA256e4945d01d9eb89ed505a95b551899fd0ecf41be66c9ee6b76246701350447e6d
- @kor-travel/tokens0.1.0 tgz SHA256554ae3f6a18cbf453130b29f8a2d737ddb880101b55e14535cf8d63174b47505
- 각 lockfile resolved=file:경로가 정확히 한 entry였으며 sha512 integrity가 실제 tgz bytes와 동일했다. tar 내부 package/package.json name/version도 의존 패키지와 일치했다. 기존 vendor bytes는 변경되지 않았다.

직접 targeted tests: own archive에서 /home/digitie/.cache/map-common-recovery-venv/bin/python으로 아래 세 파일을 pytest -q 실행했다. PYTHONPATH는 own fixed Map/Common source, TMPDIR은 ext4 cache다.

- tests/unit/test_dockerfile_workspace_manifest_coverage.py
- tests/unit/test_c7_prod_live_runner_contract.py
- tests/unit/test_frontend_dependency_security.py

결과53 passed in0.70s/exit0/stderr0. 전체 변경 없는 broad suite는 반복하지 않았다.
본인 COPY/lock/tar 재현 사본: /home/digitie/.cache/recovery-c7-vendor-input-probe.py.

유효한 이전 근거 재사용: map-pinvi-ticks-closure-review-recovery.md SHA682a09b168da2872543f0dadcc5701bfeb40a3a0164f3b4dfc1675961b794ab9의 source FULL112 판정을 같은112 blobs에 재사용한다. 이 원문과 앞선 builtin FULL413dc 원문은 불변으로 보존한다. API tick query fce5 해시 및 실제 all4statuses2.077초/DTO·UI 정보 보존/own SQLite selector LIMIT branch 근거는 동일하다. snapshot100배치 atomic seal/dedup, lease/operation CAS 복구, executor/run retry0, active/owner selector, bounded HTTP/cancel/client 수명, Common health marker guard 및 PinVi pins/autoload/builtin source에 새 delta가 없다. 이전 source PASS는 그 당시 고정 후보·범위의 역사적 근거이며 이번 실제 C7 source 입력 발견을 소급하여 없던 것으로 만들지 않는다.

최종 판정과 경계: C7 pre-ci vendor 누락은 own COPY layer 재현 기준 CLOSED. 현재113 범위 source FULL 연속 PASS이며 새로운 blocker 없음. actual image build, C7 stageC, paired deploy/runtime attestation, ACL/D1/D2 및 UI gate는 NOT_RUN이다. root 제공 실제 negative journal/native/UI 결과는 본인 수행이나 새로운 Map1a3 성공으로 합산하지 않는다. 새 source에는 실제 fresh build 및 새 revision으로 바인딩된 runtime/UI 증거가 필요하다. 기존 deployed Map1ba와 그 native 성공은 별도 범위로 보존해야 한다.

제품/서비스/DB 변경·commit/push·회전·build·운영 접속을 수행하지 않았다. 새 ignored helpers는 제품 manifest 밖 별도 gate이며 이번 source FULL 판정이 helper 실행을 대신하지 않는다. codegraph 상태/사람 checkout/다른 agent resource도 수정하지 않았다.

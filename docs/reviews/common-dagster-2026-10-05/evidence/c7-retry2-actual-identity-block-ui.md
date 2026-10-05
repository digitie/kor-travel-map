# C7 retry2 실제 Docker identity 진단 독립 원문
실행 ID: J-C7-ESM-IDENTITY-ACTUAL-B-20261006
판정: BLOCK (P2) — ignored overlay helper 실행 호환성. frozen 제품 113파일 및 실제 UI/HTTP/native 검증과 별도이다.

고정 대상: /tmp/map-c7-esm-ticks-retry2-overlay.py SHA256 ee825d52292a9126c17ab26f73a0b04eeccc7d2a4c4273fe929b1ca86a187977.
J-C7-ESM-P2-02 OPEN, line50.
Config blob SHA를 docker image inspect의 Id와 같다고 가정한다. 실제 Docker29 containerd store의 Id는 OCI index target digest다. 정상 derived image에서 이 검사가 실패하여 proof 작성/standard test tag repin/D1/D2 전에 중단한다. fail-closed 실패이며 성공 오인은 아니다.

EXECUTED — 독립 실제 read-only:
- Docker29.6.1/API1.55 actual image inspect. child Descriptor는 OCI index이며 Id==Descriptor.digest. standard TEST tag가 보존 parent에 계속 연결됨과 child RootFS prefix==parent를 확인했다.
- ctr content get으로 index/선택 manifest/config만 읽었다. 각 descriptor size와 bytes SHA를 검증했다. config body/환경변수/private 주소는 출력하지 않았다.
- index: sha256:2ace4e5a55db16b998fc9248c6be2bd7e48d7b821c0f4ef0c5f3e0afddaf5c66, 856B.
- 유일 linux/amd64 manifest: sha256:fbd3b0cd8fbe56c96d4b0dc48947b567264107283675b11ca01e1cc60d798518, 4277B.
- config: sha256:da79f217c65f73924866bc581f2c9cec2098e0fbcdc5681958086c5c3b91f928, 10792B. 실제 Id와 다르며 config RootFS 21개 diffIDs는 inspect와 정확히 같다.
- manifest 마지막 layer descriptor: sha256:2198d9580773c8564b92cddb74d53bb95bff879c95d903ded2a364bd0e237b39, 1363B.
- config 마지막 uncompressed diffID: sha256:a7105bc3b2631c357bfd3aceaf6bc0f0c789039bb5681a11d72d3b1abb266cb8. 압축 layer digest와 구분해야 한다.
- source label은 frozen Map1a3c4673790f51daa1a2f5ccf803d4e31673bad6이다. 전체 docker save는 반복하지 않았다.

권고 계약:
실제 inspect Id/Descriptor의 index bytes SHA·size → 유일 실행 platform manifest SHA·size → config SHA·size → RootFS와 마지막 layer descriptor/diffID를 연결한다. 정상 platform과 attestation manifest를 구분하고 모호한 복수 실행 manifest는 거절한다. parent/child rootfs prefix와 source/base/parent labels, package before SHA 및 한 파일/type 한 키 제한은 유지한다. config digest를 Docker target Id로 대체해서는 안 된다. 마지막 압축 layer를 읽는다면 compressed descriptor hash/size와 bounded decompressed diffID를 각각 검증한다.

근거:
[Moby containerd ImageInspect 구현](https://github.com/moby/moby/blob/master/daemon/containerd/image_inspect.go)은 target digest를 ID/Descriptor로 사용한다. 실제 호스트 관측과 일치한다. master 구현을 실제29.6.1의 고정 소스 tag 검증으로 과장하지 않는다.
[OCI image index](https://github.com/opencontainers/image-spec/blob/main/image-index.md)는 platform manifest descriptor를 연결하고, [OCI image manifest](https://github.com/opencontainers/image-spec/blob/main/manifest.md)는 config와 ordered layer descriptor를 연결한다.

NOT_RUN:
overlay build/retag/repin 재실행, 전체 save, 큰 layer 읽기, archive rename, chain/D1/D2, 제품·서비스 변경 및 새로운 운영 테스트. 실제 retry2 실패 실행은 부모가 수행했다. 본인은 그 실행을 자체 실행으로 집계하지 않았다.

기존 원문:
초기 save-format P2-01은 OCI 지원 수정으로 FIXED였으며 불변 원문을 유지한다. 이전 scoped PASS는 당시 parser fixture/정적 검증 결과다. configSHA==Id를 만족하는 fixture만 사용하여 Docker29 actual target identity 차이를 검증하지 못했던 한계를 이 새 실제 진단으로 명시한다. 기존 PASS 원문 SHA f2b76d20b6c6ec23c7d92e5e86730f1a1573142660911a8bb8b269bd3e64d1f8을 변경하지 않는다.
peer 원문 미열람, private 주소·credential·config 내용 미공개, 제품/운영/원본 실패 증거 미변경.

독립 관측/보존 시각(UTC): 2026-10-05T20:39:03.375345+00:00

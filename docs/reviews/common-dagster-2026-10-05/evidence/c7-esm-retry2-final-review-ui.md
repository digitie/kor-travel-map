# C7 ESM retry2 좁은 독립 최종 리뷰
실행 ID: J-C7-ESM-RETRY2-FINAL-B-20261006
판정: PASS — overlay·retry2 launch/archive preserve/collector 정적 범위. frozen 제품 113파일 및 UI FULL 검증을 다시 집계하지 않는다. 실제 overlay build/repin·archive 이동·chain/D1/D2 실행은 NOT_RUN.

고정 SHA256:
- overlay: ee825d52292a9126c17ab26f73a0b04eeccc7d2a4c4273fe929b1ca86a187977
- owned retry2 shell: a815ecd317f19bb268e816da02e06a065973eacc0d89bba17d4c6952f095c694
- prepare: 162c07eabc9edba023cbd2b8ef6c3396fe3d97f6ef3c08af0f2be55eb245a5b0
- launch: 89f40551efd25c75f6a71460931f9d70cf18d800c00b7ba8e5f3fce35db43eaa
- preserve-retry1: f60479b6738a690a5b6a2b528cb81c0255b2728221914f764833e68b942b1448
- source identity: 6f3182610e85d20b47b900cb0d3033924e08c258328ae1eec2fb87e215463bc8
- format-fix generator: e7e2b6950808cb2c1c569c11d515d1eb02ee7db17419f5687a43660fbe0e1fa4
- sealed collector: 4def75e6bcbe9eaf0c9ee03a8b13da1c4774c0928a36c0552438bf18034210d7
- collector seal generator: ce04c1d7c125679cde90004323d9914bab65e50a5ab6a352f39b8f1d76fa6516

J-C7-ESM-P2-01 FIXED: 초기 a3c16e 파서는 legacy layer.tar/config.json만 수집하여 실제 OCI blobs save 형식에서 정상 입력을 거절했다. 정확히 같은 초기 AST fixture의 legacy control PASS/OCI·OCI gzip 실패를 재현했다. 실제 호스트 Docker info는 containerd image store였고 read-only C7 save의 첫 regular header는 blobs/sha256 형식이었다. 앞부분만 읽고 CLI를 종료했으며 archive를 저장하지 않았고 standard image ID 전후 동일했다. 초기 BLOCK 원문 SHA 7a8c084b403baddafdbfec082ab643a0138b5c1f335e00a735f4dac5e408d057은 불변 보존했다.

EXECUTED:
- current exact AST 파서: legacy·OCI·OCI gzip 정상 3종 PASS. extra file/whiteout/hardlink/중복 package/8MiB 초과 gzip/config image digest/마지막 layer diffID 불일치 음성 7종 모두 거절.
- exact stream reader: 총 128MiB cap 초과 시 추가 파일 보존 전에 거절, 오류 시 export 자식 kill/wait 확인. 공유 8MiB fixture로 수행했으며 큰 임시 archive를 만들지 않았다.
- Map1a3 고정 Git package bytes와 BEFORE_HASH/BEFORE_JSON 동일성, generator→current overlay byte 동일성.
- retry1→retry2는 새 namespace와 repin 직전 overlay 한 호출 이외 shell bytes 동일. 여섯 환경 allowlist·네 D1 spec·strict exit·private artifact/log·M01/D2 흐름 유지.
- helper local compile, 실제 모든 placeholder 치환 후 remote Python compile, launch 및 owned shell bash -n.
- preserve-retry1은 이전 PASS helper의 failed invocation/destination/receipt/private log namespace 치환만임을 byte proof로 확인. nofollow/dev/inode/UID1000/RENAME_NOREPLACE·dangling lane·stdin transport 경계 유지.
- exact collector seal: 정상 및 proof FAIL/derived image mismatch/helper hash drift/D1 exit failure/OOM/foreign D1 image 음성 6종 확인. 전부 기대대로 허용/거절.
- 검토 종료 전 current source 전체 bytes 불변 재확인.

READ-ONLY 계약:
현재 source1a3/base9bd labels guard, parent tag 보존, before package SHA 확인, type=module 한 키 semantic delta, parent rootfs prefix와 추가 layer/config ID 증명 후 standard TEST tag repin 순서이다. manifest가 지목한 정확 config/layer를 선택하고 config SHA=image ID, 해제한 layer SHA=diffID를 검증한다. 추가 파일은 package.json 하나와 제한된 부모 directory만 허용한다. whiteout·symlink/hardlink는 거절한다.
캐시는 파일당 8MiB/총 128MiB, gzip 해제는 8MiB+1 검사를 적용한다. 큰 base layer를 파일로 저장하지 않는다. save CLI의 별도 시간 deadline은 없고 전체 chain의 TimeoutStartSec=10800에 의존한다. 본 scope에서 이 사실을 별도의 짧은 HTTP deadline 계약으로 과장하지 않는다.
launch의 새 nonce/start/old-run set/InvocationID/attestation와 helper/source hash 연결을 유지한다. sealed collector는 현재 overlay source SHA·proof·derived C7 ID·실제 D1 container ID/exit/OOM을 묶으며 기존 fresh D2/snapshot validator/현재 여섯 image fence를 유지한다.

NOT_RUN / 개인정보:
overlay main, Docker build/tag 변경, archive rename, chain/D1/D2 실제 실행, 신규 제품/운영 테스트는 수행하지 않았다. current 제품1a3/005/Common pins·여섯 operating image의 새 운영 성공으로 해석하지 않는다. source·계정·공개 기록·peer 원문을 변경/열람하지 않았다. 실제 주소·credential·private helper 전문·image config는 이 원문에 포함하지 않았다. 리뷰 도구의 launch 일부 출력에서 SSH 주소 redaction 누락이 한 번 있었으며 즉시 부모에게 알렸고 공개 증거로 복사하지 않았다.

잔여 P0/P1/P2 finding 없음. 실제 새 실행 결과는 fresh namespace receipt로 별도 검토해야 한다.

검토 종료/보존 시각(UTC): 2026-10-05T20:28:34.025039+00:00

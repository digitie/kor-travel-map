# C7 ESM retry3 독립 좁은 closure
실행 ID: J-C7-ESM-RETRY3-FINAL-B-20261006
판정: PASS — ignored overlay/생성기/launch/collector 범위. 실제 retry3 build/tag/repin/chain/D1/D2는 NOT_RUN이다. frozen 제품113 FULL 및 운영 UI 결과와 별도로 기록한다.

고정 SHA256:
- overlay 94cdbbb7ed09cc081f2650f7a74288f2b67c42750f1e21386b97c89ca445d413
- owned shell f2e2e86bbfe27c6b7914915b0deb87c082e0c75a239b3d942a6fe7e7f88f980e
- prepare 97f3e3dae366f84e348b2baf316e7d7fdb1cb4ad4fd4d21b6dc9e53c0a62bf96
- launch e7a90e5495fe0750568ee322f666b1113acfa5553aa3523ff69a536a969c5929
- collector 35d64f8865958fb24028fe65a1925b8a5521d1b15c2a6c433402515247d618e4
- source identity 25324a8c0e3df5f2ec14c50bb97db2c0e30eb10806ef4712690e30d3b1b1cc7e

J-C7-ESM-P2-02 FIXED. 이전 configSHA==Docker inspect Id 가정을 제거했다. 실제 OCI index Descriptor/Id → 유일 linux/amd64 manifest → config → 마지막 layer의 SHA·size·mediaType를 연결한다. config RootFS와 labels/coreConfig가 inspect와 일치하고, child Config는 parent 대비 두 test label만 변경되어야 한다. 마지막 압축 bytes digest와 해제 diffID를 각각 검증한다. 기존 실제 P2 BLOCK 원문 SHA46900345ddc377e3d81816e56bd2d8ea60407145f31a0f02999f128d94c0dd03은 불변 유지한다.

EXECUTED:
- current overlay의 정확한 content 함수와 descriptor/config/layer 검증 AST만 기존 retry2 failed-derived image에 read-only 적용했다. actual index/manifest/config/마지막 작은 layer가 모두 통과하고, parent Config 대비 두 label만 변경·package.json 한 파일/type=module 한 키를 확인했다. 기존 실패 이미지의 정합성을 검증한 것이며 retry3 build 또는 성공 실행으로 집계하지 않는다. 전체 save/retag/build 호출은 없는 snippet이었다.
- exact content 함수 own subprocess fixture: 정상, bool size, 잘못된 hash, size 초과, child exit failure, timeout 음성/정상 6종 기대 결과. timeout fixture는 select가 deadline 실패를 반환하도록 주입했으며 실패 시 자체 자식 kill/wait와 stdout close를 확인했다. 실제15초 벽시계 대기를 새 테스트로 수행했다고 주장하지 않는다.
- exact modern descriptor/layer validator 14종: 정상, 모호한 platform, foreign platform, target mismatch, foreign rootfs, foreign config mediaType, config bytes hash drift, nonlabel config 변경, extra file, whiteout, symlink, duplicate file, package semantic 변경, gzip 해제 상한 초과. 정상 허용/음성 모두 거절.
- generator 순수 할당만 평가하여 실제 overlay/shell/launch/collector 네 파일 및 identity가 정확히 재현됨을 확인했다.
- launch/collector는 검토된 retry2 sealed 파일의 namespace 치환만이고 shell도 같은 치환만임을 직접 byte proof로 확인했다. 이전 fresh nonce/start/old-run set/InvocationID/current images/snapshot validator/overlay proof·source SHA/derivedId·D1 exit/OOM 경계의 검증을 유효한 재사용으로 명시한다.
- 모든 local 및 실제 placeholder 치환 remote Python compile, owned shell/launch bash -n. 종료 직전 current bytes 재확인.

수명·메모리:
ctr는 readonly content get만 사용한다. 각 descriptor는 positive non-bool size와 SHA256 형식을 검사하고 JSON1MiB/layer8MiB cap을 적용한다. selectors read deadline15초, 실패 시 kill 후 wait cleanup 상한15초, stdout close가 있다. gzip은 해제8MiB+1 읽기로 상한을 검사한다. read deadline을 cleanup까지 포함한 전체15초 상한으로 과장하지 않는다. Docker build/inspect/tag 등 전체 동작은 기존 chain10800초 상한에 의존한다. 큰 base layer/전체 save를 수행하거나 저장하지 않는다.

개인정보·운영 경계:
source1a3/PinVi005/Common frozen제품 bytes 및 실제 계정·서비스는 수정하지 않았다. tiny config는 메모리에서 검증하고 환경변수/실주소/credential/전체 config를 출력·공개하지 않았다. helper 전문/private shell은 공개 원문에 복사하지 않았다. peer 원문 미열람. 실제 새 tag 전환과 fresh 성공 영수증은 이후 실제 실행 후 별도로 판정해야 한다.

잔여 P0/P1/P2 finding 없음. 이전 초기 save-format 및 실제 identity BLOCK/PASS 원문을 수정하지 않는다.

검토 종료/보존 시각(UTC): 2026-10-05T20:44:12.193639+00:00

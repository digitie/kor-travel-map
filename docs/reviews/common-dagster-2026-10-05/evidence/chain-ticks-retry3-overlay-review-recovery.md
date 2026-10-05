# retry3 OCI content 하니스 독립 closure

판정: **PASS — 고정 source의 좁은 정적·로컬 검증**. retry2 H-OCI-01의 index/config ID 혼동은 source에서 수정됐다. 실제 retry3 helper/build/tag/repin/D1/D2는 본인이 실행하지 않았으며 **NOT_RUN**이다. Common a960 / Map 1a3 / PinVi 005 제품 FULL113 범위와 구분한다.

## 고정 bytes

| 대상 | SHA256 |
| --- | --- |
| overlay helper | 94cdbbb7ed09cc081f2650f7a74288f2b67c42750f1e21386b97c89ca445d413 |
| retry3 chain | f2e2e86bbfe27c6b7914915b0deb87c082e0c75a239b3d942a6fe7e7f88f980e |
| map-chain-ticks-retry3-prepare.py | 97f3e3dae366f84e348b2baf316e7d7fdb1cb4ad4fd4d21b6dc9e53c0a62bf96 |
| map-pinvi-chain16-ticks-retry3-launch.py | e7a90e5495fe0750568ee322f666b1113acfa5553aa3523ff69a536a969c5929 |
| map-pinvi-chain16-ticks-retry3-collect.py | 35d64f8865958fb24028fe65a1925b8a5521d1b15c2a6c433402515247d618e4 |

이전 retry2 실제 실패 원문은 `map-chain-ticks-retry2-containerd-digest-negative-review-recovery.md`, SHA256 `fc1f9a7decc28fd8d3f7ccaf9906011ca1c9c951c9f93a2e20e7b628460e4447`로 불변 보존한다. 이전 정적 PASS 원문도 실제 실패로 덮어쓰지 않았다.

## H-OCI-01 closure와 새 경계

현재 helper는 actual inspect Id/Descriptor를 OCI index로 검증한다. index→유일한 linux/amd64 platform manifest→config→마지막 layer의 연결을 각 content SHA·descriptor size·mediaType으로 확인한다. config digest가 image index ID와 같다는 이전 잘못된 검사는 없다. 실행 platform이 모호하거나 지원 mediaType이 아니면 거부한다. 이 helper는 현재 Docker29 containerd OCI index 모델을 대상으로 하며 generic legacy engine 지원을 주장하지 않는다.

config rootfs.diff_ids는 inspect RootFS와 같아야 한다. Config core Env/WorkingDir/Entrypoint/Cmd/User와 labels를 actual inspect 값에 연결하고, parent Config와 child Config의 전체 차이를 두 test labels만 허용하도록 검사한다. 마지막 compressed blob digest와 uncompressed diffId를 분리한다. parent layer prefix+한 추가 layer, package.json 단일 파일 whitelist, semantic type=module 한 key, standard tag의 parent 재확인과 immutable proof 쓰기를 유지한다.

ctr는 지정한 local socket/namespace에서 필요한 작은 content만 읽는다. descriptor size는 bool을 거부하고 JSON1MiB/layer8MiB 상한을 둔다. 실제 stdout도 64KiB 단위로 읽으며 선언과 상관없이 상한을 검사한다. selector read 예산은 **각 content 15초**이며, 실패 시 자식을 kill/wait하고 stdout을 닫는다. 전체 helper가15초 안에 완료된다는 주장은 아니다. gzip 해제도8MiB로 제한된다.

launcher와 collector의 이번 delta는 retry2→retry3 namespace 치환만이다. 이전 collector seal의 helper hash·proof source/mode/parent/derived ID, D1 실제 container image/exit/OOM와 D2 execution identity 연결이 유지된다. 기존 실패한 child/source/log/tag를 지우는 코드는 없다. canonical source archive 부재는 retry2 실패 후 actual read로 확인했으며 이번 retry3는 새 rename helper를 추가하지 않는다.

## 직접 수행한 검증

현재 validator AST와 실제 content 함수를 own Python process에서 실행했다. ctr 대신 own local Python child가 stdout pipe로 fixture를 전달하도록 했으며, os.read·selector·deadline·kill/close는 실제 로컬 동작이었다. 원본 helper/생성기의 mutation 부분은 실행하지 않았다.

- OCI 모델 **22건**: 정상 gzip/raw2 PASS. wrong index ID, config ID를 index로 사용, 중복/누락 platform, index/manifest/config/layer mediaType, config rootfs/core drift, unexpected Config/label, wrong diffId, 추가 file, semantic extra key, truncated blob, blob digest drift, bool size, descriptor cap, gzip expansion cap20 REJECT.
- 실제 transport **2건**: declared size와 무관하게1MiB를 초과한 stdout stream REJECT(0.014초); 무응답 pipe를 실제 **15.017초**에 REJECT. 두 경우 자식 종료와 stdout close를 확인했다.
- 생성기의 읽기·대입·compile 부분만 AST로 평가했다. overlay/chain/launcher/collector 네 출력이 실제 파일과 BYTE_EXACT였다.
- outer Python4파일 compile, 완전 치환 launch2/collector1 Python 블록 compile, 치환 shell2개와 chain bash -n 모두 PASS.
- 현재 launch/collector가 이전 검토된 retry2 파일의 namespace 치환과 byte 동일함을 직접 확인했다.

추가 actual read-only 확인: 보존된 retry2 child2ace/parent1d37의 Config가 두 test labels만 다른지 실제 inspect에서 비교해 정확히 같음을 확인했다. 앞선 독립 tiny ctr 진단은 실제 index·manifest·config·compressed layer·diffId·단일 package semantic 연결을 검증했다. 새 retry3 validator를 운영에서 실행한 증거로 합산하지 않았다. 작성자나 다른 리뷰어의 실행 수치도 위 직접 수행 수에 포함하지 않는다.

## 운영 판정

source 수준 H-OCI-01 closure와 추가 경계 검증은 PASS다. 실제 새 image·proof·standard test tag·여섯 production image 불변/healthy, 최종 D1/D2 terminal receipt·purge/lane은 실제 실행 후 별도로 확인해야 한다. 이번 검토에서 build/tag/repin/rename/cleanup·DB/fixture 쓰기·browser 재실행·새 helper 실행은 하지 않았다. 제품과 이전 원문은 수정하지 않았다.

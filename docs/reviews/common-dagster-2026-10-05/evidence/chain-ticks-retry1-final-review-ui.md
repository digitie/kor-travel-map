# Chain ticks retry1 정적 최종 독립 closure
실행 ID: J-CHAIN-TICKS-RETRY1-FINAL-B-20261006
판정: PASS — 현재 고정 helper 범위. 실제 보존 이동·chain/D1/D2 운영 실행은 NOT_RUN이다. 제품 113파일 FULL PASS와 별도 검토이며 새 제품 리뷰나 실제 chain 성공으로 집계하지 않는다.

## 고정 대상
Weather ignored helper를 own cache 사본으로 고정하고 종료 직전 원본과 byte 동일성을 재확인했다.
- map-pinvi-chain16-ticks-retry1-launch.py: a36d397fc769c7230a71f0350210ebbe5278f0696c5e89b6e4a4be5b96adab34
- map-pinvi-chain16-ticks-retry1-collect.py: f5d9ed27b013d4a14ea1634ec9d1fed42a43d8bee9d7561660086531a10d8a06
- map-chain-owned-archive-preserve.py: 8653e12436dfa3c60fbebc58178da393e66df44145158fc6f5c421bb6808dbd3
- map-chain-ticks-retry1-prepare.py: af059e103eb10f4d11d5f8c66913bf88888a5bbb01b11c6b903c8af797977b05
- map-chain-ticks-retry1-source-identity.json: 84c5db3d829d06a23983772222e81ed452742d03edf4d5c40c57fbb6819d32ad
- owned shell: 86c16e271bca0e4f6754796c771c0389753a1739220930daaa6f7a75229fd038
- trusted 원본 shell: 7f6558eebfbf3acceb7771e8025e161c028bbe6f8ff1e8d3177f103181b1bce4

Map1a3c4673790f51daa1a2f5ccf803d4e31673bad6 / PinVi0058369c778f8c3357ee393e12e3447d7975cc1f / 기존 attestation 연결을 유지한다. peer 원문 미열람, 제품·shared 서비스·원본 trustedshell·계정 미변경.

## Finding disposition
- J-ARCHIVE-P2-01 FIXED. archive helper:63–78의 parent dirfd/no-follow source directory·UID1000·dev/inode 검사, renameat2(RENAME_NOREPLACE), destination.lstat 및 source nonlink 최종 검사. own scratch의 실제 libc 호출로 정상 rename 허용, anchor 전 source symlink·anchor 후 치환 symlink·늦게 등장한 destination 거절을 확인했다. anchor 후 치환은 최종 guard에서 거절될 수 있으므로 ‘경합 시 이동 부작용이 전혀 없음’으로 표현하지 않는다. 기존 목적지 덮어쓰기는 방지된다.
- J-CHAIN-RETRY1-P2-02 FIXED. collect:39 및 archive:18의 ACTIVE/BLOCKED 검사에 dangling symlink 거절을 포함한다. own 빈 lane 허용, 두 dangling marker 거절을 직접 확인했다.
- J-CHAIN-RETRY1-P2-03 (이전 원문 P2) NOT_APPLICABLE / 검토 scope 오류 정정. 기존 sh -c 반례는 코드 전체를 부모 argv에 넣었지만, 실제 archive main:82는 ssh … bash -s + input=script로 전달한다. 실제 호출 인자를 확인하지 않고 다른 transport 반례를 적용한 검토 오류였다. 동일 bash -s stdin→sudo -n python3 - own fixture에서는 any_hit/parent_hit/self_hit 모두 False, foreign own child argv에 source를 넣으면 any_hit=True였다. 실제 N150에서 동일 stdin 방식으로 read-only ancestor argv 7개를 확인했으며 canonical source literal 없음이었다. 현재 코드 수정이 필요한 결함으로 유지하지 않는다. 기존 BLOCK 원문은 변경하지 않았다.

새 잔여 P0/P1/P2 finding 없음.

## EXECUTED
- 네 Python helper compile, 실제 placeholder 치환 후 remote Python compile 및 launch/owned shell bash -n.
- generator의 순수 할당만 평가하여 생성 결과가 현재 launch/collector bytes와 동일함을 확인했다. generator main/파일 생성/운영 작업은 실행하지 않았다.
- trusted 원본의 D1 블록만 치환하면 owned 86c16e와 정확히 동일함을 확인했다. 블록 밖 M01/repin/D2 흐름 bytes 유지, 여섯 기존 전달 환경변수·같은 네 D1 spec 유지, acceptance write opt-in 없음, rm -rf 없음, archive tar pipeline 실패 거절 명시.
- own scratch 실제 rename 경계 4종, lane 경계 2종, 정상 dependency symlink 허용/잘못된 dependency symlink·untracked 빈 디렉터리 거절.
- 실제 stdin transport own 정상/foreign argv 음성 fixture, N150 read-only ancestor argv 검사. 원격 보존 코드 main 또는 rename 부분은 실행하지 않았다.
- 세 기존 BLOCK 원문 SHA 불변 재확인. 초기 자체 fixture의 정규식 및 namespace 누락은 정정 후 재실행했으며 제품 실패로 집계하지 않았다.

## READ-ONLY 계약 검토
launch의 새 unit·sourcecopy·nonce/start·previous run set·InvocationID·attestation/image 연결과 local output open(x)를 확인했다. collector의 같은 retry1 namespace, 부모 terminal success/InvocationID, 현재 D2 terminal event 및 새 run 선택, parsed bytes 불변·전체 fingerprint·private snapshot validator·현재 여섯 image 재검사·API image 즉시 일치·fresh 출력 open(x) 경계를 이전 final review와 연결해 확인했다.
C7 제품의 /work 내부 node_modules와 최종 frontend WORKDIR가 새 D1 명령의 CLI/config/spec 경로와 맞는다. 전용 D1 artifact 디렉터리만 rw 전달하며 host source/dependency tree를 새 실행에 bind하지 않는다.

## NOT_RUN / 한계
실제 failed archive rename, fresh chain launch/collector, M01/D1/D2 운영 시험, 신규 build/rebuild는 수행하지 않았다. 본 판정은 current helper의 정적 계약과 own 경계 fixture PASS이다. 실제 운영 성공은 새 namespace로 생성된 실제 영수증을 별도로 확인해야 한다. 다른 리뷰어 원문 및 private URL/credential/cmdline 내용은 열람·공개하지 않았다.

## 원문 보존
기존 archive BLOCK SHA e49d4fd29828c101f94fbdef2f8c69d4a5eeb5965b2ba86475ed7683fe737d93,
lane BLOCK SHA 5cf76d7197a6735df73e6555c8477aecbd376b24799639fc81c63987e812f97c,
scope 오류가 있던 proc-parent BLOCK SHA 09bb73b8d7b30bb69232516c2ebe163c97d2fe8463997fdd26f62e994eea22a1은 불변 보존했다. 이 후속 원문이 현재 실제 호출에 대한 disposition을 정정한다.

검토 종료/보존 시각(UTC): 2026-10-05T20:02:20.602351+00:00

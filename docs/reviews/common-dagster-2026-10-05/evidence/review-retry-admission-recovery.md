# 같은 pair 재시도 admission 독립 읽기 전용 원문

작성: 2026-10-06. 범위: 설치된 launcher/CLI source, current registry, ledger claim, 기존 terminal/lock 상태의 읽기 전용 audit. 빌드·rotation·ledger override/삭제·제품 또는 운영 변경은 수행하지 않았다. peer 원문을 읽지 않았다.

## 판정

**같은 고정 pair를 새로운 안전한 tag·미존재 출력 디렉터리로 재시도하는 것은 설치된 정상 계약에서 허용된다.** 실제 실행 시 fresh preflight, global lock, root/출력/manager/registry 검증은 정상 경로로 다시 통과해야 한다. 이 판정은 빌드 성공이나 운영 gate 통과를 뜻하지 않는다.

설치된 run-pinned-rebuild-once 직접 읽기 SHA256:
a355e1689b47adfd53c2351afff07bf50e8cce589cdfcb6357b11950e14b9aec

설치된 guarded-rb.sh 직접 읽기 SHA256:
73cd4ee1439fd18cbe1c293bd670d339c35c7cc17692eaeacfdba31c7bbd2dee

launcher 233–267의 next_claim_filename은 동일 pinset의 다음 ordinal을 선택한다. 230/263의 claim 상한은 500이다. 327–328은 실패 claim을 제거하지 않고 감사 기록으로 보존하며 재실행에는 다음 ordinal을 부여한다고 명시한다. 실패 한 번으로 동일 source pair를 영구 차단하는 계약이 아니다.

root 실행·manager revision·정본 current pinset·global nonblocking flock·새 absolute 출력 디렉터리와 root로 잠긴 부모 디렉터리를 검증한다. 정상 호출은 rebuild-pinned --confirm --json이며 launcher는 --restart를 넘기지 않는다. 이번 동일 pair 재시도에는 rotation·source 변경·ledger 삭제/override·restart/adopt가 필요하지 않다. guard는 자식 실패 뒤에도 unit 성공으로 종료할 수 있으므로 systemd Result를 실제 rebuild 성공 gate로 사용하면 안 된다.

## 실행 전 실제 상태 직접 관측

아래 값은 재시도 launch 전 본인이 읽은 snapshot이다. 이후 실행 상태를 이 snapshot으로 대신하지 않는다.

- installed manager: e2a1a5b42fec207fc6c5e0638c652de04e5694d4
- current registry source: Map 1ba6ef4c52f64200e3bc3e9a4fee1dd5f8d4e77e / PinVi 0058369c778f8c3357ee393e12e3447d7975cc1f
- current pinset: 54de39d1be7a3539fb016565212e6182999ec195b9938d813b5e7801d728aa25
- 해당 pinset claim: 1개, ordinal 0. 다음 ordinal 1, 상한 미도달.
- ledger 디렉터리 root/0700 및 claim regular file root/0600/link1 안전.
- claim 원문 SHA256: dde653e54f73b3631bc5cece4a603eb5f6d350d05f4c3101bed2364e3ec27a9d
- claim key는 manager_source_revision, output_directory, pinset_sha256 세 개이며 pinset 및 제4회 출력과 일치.
- 제4회 terminal: status=failed / stage=candidate_compose_build.
- 기존 guard/inner unit inactive/dead.
- /proc/locks의 해당 inode 읽기 전용 snapshot에서 global mutation lock 미보유. lock 획득/생성/해제는 수행하지 않았다.

새 출력 tag 사용은 기존 원문과 실패 출력을 보존하기 위한 정상 요구이다. 모니터·audit 시 주소·DSN·자격정보는 출력하지 않았으며 이 원문에도 포함하지 않는다.

## 설치된 성공 결과 schema

설치된 compose_service.py 4458–4478의 _pinned_runtime_result는 10개 key를 반환한다:
success, returncode, resumed, outcome, transaction_id, phase, generation_sha256, pinset_sha256, schema_heads, warnings.

정상 새 배포 계약: success is True, returncode는 int 0, resumed=False, outcome=deployed, phase=committed. transaction_id=status.run_id이며 committed deploy도 이 run_id를 유지한다. convergence는 previous run_id 및 outcome=converged를 사용하므로 새 배포 성공과 구분해야 한다.

설치된 cli.py 122–140은 구조 redaction 후 같은 dict를 그대로 JSON 출력한다. status=success를 추가하지 않는다. 실패만 366–369에서 status=failed와 선택적 stage를 출력한다. 따라서 정상 원문에 존재하지 않는 status 필드를 만들거나 요구하지 않고, canonical success fields와 same-read deploy/source/pinset/image/transaction 연결을 검증해야 한다. warnings의 raw 내용은 공개하지 않는다.

## 실행 경계

본인 직접: 설치된 wrapper/CLI/result callsite source 읽기, current registry source와 pinset, claim ordinal·metadata·hash, terminal result, unit 종료 및 읽기 전용 lock snapshot을 확인했다.

본인 NOT_RUN: fresh preflight 실행, 재시도 launch/build, cleanup/rotation/ledger 변경, runtime attestation/native/UI/live/chain. 작성자 전달 preflight/registry network 결과는 본인 수행에 합산하지 않았다. 이후 작성자가 같은 pair retry1을 launch했다고 전달했으며, 그 새 실행은 별도 읽기 전용 stage/terminal 모니터 대상으로 분리한다. 기존 제4회 실패 원문은 수정하지 않는다.

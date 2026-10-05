# Map chain ticks retry1 하니스 독립 초기 검토

판정: **BLOCK — 실행 전 국소 안전 경계 보강 필요**. 제품 source113/FULL·실제6서비스 runtime PASS는 변경하지 않는다.

## 최초 고정 bytes

| 대상 | SHA256 |
| --- | --- |
| private chain copy | aa98d5ba46408feea04c842c54defb662cea4d34abfc4976af4d3a90d5624191 |
| prepare | 28aa4eb8b423528b239d28a0d9e3bb3242e1dad38a80a9b8788f309aaac05ea0 |
| launch | 44b8e091634c63f07f5aefda094ececdef65013b6757983531587a37558bbdb5 |
| collect | 037c1b166849f5f0792b9e932ca4384cc574e4580f74d0842c976c8db3512775 |
| preserve | 4c7ad88ceb67053935f998fe7c5b2cfe8e6398e63cc8c1413f248c5fb53286d1 |

최초 private chain은 original 7f6558...의 D1 구간만 교체한 구조다. D1 내부 C7 dependency·6개 env allowlist·실제 Docker exit 확인·전체 private log·fresh container/artifact 방향은 적절하다. M01/repin/D2 흐름을 가볍게 바꾸거나 기존 실패 증거를 지울 이유는 없다.

## 발견 경계

1. **P2 / preserve 43–52행 — 실행 중인 source 사용 누락**. cwd/root/fd만 조회한다. 본인 cache 안의 worker.py를 python argv로 실행하고 다른 cwd에서 대기시킨 실제 local process는 살아 있었지만 이 검사는 source를 찾지 못했다. /proc/cmdline에는 source worker 경로가 남았다. process cmdline 및 mapping도 확인해야 한다. 실제 N150 프로세스를 실행하거나 이동하지 않았다.
2. **P2 / preserve 53–54행 — destination no-replace 미보장**. 마지막 exists 확인 뒤 새 빈 destination 디렉터리가 생기면 Path.rename이 이를 덮어쓴다. 본인 scratch에서 실제 빈 디렉터리의 inode가 source inode로 바뀌었음을 확인했다. parent/path/inode를 고정하고 원자적인 RENAME_NOREPLACE가 필요하다.
3. **P2 / preserve 38–42행 — 미추적 디렉터리 허용**. expected에 없는 모든 directory를 허용해 known node_modules symlink 두 개 외 unexpected entries 거부 요구를 충족하지 못한다. tracked path의 ancestor directory 집합으로 제한해야 한다.
4. **P2 / preserve 18행 — dangling lane symlink 누락**. exists만으로 ACTIVE/BLOCKED의 부재를 판단하면 dangling symlink가 부재처럼 보인다. symlink 자체도 거부해야 한다.
5. **P2 / launch 67행·collect 113–114행 — immutable output TOCTOU**. exists 후 write_text는 원자적 새 파일 생성이 아니며 기존 receipt의 동시 생성 시 덮어쓸 수 있다. 앞서 inheritance에서 닫은 같은 경계이므로 open('x')로 통일해야 한다.

추가 국소 권고: private chain archive pipeline은 set -e가 없고 실패 status를 직접 처리하지 않는다. 일부 추출 뒤 runner 파일만 존재하면 진행할 수 있어 명시적인 `|| die`가 필요하다.

## 직접 수행과 경계

초기 Bash syntax exit0·Python outer4개 compile PASS. substitution된 launcher Python2개/collector1개/preserve1개 및 launcher Bash syntax도 확인했고 original 대비 D1 밖 prefix/suffix가 같았다. 소스의 hash를 읽었고 본인 cache의 짧은 process/rename 반례만 실행했다. 임의 service·source archive·fixture DB·운영 container에 작용하지 않았다.

prepare/preserve/launch/collect 실제 실행, 원격 파일 이동·새 unit/container·D1/D2는 NOT_RUN. private IP/URL/env 실제값/credential·전체 private helper는 이 원문에 포함하지 않는다. Peer raw를 읽지 않았다. 이 원문은 수정 후 PASS와 별도로 보존한다.

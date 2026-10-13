# tasks-acceptance 아카이브 — `T-VN-DAGSTER-STORAGE` (완료)

> `T-VN-DAGSTER-STORAGE`의 해제 조건 원문이다. 절은 닫혔고, live 문서
> [`../tasks-acceptance.md`](../tasks-acceptance.md)가 220 KiB(225,280 bytes)
> 상한에 닿아 `docs/tasks-rule.md` §8대로 분리했다(2026-10-13).
>
> **본문은 바이트 단위로 보존했다** — 옮기기만 했고 한 글자도 고치지 않았다
> (파일 끝 빈 줄만 하나로 정규화).
>
> **분리 전에 쟀다.** `scripts/archive_task_ledger_section.py`가 확인한 것:
> 이 절의 fence 마커 4개(짝), 시작·끝 경계 모두
> fence 밖, 그리고 옮긴 뒤 두 파일의 `parse_checkboxes` 결과 합이 옮기기 전과
> **다중집합으로 같음**. 2026-09-13에 제목 기준으로 원장을 통째로 쪼개려다
> 되돌린 적이 있는데, 그때 깨진 것이 바로 이 성질이다.
>
> 과거 검색은 `rg <패턴> docs/archive/`.

## T-VN-DAGSTER-STORAGE

```markdown
- [ ] T-VN-DAGSTER-STORAGE — **prod Dagster run이 compute-log storage에 쓸 수 없다**
```

**무엇이 참이면 닫히는가.**

1. [x] prod에서 provider asset job 하나가 `SUCCESS`로 끝난다 — run launcher에 제출한
   run이 step 실패 없이 완주한다. **2026-09-12 충족.**

   `feature_place_standard_museums_job`이 정식 경로(`dagster job launch`)로 제출돼
   `SUCCESS`로 끝났다. **이 prod에서 provider 적재 job이 SUCCESS로 끝난 첫 사례다.**

   run 이력이 뒤집혔다 — 2026-09-11에는 조회 시점 8건이 **전부 실패**였는데,
   수정 배포 뒤에는 `SUCCESS 23 · FAILURE 1`이다. 그 FAILURE 1건은 08:09의
   `current_weather_summary_refresh`로, rebuild가 스택을 내리던 순간에 걸린 run이다.
   스택이 올라온 08:22 이후의 run은 전부 성공했다.

   로컬 쓰기 자리도 실물로 확인했다 — 컨테이너 안에서 `uid=999(appuser)`가
   `/opt/dagster/state/{artifacts,compute_logs}`를 소유하고, compute log가 실제로
   쌓이고 있다. 종전에는 그 자리가 봉인된 `DAGSTER_HOME` 아래라 만들 수조차 없었다.

   적재 축도 다시 맞물린다: `claims 1047 · aliases 1047 · links 1047`
   (`features 1048`은 D2가 남긴 은퇴 행 1개를 포함한다 — §T-VN-D2-RESIDUE).

   **2026-09-13 새 세대(pinset `b71cbefc`, map `2b65e5b3`)에서 재확인.** 같은 job이
   다시 `SUCCESS`로 끝났고 이번에는 `features 1047`이다 — D2가 자기 행을 스스로
   지웠으므로 은퇴 행이 없다(§T-VN-D2-RESIDUE 실측 `lane_residue_total=0`). 네 축이
   정확히 같다: `features 1047 · claims 1047 · aliases 1047 · links 1047`.

   **2026-09-16 — 이 조문의 증거가 한 번 사라졌다가 다시 섰다.** 배포는 prod DB를
   **새로 만든다**(`kor_travel_map` 생성 2026-09-15 12:29:55Z = t44a 배포 시각).
   그래서 위 두 실측이 담겨 있던 run 이력은 t44a 뒤에 존재하지 않았고, 조회 시점
   run 897건은 전부 분 단위 `current_weather_summary_refresh`(배포 후 15시간치)였다.
   **`[x]`는 붙어 있는데 그것을 뒷받침하는 관측은 없는 상태였다는 뜻이다.**
   같은 job을 현 세대에 다시 제출해 run `0f70d0d5`가 `SUCCESS`로 끝나고
   `features 1047`이 다시 섰다(§T-VN-CURATION-SEAL-ACL 조문 1과 같은 실행). 이
   조문이 왜 이렇게 되는지는 `docs/tasks-rule.md` §6이 규약으로 적는다.
2. [x] **그 성질이 배포마다 유지된다.** (2026-09-13 t41a 배포로 확인) generation이
   `b71cbefc` → `bae61363`으로 바뀐 뒤 **새 세대에서 run 완주 게이트가 15/15로
   통과**했다 — 탐침 run이 실제로 `SUCCESS`로 완주하고, live config의 로컬 쓰기 두
   축이 여전히 `/opt/dagster/state` 아래이며, 필수 daemon 4종이 전부 fresh였다.
   즉 storage 부착이 세대 교체를 따라온다는 것이 **한 번의 관측이 아니라 두 세대의
   비교**로 보인다.
3. [x] **이 축을 재는 검사가 있다.** (2026-09-13, #1226) `scripts/dagster_run_completion_gate.py`가
   다섯 축을 독립으로 판정한다 — live config(컨테이너 안 `$DAGSTER_HOME/dagster.yaml`),
   metadata 표 실재, daemon heartbeat 신선도, **능동 탐침 run 완주**, 멈춘 run 0건.
   prod 실측으로 2026-09-11 사고 config를 되돌리면 red가 되는 것까지 확인했다
   (config 변이 5종 + daemon tolerance 변이 전부 red, 대조군 0/15).

   첫 판은 **초록이었지만 네 자리에서 아무것도 재지 않았다** — `floor/runs-observed`는
   게이트가 방금 만든 탐침 때문에 항진명제였고, stuck은 큐 대기 시간을 섞어 재면서
   `STARTING`을 6시간 기준으로 봤고(띄우지 못하는 launcher가 안 보인다), daemon 하한은
   상수 1이라 회수 daemon만 죽어도 초록이었으며, 신선도는 꺼진 daemon의 heartbeat 행이
   영구 잔류하면 절대 초록이 될 수 없는 구조였다. 두 차례 적대 리뷰가 하나씩 잡았고
   전부 prod에서 다시 쟀다.
4. [x] **봉인 검사기와 배에 실리는 `dagster.yaml`이 서로를 본다.** (2026-09-12, #1219/#1224)
   검사기가 8개 key 집합을 봉인하고, 이 저장소가 실제로 싣는 config를 그 검사기로
   통과시키는 테스트가 CI에 있다(`test_sealed_validator_accepts_the_config_this_repo_actually_ships`).
   그 테스트가 없던 동안 검사기가 자기 config를 거부해 prod 스택이 내려갔다.
5. [x] **"run이 왜 죽었나"를 UI로 확인할 수 있다. — 2026-09-13 실측으로 정정.**

   처음에 이 조문을 "UI에서 step의 stdout/stderr가 보인다"로 적었다. 근거는
   `dagster`(webserver)와 `dagster-daemon`이 별개 컨테이너이고 `/opt/dagster/state`에
   공유 volume이 없다는 것이었다 — 그 사실 자체는 맞다(실측: webserver 0 디렉터리,
   daemon 42 디렉터리). 그래서 공유 named volume을 넣으려 했다.

   **고치기 전에 재 봤더니 그 자리가 정보를 담지 않는다.**

   ```
   compute_logs : 42 run · 286 파일 · 전부 0바이트 · 352K
   artifacts    : 528K
   ```

   286개가 **전부 0바이트**이고, 여기에는 방금 1,047건을 수 분간 적재한
   `feature_place_standard_museums_job`의 것도 포함된다. 이 배포의 step은 stdout으로
   인쇄하지 않는다 — 모든 로깅이 Dagster 로거를 지나 **event log(postgres)**로 간다.
   그 표는 40 run에 699행이고(ENGINE_EVENT · STEP_START · RESOURCE_INIT ·
   STEP_OUTPUT · HANDLED_OUTPUT · LOGS_CAPTURED …) 두 컨테이너가 같은 DB를 보므로
   **이미 공유되고 UI에 보인다.** 실패는 `STEP_FAILURE` 이벤트가 오류 본문을 담아
   같은 경로로 표시된다.

   그러므로 공유 volume은 **빈 파일을 공유하는 일**이다. 그리고 공짜가 아니다 —
   파괴적 rebuild는 volume이 아니라 데이터베이스 수준에서 비우므로(`postgres`
   컨테이너가 rebuild를 여러 번 겪고도 `Up 7 days`였다) 공유 volume은 배포를 넘어
   살아남고, `retention`은 compute log를 덮지 않는다. 측정된 증가율 ~31 MB/일
   (분 단위 schedule 기준)이 상한 없이 쌓인다. **정보 이득 0에 무한 증가를 더하는
   교환이다** — 같은 날 `retention`에서 저지른 실수와 같은 모양이다.

   **남는 진짜 틈(좁다).** step이 stdout/stderr로 **직접** 쓰는 경우 — 라이브러리
   인쇄, 또는 Dagster 핸들러 밖에서 나는 하드 크래시 traceback — 그것은 daemon
   컨테이너에만 남고 UI가 보여 주지 못한다. 그때는 `docker logs
   kor-travel-map-dagster-daemon-latest`가 정본이다. 그 경로를 아는 것이 이 조문의
   실질이고, 그것을 위해 무한 증가를 사지 않는다.

**무엇이 관측됐나 — 2026-09-11.**

**범위 정정(2026-09-12).** 이 결함은 run을 FAILURE로 **표시**하고 compute log를
남기지 못하게 한다. 그러나 **적재 자체를 막지는 않는다** — 같은 run이 남긴 데이터가
정합성 검사 여섯 축을 0건으로 통과했다(§T-VN-39-DEPLOY 조문 4). 그래서 이 task는
"적재가 안 된다"가 아니라 **"run의 성공/실패 신호와 compute log를 믿을 수 없다"**를
소유한다. 신호를 믿을 수 없다는 것은 그 자체로 운영 결함이다 — 2026-09-12에 나는
정확히 그 신호를 믿고 조문 4를 "막혀 있다"로 잘못 적었다.

정식 경로(`dagster job launch` → run launcher 제출, operation key = job 이름)로 제출한
run이 step 실패로 끝났다:

    PermissionError: [Errno 13] Permission denied: '/opt/dagster/dagster_home/storage'
    Exception initializing logger write stream: PermissionError ...

실물:

| | |
|---|---|
| 컨테이너 사용자 | `uid=999(appuser)` |
| `/opt/dagster/dagster_home` | `dr-xr-xr-x root root` — appuser가 쓸 수 없다 |
| `.../storage` | **없다** |
| 마운트 | `dagster-storage-permit` (읽기 전용, generation `461cafcc…` 산출물) |

prod Dagster storage는 별도 관리 컴포넌트다 — `/usr/local/bin/ktm-dagster-storage`가
`verify-identity`와 sealed launch contract를 갖고, entrypoint가 `storage_input_preflight`
로 argv를 대조한다. 즉 storage 부착은 pinned runtime이 통제하는 축이고, 현
generation에서 그것이 붙지 않았다.

**재키가 만든 것이 아니다.** 이 prod의 Dagster run 이력은 전부 실패다(조회 시점
8건 중 7 FAILURE + 1 진행). `feature.features`가 0행이었던 것과 앞서 찾은 seal ACL
유실이 같은 사실의 다른 면이다 — **이 prod에서 provider 적재가 한 번도 완주한 적이
없다.** 그래서 이 조건도 그때부터 있었고 아무도 관측하지 않았다.

**조문 3이 그 구멍을 겨냥한다.** 배포 사후점검은 컨테이너 healthy와 정본/실물 image
일치를 보지만, "run이 완주한다"는 보지 않는다. 그 둘은 다른 사실이다.

**무엇이 관측됐나 — 2026-09-12. 고침이 결함이 됐다.**

#1216(`dagster.yaml`에 `local_artifact_storage`/`compute_logs` 선언)이 머지된 뒤 첫
회전 사이클이 prod 스택을 내린 상태에서 죽었다. `docker/dagster-storage-migrate.py`의
`_validate_dagster_config`가 최상위 key 집합을 **정확히 5개로** 봉인하고 있었다.

    06:34:05  …kor-travel-map-dagster-storage-migrate-run-dc953676ad41  기동
    06:34:07  task-delete                                              (2초)
    06:34:09  pinned runtime rebuild Compose run command failed (exit 1)

#1219가 봉인을 그 둘만큼 넓히되, 두 `base_dir`가 이미지가 appuser에게 넘긴
`/opt/dagster/state` 안인지까지 본다 — key를 허용하는 것으로 끝내면 "로컬로 새지
않는다"는 봉인의 뜻이 그 구멍으로 빠져나간다.

**조문 4 — 봉인 검사기와 배에 실리는 config가 서로를 본다.** 기존
`test_dagster_storage_rejects_alternate_top_level_storage_keys`는 실제 `dagster.yaml`을
읽으면서도 이 어긋남을 못 잡았다. **거절되는 것**만 보기 때문이다 — 두 파일이
어긋나면 그 거절은 이유만 바뀐 채 여전히 일어난다. #1219가 **통과하는 것**을 보는
검사를 심었고, 변이 ②(검사기만 되돌림)에서 그 하나만 빨갛다.

**알려진 한계.** `/opt/dagster/state`에는 volume이 없다. artifact와 compute log는
컨테이너 재생성마다 사라지고 컨테이너 경계를 넘지도 못한다. **그것이 문제가 아닌
이유는 조문 5에 적었다** — 그 파일들은 이 배포에서 전부 0바이트이고, 진단 내용은
postgres의 event log에 있다. run/event/schedule storage가 postgres이므로 조문 1·2에도
영향이 없다.

**호스트 dev 스택도 같은 파일을 읽는다.** `scripts/run-admin-stack.sh`가
`docker/dagster.yaml`을 바이트 그대로 호스트 `DAGSTER_HOME`에 깐다. #1216의
`base_dir`는 이미지 안에만 있는 경로라 그대로 두면 dev에서 같은 PermissionError가
난다. #1219가 설치 뒤 두 경로만 `$DAGSTER_HOME` 아래로 옮기고, 그 요구를
`dagster.yaml`이 선언한 key 집합에서 유도하는 검사를 붙였다.

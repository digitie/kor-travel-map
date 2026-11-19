# tasks-acceptance 아카이브 — `T-CI-DOCKERFILE-BUILD` (완료)

> `T-CI-DOCKERFILE-BUILD`의 해제 조건 원문이다. 절은 닫혔고, live 문서
> [`../tasks-acceptance.md`](../tasks-acceptance.md)가 220 KiB(225,280 bytes)
> 상한에 닿아 `docs/tasks-rule.md` §8대로 분리했다(2026-11-19).
>
> **본문은 바이트 단위로 보존했다** — 옮기기만 했고 한 글자도 고치지 않았다
> (파일 끝 빈 줄만 하나로 정규화).
>
> **분리 전에 쟀다.** `scripts/archive_task_ledger_section.py`가 확인한 것:
> 이 절의 fence 마커 0개(짝), 시작·끝 경계 모두
> fence 밖, 그리고 옮긴 뒤 두 파일의 `parse_checkboxes` 결과 합이 옮기기 전과
> **다중집합으로 같음**. 2026-09-13에 제목 기준으로 원장을 통째로 쪼개려다
> 되돌린 적이 있는데, 그때 깨진 것이 바로 이 성질이다.
>
> 과거 검색은 `rg <패턴> docs/archive/`.

## T-CI-DOCKERFILE-BUILD

- [x] C1. Map CI가 `docker/*.Dockerfile`을 실제로 빌드한다 — 현재
      `.github/workflows/`에 `docker build`가 **0건**이라 Dockerfile 결함이 n150
      격리 e2e나 pinned rebuild에서야 드러나고 피드백 루프가 한 시간이다.
- [x] C2. registry 없이 돈다(`KOR_TRAVEL_MAP_BUILDX_OUTPUT=oci` + 단일 platform).
      arm64는 굽지 않는다 — 배포 대상이 amd64뿐이다.
- [x] C3. `scripts/docker-buildx.sh`를 경유한다. 현재 그 스크립트를 **호출하는 곳이
      저장소에 없어** 자체가 검증되지 않는다; CI에서 돌리면 Dockerfile과 빌드
      스크립트가 함께 산다.
- [x] C4. trigger 경로가 Dockerfile의 `COPY` 대상에서 **파생**된다. 손으로 나열하면
      한쪽만 늘어나 조용히 빠진다(2026-09-03 `frontend.Dockerfile` 워크스페이스
      매니페스트 누락과 같은 계열).
      **구현 시 결정**: 파생 대신 **필터를 두지 않는 쪽**을 택했다. 필터가 없으면
      파생할 것도 뒤처질 것도 없어 이 조건의 목적(누락 불가)이 더 강하게 달성된다.
      비용은 PR당 job 하나이고 기존 20분짜리 unit job과 병렬로 돌아 전체 대기시간을
      늘리지 않는다. `test_the_workflow_has_no_path_filter`가 필터가 다시 생기는 것을
      막는다.
- [x] C5. 새 Dockerfile이 생기면 이 job이 자동으로 그것을 포함하거나, 포함되지 않았을 때
      깨진다. `test_every_production_dockerfile_is_built`가 `docker/*.Dockerfile`과
      `build_one` 호출 집합을 대조한다(런타임 아닌 c7-playwright는 사유와 함께 면제).
      탐침 Dockerfile을 넣어 실제로 깨지는 것을 확인했다.

(근거: 2026-09-03 `frontend.Dockerfile`이 선언된 워크스페이스 셋 중 둘만 복사하는
결함이 #1137까지 숨어 있었다. `frontend.yml`은 전체 체크아웃에서 같은 npm 명령을
돌리므로 영원히 통과했고, Dockerfile 경로는 CI에서 한 번도 빌드되지 않았다.)

- [x] C6. 이 job이 실제 PR에서 초록으로 도는 것을 한 번 확인한다. **충족**(2026-09-04):
      #1142에서 `production Dockerfiles build`가 13분 55초에 pass했고 같은 커밋의
      나머지 8개 job도 전부 초록이었다. 그 PR은 `cac35134`로 머지됐다.
      (C1~C5가 모두 `[x]`인데 task는 `[~]`로 열려 있었다 — 그 이유인 잔여 요구가
      `docs/tasks.md` 본문에만 있고 해제 조건 파일에는 없었다. 아래 이관 본문의
      "**남은 것**: 이 job이 실제 PR에서 초록으로 도는 것을 한 번 확인한다."를
      그대로 조건으로 세운 것이며, 새로 지어낸 조건이 아니다.)

### `docs/tasks.md`에서 이관한 구현 근거 (2026-09-04)

> `docs/tasks-rule.md` §5는 "task당 위치는 하나 — `docs/tasks.md`에 한 줄, 해제 조건은
> `docs/tasks-acceptance.md`에 한 절. 본문을 중복하지 않는다"고 정한다. `docs/tasks.md`의
> 이 항목은 한 줄 규약을 어긴 584자 산문이었고, 그 내용은 이 절이 소유해야 할
> 판정 근거·재개 조건이었다. 아래는
> 그 본문을 **원문 그대로** 옮긴 것이다 — 요약·축약·삭제 없음(2026-09-04 이관).

Map CI가 프로덕션 Dockerfile을 한 번도 빌드하지 않았다(`.github/workflows/`에 `docker build` 0건). 그래서 Dockerfile 결함은 n150 격리 e2e나 pinned rebuild에서야 드러나고, 그 피드백 루프는 한 시간이다 — 2026-09-03 `frontend.Dockerfile`의 워크스페이스 매니페스트 누락(#1137)이 그렇게 숨어 있었다. `scripts/docker-buildx.sh`는 `KOR_TRAVEL_MAP_BUILDX_OUTPUT=oci` + 단일 platform으로 registry 없이 돌릴 수 있고, 현재 그 스크립트를 **호출하는 곳이 저장소에 없다** — CI에서 돌리면 Dockerfile과 빌드 스크립트를 함께 살린다. trigger 경로는 파생 대신 **필터를 두지 않는** 쪽으로 해결했다(필터가 없으면 뒤처질 것이 없다). `.github/workflows/docker-images.yml` 신설 + 게이트 6건. **남은 것**: 이 job이 실제 PR에서 초록으로 도는 것을 한 번 확인한다.

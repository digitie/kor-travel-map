# Admin Feature targeted production live 인수·복구

이 runbook은 issue #741·#785만 검증한다. strict C7 runner와 state/evidence를 공유하지
않으며 C7 성공을 대신하지 않는다.

## 1. 실행 전 준비

1. n150에 배포된 Map API/UI와 Playwright executor image가 같은 exact Map commit인지
   확인한다. executor image는 mutable tag가 아니라 `sha256:...` image ID를 사용한다.
2. exact commit의 Git archive에서 아래 세 파일만 고정 snapshot 경로
   `/usr/local/lib/kor-travel-map/admin-feature-live-acceptance`에 provision한다.
   - `scripts/run-admin-feature-live-acceptance.sh`
   - `scripts/admin_feature_live_fixture.py`
   - `scripts/admin_feature_live_state.py`
   archive 내부 경로를 제거한 basename으로 설치하고 파일은 `root:root 0555`, snapshot
   directory는 `root:root 0555`로 둔다. 기존 snapshot을 in-place 수정하지 말고 새 임시
   directory에서 완성한 뒤 교체한다.
3. 같은 임시 directory에서 다음 exact-key JSON을 `source-manifest.json`으로 생성하고
   `root:root 0444`로 설치한다. `files`에는 세 설치 파일의 SHA256만 들어가며 manifest
   자신은 포함하지 않는다.

```json
{
  "files": {
    "admin_feature_live_fixture.py": "<sha256>",
    "admin_feature_live_state.py": "<sha256>",
    "run-admin-feature-live-acceptance.sh": "<sha256>"
  },
  "repository_commit": "<40-hex>",
  "version": 1
}
```

   manifest는 snapshot 임시 directory와 exact commit을 인자로 받아 다음처럼 생성한다. 이때
   directory에는 세 source 파일 외의 파일이 없어야 한다.

```bash
python3 - '<snapshot-dir>' '<40-hex>' <<'PY'
import hashlib
import json
import os
import sys
from pathlib import Path

root = Path(sys.argv[1])
names = [
    "admin_feature_live_fixture.py",
    "admin_feature_live_state.py",
    "run-admin-feature-live-acceptance.sh",
]
if set(path.name for path in root.iterdir()) != set(names):
    raise SystemExit("snapshot source file set mismatch")
payload = {
    "files": {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in names
    },
    "repository_commit": sys.argv[2],
    "version": 1,
}
manifest = root / "source-manifest.json"
manifest.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
os.chown(manifest, 0, 0)
os.chmod(manifest, 0o444)
PY
```

   runner는 `/`부터 snapshot까지 모든 ancestor가 `root:root`이고 group/world writable이
   아닌지, snapshot exact file set이 위 4개뿐인지, mode·manifest schema·세 파일 hash를
   mutation 전에 검증한다.
4. compose project 디렉터리에서 다음 값을 shell environment로만 주입한다. 실제 URL,
   password, service 이름, image ID는 이 문서나 evidence에 기록하지 않는다.

```bash
export E2E_BASE_URL='<production-ui-origin>'
export E2E_ADMIN_PASSWORD='<admin-password>'
export E2E_LIVE_ALLOW_PROD=1
export E2E_ADMIN_FEATURE_ACCEPTANCE_WRITE=1
export E2E_ADMIN_FEATURE_ACCEPTANCE_API_SERVICE='<map-api-compose-service>'
export E2E_ADMIN_FEATURE_ACCEPTANCE_UI_SERVICE='<map-ui-compose-service>'
export E2E_ADMIN_FEATURE_ACCEPTANCE_PLAYWRIGHT_IMAGE='sha256:<64-hex>'
export E2E_ADMIN_FEATURE_ACCEPTANCE_EXPECTED_GIT_COMMIT='<40-hex>'
export E2E_C7_EXPECTED_UI_ORIGIN_SHA256='<64-hex>'
export E2E_C7_EXPECTED_API_WS_ORIGIN_SHA256='<64-hex>'
```

runner는 executor의 `io.kortravelmap.c7.repository-commit`과 실행 중인 Map API/UI
image의 `org.opencontainers.image.revision`을 expected commit과 exact 비교한다. 두 runtime
container가 모두 `running+healthy`가 아니어도 mutation 전에 중단한다. worker/retry는 각각
1/0으로 고정한다. 기존 C7 origin hash guard를 재사용해 trace/screenshot/response/error 대신
상태·건수·소요 시간만 남기는 redacted reporter를 강제한다.

## 2. 실행

```bash
sudo --preserve-env=E2E_BASE_URL,E2E_ADMIN_PASSWORD,E2E_ADMIN_USERNAME,E2E_LIVE_ALLOW_PROD,E2E_ADMIN_FEATURE_ACCEPTANCE_WRITE,E2E_ADMIN_FEATURE_ACCEPTANCE_API_SERVICE,E2E_ADMIN_FEATURE_ACCEPTANCE_UI_SERVICE,E2E_ADMIN_FEATURE_ACCEPTANCE_PLAYWRIGHT_IMAGE,E2E_ADMIN_FEATURE_ACCEPTANCE_EXPECTED_GIT_COMMIT,E2E_C7_EXPECTED_UI_ORIGIN_SHA256,E2E_C7_EXPECTED_API_WS_ORIGIN_SHA256 \
  /usr/local/lib/kor-travel-map/admin-feature-live-acceptance/run-admin-feature-live-acceptance.sh run
```

고정 state root는 `/var/lib/kor-travel-map/admin-feature-live-acceptance`다. runner는
mutation 전 `BLOCKED.json`에 `run_id`와 결정적으로 파생한 owned Feature ID 6개를 쓰고
directory `fsync`까지 끝낸 다음 아래 순서로 실행한다.

1. hidden weather/price Feature와 value 각 1건을 exact owned ID로 seed
2. draft/inactive/hidden place marker와 correction Feature를 admin change request로 생성·승인
3. #741 admin bbox/marker/detail/card/UI panel과 public 404/미포함 검증
4. #785 승인된 경쟁 update 뒤 stale raw `If-Match` 412, dirty draft, explicit reload 검증
5. browser recovery-only cleanup, direct fixture cleanup, 모든 `feature.features` 참조 FK audit
6. executor create/start/wait/remove phase를 ID 원문 없이 hash journal로 기록
7. 성공 evidence 기록 뒤에만 `BLOCKED.json` 제거

## 3. 실패와 recovery

일반 assertion 실패라도 runner는 cleanup을 수행한 뒤 `test_failed_restored` BLOCKED를
유지한다. cleanup 실패·signal·SIGKILL은 `cleanup_failed`/`interrupted` 또는 마지막 durable
phase를 남긴다. BLOCKED가 있으면 새 run은 거부된다.

현재 배포와 같은 env를 다시 주입하고 다음을 실행한다.

```bash
sudo --preserve-env=E2E_BASE_URL,E2E_ADMIN_PASSWORD,E2E_ADMIN_USERNAME,E2E_LIVE_ALLOW_PROD,E2E_ADMIN_FEATURE_ACCEPTANCE_WRITE,E2E_ADMIN_FEATURE_ACCEPTANCE_API_SERVICE,E2E_ADMIN_FEATURE_ACCEPTANCE_UI_SERVICE,E2E_ADMIN_FEATURE_ACCEPTANCE_PLAYWRIGHT_IMAGE,E2E_ADMIN_FEATURE_ACCEPTANCE_EXPECTED_GIT_COMMIT,E2E_C7_EXPECTED_UI_ORIGIN_SHA256,E2E_C7_EXPECTED_API_WS_ORIGIN_SHA256 \
  /usr/local/lib/kor-travel-map/admin-feature-live-acceptance/run-admin-feature-live-acceptance.sh recover
```

recovery는 BLOCKED의 검증된 `run_id`와 결정적 owned ID 목록만 사용한다. 같은 label의 남은
executor container를 제거하고, API-owned pending request를 reject 또는 delete-approve로
종결한 뒤 status=deleted, public 404, pending=0을 확인한다. direct weather/price Feature는
`data_origin`·kind·name ownership fingerprint가 정확할 때만 두 ID를 transaction으로 삭제하고
child value를 포함한 0/0/0 cardinality와 `pg_catalog.pg_constraint`에서 발견한 모든
`feature.features(feature_id)` FK reference 0건을 audit한다. 둘 중 하나라도 실패하면 BLOCKED를
지우지 않는다. recovery-only는 add/seed/correction write를 명시적으로 거부한다. 성공 시
result를 먼저 `fsync`하고 BLOCKED unlink도 state directory `fsync`로 확정한다.

## 4. 완료 판정

- runner exit 0
- `BLOCKED.json` 없음
- 최신 `run-<run-id-sha256>/result.json`이 `phase=passed`, `status=complete`이고 result에는
  run/Feature ID 원문 대신 SHA256만 존재
- `direct-audit.json`의 features/weather_values/price_values가 모두 0
- `direct-audit.json`의 `foreign_key_references=0`
- `executor-main.json`·`executor-recovery.json`의 마지막 phase가 `removed`
- Playwright main과 recovery artifact가 root-owned 0700 evidence 아래 존재

Playwright evidence에는 response body/text, URL, run/Feature/container ID, assertion 값, trace,
screenshot을 남기지 않는다. 실제 run ID·Feature ID는 issue 코멘트에 원문으로 복사하지 않고
redacted 실행 시각, exact commit, passed/cleanup 결과만 남긴다.

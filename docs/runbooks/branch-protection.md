# GitHub branch protection 운영 절차

본 문서는 ADR-021/038과 Sprint 5 `T-204` 기준 `main` branch protection을 운영자가
설정할 때 쓰는 절차다. 목적은 `main` 직접 push, CI 미검증 merge, force-push 사고를
서버에서 차단하는 것이다.

## 1. 전제

- 저장소 관리자 권한이 필요하다.
- 모든 변경은 feature branch + PR + squash merge로 들어간다.
- 로컬 검증은 PR push 전 1차 확인이고, GitHub Actions는 merge 전 2차 gate다.
- 단일 운영자가 self-merge해야 하는 경우에도 PR 페이지에서 diff/check를 한 번 더
  확인한다. GitHub required approval은 작성자 본인의 approval을 세지 않을 수 있으므로,
  실제 1인 운영이 필요하면 repository admin bypass를 명시적으로 허용하고 이 결정을
  `docs/decisions.md`나 운영 메모에 남긴다.

## 2. 설정 위치

GitHub 웹 UI:

```text
Settings -> Branches -> Branch protection rules -> Add branch ruleset
```

branch name pattern:

```text
main
```

이미 ruleset을 쓰는 저장소라면 `Rules -> Rulesets`에서 같은 의미로 설정해도 된다.
이 문서의 정책 값이 정본이고, GitHub UI 용어가 바뀌면 가장 가까운 equivalent 항목을
선택한다.

## 3. 필수 설정

다음 항목을 켠다.

| 항목 | 값 |
|------|----|
| Require a pull request before merging | enabled |
| Required approvals | `1` |
| Dismiss stale pull request approvals when new commits are pushed | enabled 권장 |
| Require status checks to pass before merging | enabled |
| Require branches to be up to date before merging | enabled |
| Do not allow bypassing the above settings | 1인 운영 bypass가 필요 없을 때만 enabled |
| Restrict deletions | enabled |
| Do not allow force pushes | enabled |

`Require conversation resolution before merging`은 review thread를 실제로 쓰기 시작하면
enabled로 둔다. 현재 자동 에이전트 PR에서는 blocker가 아니므로 optional이다.

## 4. Required status checks 기준

현재 모든 PR에서 항상 생성되는 required check는 다음이다.

```text
lint
pytest (Python 3.11)
pytest (Python 3.12)
pytest (Python 3.13)
```

다음 check는 workflow가 path filter를 갖고 있어 해당 파일을 건드린 PR에서만 생성된다.
현재 상태에서 branch protection의 required check로 항상 걸면, check가 생성되지 않은
문서/백엔드 PR merge가 막힐 수 있다.

```text
openapi-drift
type-check + next build (Node 20)
```

이 둘은 `T-203`에서 neutral/success check가 모든 PR에 생성되도록 바꾼 뒤 required로
승격한다. 그 전까지는 PR 작성자가 변경 범위에 맞춰 `gh pr checks <PR>`에서 실행 여부를
확인하고, DTO/admin router/frontend 변경 PR 본문에 OpenAPI/frontend 검증 결과를 적는다.

## 5. Merge 정책

- merge 방식은 **Squash and merge**를 기본값으로 둔다.
- merge commit 제목은 PR 제목과 동일하게 둔다.
- merge 후 feature branch는 삭제한다.
- `git push origin main`은 운영자도 사용하지 않는다. 긴급 수정도 단명 branch + PR을
  사용한다.

## 6. 확인 명령

PR merge 전 check 상태:

```bash
gh pr checks <PR_NUMBER> --repo digitie/python-krtour-map
gh pr view <PR_NUMBER> --repo digitie/python-krtour-map \
  --json mergeStateStatus,statusCheckRollup,reviewDecision
```

branch protection API 조회:

```bash
gh api repos/digitie/python-krtour-map/branches/main/protection
```

`required_status_checks.contexts`에 §4의 always-on check가 들어 있어야 한다. `openapi`
또는 frontend check를 required로 승격한 뒤에는 문서-only PR에서 check 누락으로 merge가
막히지 않는지도 별도 smoke PR로 확인한다.

## 7. 운영 체크리스트

- [ ] branch name pattern이 `main`인지 확인.
- [ ] PR 필수, approval 1개, stale approval dismiss 설정.
- [ ] required checks: `lint`, Python 3.11/3.12/3.13 pytest.
- [ ] branch up-to-date requirement 설정.
- [ ] force-push/delete 차단.
- [ ] 1인 운영 bypass 필요 여부를 명시적으로 결정.
- [ ] T-203 이후 `openapi-drift`, `type-check + next build (Node 20)` required 승격 여부
      재검토.

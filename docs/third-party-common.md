# Common 의존성 출처

`kor-travel-common`은 GPL-3.0-or-later다. Map의 GPL 배포와 같은 라이선스 경계를 유지하며 공통 소스를 앱에 복제하지 않는다.

| 산출물 | 원천 | SHA256 |
| --- | --- | --- |
| `frontend/vendor/kor-travel-ui-0.1.0-dev.9.tgz` | digitie/kor-travel-common `aa232ad5f255233184de80eceaab2e9b6ccb00c9`(#47 병합), `packages/ui`, GPL-3.0-or-later, 수정 없음 | `b738d8824e36eb6e58d8cc6b78af7dc31233b6763248d634286044def795b403` |
| `frontend/vendor/kor-travel-tokens-0.1.0.tgz` | digitie/kor-travel-common `e28559803c1ec1134ef7ba7736b9acf4cadb9a32`, `packages/tokens`(위 UI 원천까지 변경 없음), GPL-3.0-or-later, 수정 없음 | `554ae3f6a18cbf453130b29f8a2d737ddb880101b55e14535cf8d63174b47505` |
| Python API/Dagster | digitie/kor-travel-common `aa232ad5f255233184de80eceaab2e9b6ccb00c9`, `packages/py/kor-travel-common`, GPL-3.0-or-later, Git 의존성 | 코드 pin은 각 `pyproject.toml` |

UI tgz는 Common CI `packages` lane과 같은 조건(`.nvmrc` Node 22.23.1, npm 11.19.1, 루트 `npm ci`, `npm pack -w packages/ui`)으로 다시 만들었고 Common T-217이 기록한 정규 산출물 SHA256과 byte-exact다. tokens tgz는 기존 고정 산출물 그대로다. LGPL/MIT 등 별개 라이선스로 표시하지 않는다. 각 산출물 안의 라이선스·출처 파일을 유지한다.

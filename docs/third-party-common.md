# Common 의존성 출처

`kor-travel-common`은 GPL-3.0-or-later다. Map의 GPL 배포와 같은 라이선스 경계를 유지하며 공통 소스를 앱에 복제하지 않는다.

| 산출물 | 원천 | SHA256 |
| --- | --- | --- |
| `frontend/vendor/kor-travel-ui-0.1.0-dev.6.tgz` | digitie/kor-travel-common `e28559803c1ec1134ef7ba7736b9acf4cadb9a32`, `packages/ui`, GPL-3.0-or-later, 수정 없음 | `e4945d01d9eb89ed505a95b551899fd0ecf41be66c9ee6b76246701350447e6d` |
| `frontend/vendor/kor-travel-tokens-0.1.0.tgz` | 동일 원천 `packages/tokens`, GPL-3.0-or-later, 수정 없음 | `554ae3f6a18cbf453130b29f8a2d737ddb880101b55e14535cf8d63174b47505` |
| Python API/Dagster | digitie/kor-travel-common `1f8e339c7c79f86f8952b0d4c326ab4dae56bee8`, `packages/py/kor-travel-common`, GPL-3.0-or-later, Git 의존성 | 코드 pin은 각 `pyproject.toml` |

UI·토큰 tgz는 PinVi의 검증된 고정 산출물과 byte-exact이며 재pack하지 않았다. LGPL/MIT 등 별개 라이선스로 표시하지 않는다. 각 산출물 안의 라이선스·출처 파일을 유지한다.

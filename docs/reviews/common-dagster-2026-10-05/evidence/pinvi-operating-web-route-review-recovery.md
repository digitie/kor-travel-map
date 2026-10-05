# PinVi 운영 Web route·build 입력 독립 진단

작성: 2026-10-06 KST. 판정: **설치 route 존재 및 내부 application HTTP 정상 확인**. 외부 경로의 404 원인은 이 조사만으로 확정하지 않으며 UI/auth 수용 PASS를 뜻하지 않는다.

## 대상과 직접 결과

실제 `pinvi-web-latest` image는 `sha256:1ac1a01ac5bd845bf72e04a3f96db0e6438b6095529480529af2a3361b19eec1`, source label은 `0058369c778f8c3357ee393e12e3447d7975cc1f`다. 실제 running/healthy 및 image/source를 Docker inspect로 조회 전후 확인했다. 2026-10-05T19:25:13Z와 19:25:47Z의 직접 읽기 결과다.

설치된 Next `app-paths-manifest.json`:
SHA256 `2793a2844fbd1cf03e36ae5091b6a8d72bdfe7673e34054e34e37f550779de9d`.
총 65개, admin 경로 43개. route group을 제거해 정규화하면 /admin/login과 /admin/etl 각각 1개이며, manifest가 지정하는 compiled page 파일이 실제 존재한다.

설치된 `routes-manifest.json`:
SHA256 `817072dd9c4b81549c4338a18cfcecc3ef0b15b3d27663b67965c8b7d59bd04c`.
version 3, staticRoutes 54개/dynamicRoutes 11개. staticRoutes에 /admin/login과 /admin/etl 모두 있고 basePath는 비어 있다.

설치된 `required-server-files.json`:
SHA256 `2ebb21959b2fc081793ac8e48d8ef92dae00e5bf130e72f1e1bf0d37c7fe7a93`.
필수 파일 19개, appDir 존재, config.output null. 전체 manifest나 private filesystem path는 출력하지 않았다.

컨테이너 내부 node fetch는 GET·redirect manual·요청 timeout만 사용했다. environment 값은 후보 port 선택에만 사용하고 출력하지 않았다.

| 내부 known listener | GET / | GET /admin/login | GET /admin/etl |
| --- | --- | --- | --- |
| 3000 | ECONNREFUSED | ECONNREFUSED | ECONNREFUSED |
| 12805 | 200 text/html | 200 text/html | 200 text/html |

이 결과는 외부에서 본 HTTP404가 현재 Next application의 동일 경로에 대한 내부 HTTP404와 같다는 주장을 지지하지 않는다. 프록시/경로/대상 차이 조사가 필요하다. 실제 외부 요청의 target·Host·proxy routing은 다른 독립 진단 범위이며 본인은 확인하지 않았다.

## 고정 소스와 Docker 입력 대조

immutable Git 005 source에는 `apps/web/app/(admin)/admin/login/page.tsx`, `apps/web/app/(admin)/admin/etl/page.tsx`와 admin layout이 추적되어 있다. 설치 route·compiled 파일 존재 결과와 일치한다.

고정 Web Dockerfile SHA256은 `f62decde285a63c3650c0c599fe56ad42ed596fe6408796d4b04831fcd0656a8`다. build 단계는 전체 source를 COPY하고 `npm --workspace apps/web run build`를 수행한다. runtime은 build의 apps/web/.next·public·package.json·next.config를 복사한다. 고정 package.json build는 `next build --webpack`, start는 12805이며 image Docker CMD는 next start 3000이다. 내부 실제 listener를 Dockerfile CMD 값만으로 추측하지 않고 직접 확인했다.

root .dockerignore SHA256 `9c31919e0325cd8010661b8bbe9027121e665324edd9d9372e8b6731c6991da5`는 source의 route group/admin 디렉터리를 제외하지 않는다. host .next와 node_modules는 제외해 빌드 context의 이전 산출물 유입을 막는다. apps/web 전용 .dockerignore는 없다. 이 읽기는 immutable 소스의 materialization 계약 확인이다. 실제 과거 build context 모든 bytes나 compiled bundle 전체를 source와 역비교했다고 주장하지 않는다.

## 수행 경계

직접 수행: immutable Git의 route/Dockerfile/.dockerignore/package.json 읽기, actual Docker image/source/health fence, 설치 Next manifest·compiled file 존재 확인, known 내부 listener의 GET 6개. 처음 3000만 사용한 시도는 connection 오류였고 이후 실제 알려진 후보를 확인해 12805의 200 응답을 확보했다.

NOT_RUN: 브라우저/로그인·쿠키·API 인증 동작, 프록시 수정, 서비스 변경, build/restart, 실제 source/full bundle 복원 비교, 제품 전체 테스트. GET 응답의 HTTP200을 admin 권한이나 기능 수용 성공으로 확대하지 않는다. 진행 중인 UI probe 컨테이너를 조작하지 않았다. 다른 reviewer 원문은 읽지 않았으며 private URL/host/env/credential은 기록하지 않았다.

제품 source113 PASS는 그대로이며 이번 조사에서 route COPY 누락 또는 현재 application HTTP404 결함은 재현되지 않았다. 외부 UI gate 판정은 보류한다.

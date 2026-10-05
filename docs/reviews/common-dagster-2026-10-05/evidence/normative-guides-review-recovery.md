# Common·Map·PinVi Dagster 규범 가이드 독립 검토

작성: 2026-10-06 KST. 판정: **PASS — 좁은 문서·계약 검토**. 새 제품 FULL 검증이나 운영 성공 판정으로 집계하지 않는다.

## 고정 대상과 범위

제품 정본은 Common `a960bdb114d99a2ac1b9608a77b240635806e551`, Map `1a3c4673790f51daa1a2f5ccf803d4e31673bad6`, PinVi `0058369c778f8c3357ee393e12e3447d7975cc1f`다. 세 문서 전체를 직접 읽고 다음 bytes를 확인했다.

| 문서 | SHA256 |
| --- | --- |
| Common `docs/runbooks/dagster-adoption.md` | `ed75f864e2719d1130e94013c58cda8b15d14fb87904bda50ea3c5758cee7c6d` |
| Map `docs/runbooks/common-dagster.md` | `5d199456a2ee01e600f8359c444f487a215dbd2846cd9eaaed1d9acfed9fd525` |
| PinVi 최초 검토본 | `b17feb6412cde0651f7df822e5da9a6ea822b527fbe884b3467e1291a407f19d` |
| PinVi 범위 정정 후 최종 검토본 | `0494412105ff63ad8119c9c72220397da7019d2103b44ac7b1c1b748a91f7f31` |

문서들은 별도 후속 문서 후보이며 고정 제품에 새 코드 변경이 있다고 해석하지 않는다. peer 원문은 읽지 않았다.

## 직접 확인한 계약

- Common §11의 네 TickStatus와 selector별 최신 최대 3건은 두 소비자 고정 query와 일치한다. Map query 56·73행 및 PinVi `apps/api/app/services/admin_etl.py` 221·225행 모두 `ticks(limit: 3, statuses: [STARTED, SKIPPED, SUCCESS, FAILURE])`다. Map query bytes SHA256은 `fce5e6d13f217860e3a1b022dd2f9c3656502c01b47ea87212991efcd27d8d3a`로 이전 FULL 검증과 같다.
- 1.13.24에서 nonempty statuses가 전체 이력 batch rank 경로를 피한다는 안내는 본인이 앞서 실제 설치 resolver와 SQLite control·운영 읽기 query로 검증한 범위에 한정되어 있다. 당시 동일 요약의 2.077초 결과는 특정 실제 호출 결과이며 보편적 성능 보장이 아니다. 새 tick 상태·resolver 변경 시 재검증, legacy NULL selector와 timestamp 동률에서 완전 동일하지 않을 수 있다는 caveat를 명시해 의미를 과장하지 않는다. DB 이력 삭제·schema 변경·HTTP deadline 증가를 채택 절차로 권하지 않는다.
- Map API와 Dagster의 pyproject는 실제 a960 전체 SHA를 고정한다. PinVi API는 실제 1f8e339의 [http], ETL은 73e3ff8의 [dagster]를 고정한다. PinVi 문서의 초기 ETL pin과 후속 API pin 구분이 실제 dependency와 맞는다. 모든 앱이 건강 점검 구현 a960을 소비한다고 추측하지 않는다.
- Common HTTP 고정 소스의 4MiB plain body, 10초 전체 읽기, 50ms 별도 response cleanup, RequestError 뒤 client 폐기·외부 취소 책임은 안내와 맞는다. 압축 사전 거부·response hook 거부·HTTPX auth flow 비활성화·cooperative transport 한계와 write uncertain outcome을 함께 설명한다.
- Common 건강 점검은 실제 설치 generated protobuf를 직접 로드하며 proxy health와 child ListRepositories에 각각 4초·수신 4MiB를 적용한다. 지원 module/file/package profile, 기본 __repository__ 허용 및 unsupported stateful/custom/typed metadata fail-closed 안내가 고정 구현과 맞는다. Map standalone healthcheck는 실제 `python -I -m kortravelcommon.dagster_health`와 timeout 15초를 사용한다. health 판정과 Docker 자동 restart·watchdog·orphan run 회수·shared daemon 정책을 명확히 구별한다.
- Common 소비 순서는 exact SHA/extra/lock, 실제 resolved executor, DB 소유권·멱등성, shared daemon 소유 경계, API shape/scope/cap, 운영 gate를 함께 다룬다. Map의 atomic snapshot seal과 PinVi의 배치별 partial commit을 섞지 않는다. 합성 allocation과 운영 RSS를 구별한다. 문서 검토를 운영 완료 증거로 대체하지 않는다.

## PinVi 최종 정정의 closure

최초 문서의 “이 PR의 작업이 아니다”와 일반 “검증” 제목을 초기 T-370 범위로 명시하고, 후속 Map paired 운영 절을 따르도록 바꿨다. 최종 bytes에서 이 두 변경을 역치환하면 최초 SHA256 `b17feb...`가 재현된다. 그 외 문단·dependency·tick guide는 그대로다. 초기 fixture DB 검증 설명과 후속 운영 재구축 범위가 혼동될 여지를 줄였다. 이 정정은 적절하며 새 제품 변경을 뜻하지 않는다.

## 링크와 실행 경계

세 문서의 상대 Markdown 링크 대상 파일 존재를 직접 확인했고 Common UI 계약·instance 설정 heading을 확인했다. Map의 고정 a960 GitHub 링크는 로컬 해당 Git 객체의 가이드로 확인했다. PinVi의 Common main 링크는 일반 최신 가이드 링크이며 실행 dependency의 이동 참조로 쓰지 않는다. 외부 웹 서버의 HTTP 상태·공개 배포 최신성은 이번에 확인하지 않았다. 증거 링크는 본인 진단 문서의 경로 존재만 확인했으며 다른 리뷰어 원문은 열람하지 않았다.

직접 수행: WSL Python hashlib로 문서 SHA 검증, 전체 문서 읽기, immutable `git show`/선택 `git grep`로 dependency·query·HTTP·health·Compose 대조, 상대 링크/heading 확인, PinVi 최종 문서 역치환 해시 확인.

NOT_RUN: 변경 없는 전체 제품 테스트, 새 운영 query, SSH/N150 점검, 빌드·rotation·runtime attestation·native fault·브라우저 live. 현재 진행 중인 paired rebuild의 성공을 주장하지 않는다. 이전 실제 query 증거와 이전 FULL 제품 증거는 이 문서 안내의 근거로만 연결하고 이번 직접 테스트 수에 합산하지 않는다.

발견한 차단 결함 없음. 제품 코드·공개 문서·서비스를 수정하지 않았으며 이 ignored 원문만 새로 저장했다.

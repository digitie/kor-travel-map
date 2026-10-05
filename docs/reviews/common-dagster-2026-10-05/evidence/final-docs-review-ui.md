# 최종 Map·PinVi 문서·증거 독립 리뷰 B

실행 ID: J-FINAL-DOCS-20261006-B. 검토자는 작성자와 별도이며, 상대 리뷰 원문·판정 내용은 열람하지 않았다. 저장소와 운영 서비스를 수정하지 않았다.

판정: **PASS — 문서·증거 closure 범위**. 새 P0/P1/P2/P3 finding 없음. 최종 문서 포함 exact HEAD CI, staging 전체 감사와 PR 병합은 별도 미완료 게이트다.

## 고정 기준과 검토 범위

- 최신 781파일 manifest: `map-pinvi-final-docs-reviewed-manifest-postfix.json`, SHA256 `89ac320a5f404faf667823d1deba832318a6225712ca789563e118cc199d7252`.
- 이전 manifest `6de8136a0ed71e0e375576ce43af5b85eceecdc0e5a1b07e0e34b5b6e4d9dc2c`도 그대로 보존되어 있다. 이전 대비 변경은 세 저장소 journal/resume의 네이티브 검증 범위 설명 6파일이며 나머지 775파일은 동일하다.
- 제품 고정 기준은 Common `a960bdb114d99a2ac1b9608a77b240635806e551`, Map `1a3c4673790f51daa1a2f5ccf803d4e31673bad6`, PinVi `0058369c778f8c3357ee393e12e3447d7975cc1f`다.
- 기존 제품113 manifest `8837d075991f70a65d977eee4bd8c5b641f0b7653e1fbc116ad2204204db0f2f`의 모든 파일을 위 고정 Git 객체에서 직접 해시 대조했다. 113/113 일치했다. 기존 본인 FULL PASS 원문 SHA256 `212e3f8c71b61d814cc63c50296ec59ebbedb32553103127ff07b1aae91b2fa0`의 검증을 이 불변 범위에서 이어받는다.
- 현재 narrative/guide/task 16파일, 실제 rebuild/runtime/UI/native/D1·D2 증거와 관련 링크를 검토했다. 전체 781파일은 bytes/SHA256 검증 범위이며, 전체 원문 내용을 다시 리뷰했다는 의미가 아니다. 상대 리뷰 파일은 내용 대신 보존 해시만 확인했다.

## 직접 수행한 확인

1. 최신 manifest의 781/781 파일 크기·SHA256 일치, 세 저장소 증거 복사본 일치. 원문 wrapper 76개의 raw UTF-8 해시와 original_sha256, 별도 공개 MD의 display_sha256도 불일치 0이었다. 상대 raw는 해시 계산만 수행하고 판정 근거로 사용하지 않았다.
2. 현재 16문서의 상대 파일 링크 436개가 모두 존재했다. 외부 URL 접근이나 상대 리뷰 본문·앵커 해석은 수행하지 않았다.
3. Common·Map·PinVi 가이드 해시는 각각 `ed75f864e2719d1130e94013c58cda8b15d14fb87904bda50ea3c5758cee7c6d`, `5d199456a2ee01e600f8359c444f487a215dbd2846cd9eaaed1d9acfed9fd525`, `0494412105ff63ad8119c9c72220397da7019d2103b44ac7b1c1b748a91f7f31`로 앞선 독립 normative 리뷰와 같다. 지원되는 경량 health profile, fail-closed 제한, 앱 소유 인증·URL·repository 경계, 네 상태 tick 조회와 bounded HTTP 계약에 새 규범 변경이 없다.
4. 실제 최종 재구축 영수증은 success가 boolean true, returncode 0, resumed false, outcome deployed, phase committed이고 transaction_id와 runtime attestation의 deploy_run_id가 같다. attestation `8d998cec…`의 여섯 서비스 source/image/healthy 및 소비자별 Common pin 구분과 문서 설명이 일치한다. 이 실행은 작성자가 수행했다.
5. 최종 D1/D2 영수증 SHA256 `0958cf5bf98013473beaf4ea722e9860eae9ce5ba19b49073c120024ed6ed14c`는 본인이 앞서 읽기 전용으로 관찰한 chain/D2 InvocationID, terminal result `cedf21dd…`, validation `84b0a842…`, 원본 fingerprint `f9787754…`와 같다. D1 11, M01 ACL 통과, normal/attempt0, 두 report 각각 2/2, purge 1/7, residue 0, ACTIVE/BLOCKED false를 확인했다. fresh validator 출력 byte-identical은 검토한 63c 수집기의 작성자 실행 결과이며, 본인이 validator 또는 도메인 시험을 재실행한 것은 아니다. 앞선 collector 실패는 D1/D2 실행 실패와 구분되어 보존된다.
6. 실제 UI 영수증 `38db579f…`과 세 저장소 PNG 8개는 본인이 앞서 직접 열어 시각·개인정보 리뷰한 원문과 바이트가 같다. Chromium/Firefox×Map/PinVi 4건, Map UI logout 200과 PinVi API 시험 세션 정리 204, 로그인 Secure/HttpOnly, 선택 실행 identity, 브라우저 summary 요청 abort 후 last-good/recovery, 390px 내부 스크롤·키보드 범위가 문서와 일치한다. 공유 서비스/worker 중단 시험으로 설명하지 않는다. 이미지의 계정·비밀번호·토큰·쿠키·실제 접속 URL 노출 없음이라는 기존 시각 판정을 같은 바이트에 한정해 재사용했다. 새 브라우저 실행은 하지 않았다.
7. native inheritance 영수증 `72c7f9ee…`의 이전 이미지 `5ded0abe…`와 최종 이미지 `19759750…`는 서로 다르다. 고정 Git 객체에서 Map definitions와 Common dagster/dagster_health 코드 해시를 직접 대조하여 기록된 설치 코드 해시와 일치함을 확인했다. Map 1ba→1a3의 제품 변경은 API tick query와 C7 Dockerfile뿐이다. 이전 이미지에서 실제 native raise/crash/stall 장애 시험을 했고 최종 이미지에서는 설치 코드·Dagster1.13.24 및 별도 배포 identity를 확인했다는 범위가 명확하다. 최종 이미지의 새 장애 주입 또는 PinVi의 실제 장애 주입으로 확대하지 않는다.

## 범위와 disposition

현재 journal/resume 상단은 실제 수용 완료와 exact HEAD CI·Common #28 → Map #1303 → PinVi #576 병합 대기를 구분한다. 아래의 RUNNING/NOT_RUN은 과거 기록임을 명시해 이전 실패를 지우지 않았다. T-216/T-319는 나머지 소비자·공유 장애·운영 RSS 등 전역 범위 때문에 IN_PROGRESS이고, PinVi T-371은 exact 문서 CI/merge gate 때문에 미완료다. 유한 응답·batch·pool·동시성 구조 및 합성 메모리 결과를 운영 RSS 감소율 실측으로 승격하지 않는다. 인간 dirty 변경과 다른 운영 후속도 이 작업으로 완료 처리하지 않는다.

이전 본인 제품·helper BLOCK 원문은 그대로 보존되고 후속 FIXED/PASS를 별도 원문으로 연결한다. 기존 PinVi 가이드의 초기 T-370/후속 운영 범위 P3는 수정된 불변 가이드에서 FIXED다. 이번 6문장 정정은 이전 native 시험과 최종 설치 코드·이미지 identity의 구분을 더 명시한 것으로 재검증 범위 확대가 아니다.

Common AGENTS/agent-workflow 기준으로 공개 UI/CSS·Python 복구/HTTP/health·runbook을 포함한 제품 변경은 **FULL 대상**이며 기존 113파일 독립 FULL 검토를 재사용한다. 이번 변경은 원문 보존·재검증 결과·상태/증거 연결의 closure이다. 규범·공개 API·동작·acceptance/gate를 새로 바꾸지 않아 review closure artifact 예외로 재귀적인 새 제품 FULL 리뷰를 집계하지 않는다. 가이드 3개는 이전 독립 normative 리뷰 해시를 유지한다. 작성자 대신 독립 검토자로 내린 범위 판정이며 최종 merge 담당의 staging 판단을 대신하지 않는다.

## NOT_RUN 및 남은 게이트

이번에는 운영 재구축·UI·native fault·D1/D2·validator·전체 제품 테스트를 재실행하지 않았다. 작성자의 실행 수치를 본인 테스트 수에 합산하지 않았다. 최종 문서 커밋의 CI, PR 병합, 미래 staging 전체 감사도 NOT_RUN이다. 순환 참조를 피한 generated preservation index와 이후 생성될 최종 리뷰 원문은 이 781파일 manifest의 포함 범위 밖이며, 작성자의 최종 staging 감사에서 다뤄야 한다. 본 PASS는 manifest로 고정된 문서·증거의 정확성·보존·범위·개인정보 판정이다.


보존 시각(UTC): 2026-10-05T21:07:21.207711+00:00

# Native/UI collector 엄격 검증 독립 closure — PASS 원문

검토일: 2026-10-06. 범위는 ignored 하니스와 성공 증거 승격 검증이다. 이전 narrow BLOCK 원문은 별도 보존한다. 제품 FULL PASS를 새로 집계하지 않는다.

고정 collector SHA256: 0726daf879230bd805bbe3b2269376b4887926d1dda1189ede85d0a5b2073dc0
Launcher SHA256: d404481ede05a87f6a8710a6ad5bc5b493dd416c89d434bd1ac8e5d2ac65930f
Native probe SHA256: 64813b455c2f0b3c43ef3c37f16d26788eea87d8381da2d670ccce2e911e61d3

판정: 좁은 하니스 소스 및 본인 격리 반례 기준 PASS. 기존 collector P2 두 반례 CLOSED. 실제 native/UI 운영 성공을 의미하지 않는다.

현재 native 분기는 local attestation status == "PASS"를 검사하고 autonomous_daemon_monitoring, raise/crash의 step_started/fault_cause_verified, stall의 시작/timeout/시간 겹침/coalescing 해제 플래그를 모두 is True로 검사한다. UI 분기도 local attestation PASS와 세션·cookie·repository 검증 플래그를 is True로 검사한다. image/Common source hash·commit, fault 순서, FAILURE→같은 job 수동 SUCCESS, 실제 timeout20, 동시 healthy job, 컨테이너 종료·exit/OOM 및 UI identity/source/time/capture 검증은 유지된다.

본인 직접 수행:

- outer 및 추출한 remote Python compile: PASS.
- 전체 collector를 FakePath 및 mock subprocess로 실행한 138개 반례: 정상 native/UI 2 ACCEPT, 실패 조건 136 REJECT.
- 두 기존 반례: attestation FAIL과 autonomous_daemon_monitoring 문자열 "false" 모두 REJECT, 최종 PASS receipt 쓰기 없음.
- native boolean 9필드와 UI boolean 20필드에 각각 False, "false", 1, None을 주입한 116개 검증: 모두 REJECT.
- 두 분기의 attestation status FAIL/False/"false"/None, running/exit1/OOM/receipt 누락/SSH 실패/image 불일치: 모두 REJECT.
- 정상 mock 두 경우만 최종 receipt status PASS를 쓰는 것을 메모리에서 확인했다.

재현 방법: Python3에서 현재 collector를 compile하고 AST로 remote heredoc을 추출하여 compile한다. unittest.mock.patch로 subprocess.run을 가짜 JSON 응답으로 대체하고 sys.modules pathlib의 FakePath로 읽기 및 쓰기를 격리한다. 각 실패 입력에서 예외/SystemExit와 최종 operating-evidence.json 쓰기 부재를 확인한다. 사용한 본인 테스트 사본은 /home/digitie/.cache/recovery-native-collector-closure-probe.py이며 보고서와 함께 SHA256을 전달한다.

정확한 실행 결과:
{"accepted": 2, "checks": 138, "collector_sha256": "0726daf879230bd805bbe3b2269376b4887926d1dda1189ede85d0a5b2073dc0", "compile_outer_remote": "PASS", "false_values": [false, "false", 1, null], "native_boolean_fields": 9, "prior_two_counterexamples": "CLOSED", "real_file_writes": 0, "rejected": 136, "ssh_docker_calls": 0, "ui_boolean_fields": 20}

실행 경계: 실제 SSH/Docker/DB/UID 조회/컨테이너 실행/실제 native 및 UI 결과 수집은 NOT_RUN. runtime attestation과 retry1 실행에 대한 작성자 결과를 본인 수행으로 합산하지 않는다. 테스트의 모든 receipt/private-log 쓰기는 메모리 FakePath로 대체되었다. 보고서와 본인 mock 사본만 새로 저장하고 제품·하니스 소스·기존 원문은 수정하지 않았다. 따라서 운영 성공 판정에는 실제 종료 상태와 실제 새 receipt를 별도로 엄격하게 수집해야 한다.

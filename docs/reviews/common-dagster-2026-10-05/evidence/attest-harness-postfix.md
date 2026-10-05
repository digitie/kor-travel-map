<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 Youn-sok Choi (digitie) -->

# 운영 attestation 하니스 독립 후속 리뷰 B

**하니스 PASS. J-ATTEST-P2-01/02(P2)은 FIXED.** 이는 ignored 검사 도구의 판정 정확성/안전성 검토이며 실제 운영 attestation PASS가 아니다. 제품 builtin FULL PASS는 그대로 유지한다.

실행 ID J-ATTEST-HARNESS-POSTFIX-20261006-74e89. 검증 완료 UTC 2026-10-05T15:44:10.989001+00:00/KST 2026-10-06 00:44:10. 대상 map-pinvi-runtime-attest.py의 SHA256 74e89f7c79d5c410cc2d019b7df6c7be1398382f254b65800db36bab3f2a6d16과 15,252bytes를 직접 확인했다. 이전 BLOCK 원문 SHA256 b43ce76f3d0a60015d547f70130293ed3c8c8d5204a9d990faf1e27c5bc9ba84는 불변이다. Peer 원문/실행 결과는 검토 근거로 사용하지 않았다. 제품·운영·public archive를 변경하지 않았다.

## 직접 수행

고정 하니스의 remote 함수/main을 AST로 추출·컴파일한 본인 mock 14사례: 정상 root metadata control 1개는 PASS, 음성 13개는 거절됐다. UID1000, file/directory mode, file/directory owner, file/directory inode 교체, file/directory symlink, 동일 경로 본문 변경, container identity 교체, 다른 Common installed commit, shared DB read_only false를 각각 검증했다. Root metadata는 mock하고 inode/mode/symlink/bytes는 본인 scratch 실제 파일에서 바꿨다. 운영 파일에 권한을 바꾸거나 root/DB에 접속하지 않았다.

별도 fresh 자체 venv의 실제 Python 프로세스 6사례를 실행했다. 부모 __init__와 leaf에 실행 즉시 sentinel 생성/예외가 발생하도록 한 regular, split namespace, 경로형 .pth editable, WORKDIR, Common package 5개에서 정확한 leaf SHA를 찾고 부모/leaf를 실행하지 않았다. 해당 프로그램은 본인 fixture distribution의 실제 direct_url.json commit도 읽었다. 사전 product module import 1개는 거절됐다. 임의 custom meta_path editable 구현 전부를 지원한다고 확장해 주장하지 않는다.

본인 probe:
- /home/digitie/.cache/james-runtime-attest-postfix-mock-20261006.py SHA256 2d7d9c21d44253e3dc700e24a01dec75bd9a51537b5115242f27ca40836cefff.
- mock 결과 SHA256 0a60f44102c17a1474a050048e6a8287c28888569ec02751fb30bb26b922f3ae.
- /home/digitie/.cache/james-runtime-attest-lookup-20261006.py SHA256 fb632f76711a5fb8d8f85b020c62acb0c32ac57a77cc73254dbaefe89bedbb4d.
- lookup 결과 SHA256 bf68b6ee49d3d01be15149e94dc83efd7176fea033ed3d85d32d9fe89a79c631.
- 재현은 각 probe를 python3로 실행한다. Scratch fixture/venv는 종료 때 제거했다. 실행 수치를 작성자·다른 리뷰어의 18/5 사례와 합산하지 않았다.

## Finding closure

**J-ATTEST-P2-01 — P2 FIXED.** runtime_program:55~72는 PathFinder로 각 package 경로를 순회하고 source origin .py 파일만 읽는다. :78~87에서 기존 product import/조회 중 새 product import를 거절한다. 실제 exploding-parent/leaf fixture에서 코드 실행 없이 exact source hash가 확인됐다. Source가 없는/비Python인 경우는 예외로 거절하며 부모를 import하는 fallback을 추가하지 않았다.

**J-ATTEST-P2-02 — P2 FIXED.** remote:156에서 actual UID0를 요구한다. :144~153 lstat는 directory/regular file type·root owner·0700/0600을 요구하고 dev/inode/uid/gid/mode identity를 기록한다. 초기 read 뒤 재검사 및 마지막 metadata→bytes→metadata 검사를 통해 이전 0600→0644 반례, owner/inode/symlink/본문 교체를 거절한다. 기존 container identity/health 및 committed deploy bytes fence도 유지된다. 심각도 P2를 유지하고 disposition만 FIXED로 한다.

새 P0/P1/P2/P3 finding은 확인하지 못했다.

## 고정 소비 계약·read-only·비밀 경계

고정 제품 Git pyproject를 직접 읽어 Map API/ETL Common a960bdb114d99a2ac1b9608a77b240635806e551, PinVi API Common1f8e339c7c79f86f8952b0d4c326ab4dae56bee8, PinVi ETL Common73e3ff8b9398e533806d2d1a8435292570169de3를 확인했다. 하니스는 각 repo 고정 dependency commit을 추출하며 한 Common revision을 모든 소비자의 installed commit으로 오인하지 않는다. Module bytes와 installed VCS commit을 따로 검사한다.

Installed strict deploy reader의 committed source/image/schema 계약 및 실제 shared Dagster head read 경계는 유지된다. Shared DB는 SELECT 이전 transaction READ ONLY, statement/lock/connect timeout, 정확한 database/user/head 및 dispose를 요구한다. Docker/container/SQLAlchemy 오류의 DSN/stderr/원문 예외를 receipt에 출력하지 않는다. 이 내용은 정적 검토와 local fake 검증이며 실제 production DB 접근의 결과는 아니다.

## 인접 native launcher

최신 map-native-runtime-probe-launch.py SHA256 58bb3a415c094266bc6369756137c62fc285912640a6ab8d3c3b0964abd408ae의 remote probe64813b455c2f0b3c43ef3c37f16d26788eea87d8381da2d670ccce2e911e61d3 assert가 실행 전 추가된 것을 확인했다.

Attested image ID와 현재 operating image를 비교하고 /work tmpfs512MiB·정확한 probe file readonly bind·/evidence만 writable bind를 사용한다. runtime.env가 있는 전체 root bind나 host environment 주입을 하지 않는다. /work/native-runtime-instance는 사전 생성하지 않아 probe의 mkdir(exist_ok=False) 계약과 맞다. Network none·memory3g·CPU2를 유지한다. Launcher 구성은 정적 PASS이며 실제 Docker mount/프로세스 실행은 NOT_RUN이다.

## NOT_RUN과 판정 제한

Full-success operating attestation, SSH/N150 inspect/exec, 실제 shared DB query, native launcher/fault probe, 새로운 운영 pair rebuild/live는 **NOT_RUN**이다. 실제 deploy/image/source가 기대치와 일치하여 성공했다는 receipt는 본인이 만들지 않았다. 제품 FULL 리뷰나 실제 live 완료로 집계하지 않는다. Public archive도 추가하지 않았다.

**최종: ignored 하니스 PASS, 두 P2 FIXED. 실제 운영 성공 gate는 미완료이며 제품 builtin FULL PASS 불변.**

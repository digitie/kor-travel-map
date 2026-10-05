# retry3 D1/D2 terminal 및 validation collector 좁은 독립 리뷰

판정: **PASS — collector 수정의 정적·자체 fixture 경계와 실제 기존 종료 증거의 읽기 전용 확인**. 신규 collector의 실제 실행·공식 validator 재실행은 NOT_RUN이며 최종 operating PASS receipt를 이 보고서에서 생성하지 않았다. 제품 FULL113 판정과 기존 실제 overlay 판정은 별도 원문으로 유지한다.

## 고정 입력과 변경 범위

- 기존 collector: 35d64f8865958fb24028fe65a1925b8a5521d1b15c2a6c433402515247d618e4. 원본 불변.
- validation 수정 생성기: 5f7c8e06b9cbd2b9789802c2a195997e44ef9e942a0a015056b30cdb17877073.
- 중간 collector: c7e2ce7c0abaa85191407de355a5bc533d4037fc71973981fccee614ad98c3b7.
- metadata seal 생성기: a91a2c92e57e01571f213d90d8a6ae1550f01fd6fbd16ec3dd65d279c9efc70b.
- 최종 map-pinvi-chain16-ticks-retry3-collect-closure.py: 63c08d0466d564982f321becf5d4ecabfe19b57636fa8b61fc3ae19a44f1370c.
- 제품 Common a960bdb114d99a2ac1b9608a77b240635806e551 / Map 1a3c4673790f51daa1a2f5ccf803d4e31673bad6 / PinVi 0058369c778f8c3357ee393e12e3447d7975cc1f 변경 없음.

## 수정의 의미 및 closure

기존 canonical validator가 성공 시 validation.json을 생성하지만 종전 snapshot은 result.json만 제외하여 exact-file-set 검증에서 이미 생성된 validation.json을 추가 파일로 취급했다. 최종 수정은 원본 validation의 정확한 7개 키, normal/attempt0/64 lifecycle/2 reports/version1, 원본 fingerprint와 바이트를 먼저 고정한다. 검증된 result와 validation 두 파일만 snapshot 복사에서 제외하고 기존 공식 validator를 실행한다. 생성된 validation은 원본과 byte-identical이어야 하며 나머지 snapshot fingerprint도 일치해야 한다. 원본 result/validation/전체 evidence는 이후 다시 확인한다.

직접 equality에서 False와 0 등은 같은 값으로 취급될 수 있지만 최종 canonical 출력과 바이트 동일 검증이 이를 차단한다. 자체 bool-attempt 및 FK 값 변조 반례도 REJECT였다. direct_foreign_key_constraints_checked 값은 임의 고정 수치로 대체하지 않고 공식 재생성 출력과 동일해야 한다.

원본 및 snapshot root/entry의 root UID/GID, directory0700/file0600, regular-file/directory와 symlink 거부가 복사 전에 적용된다. copy가 원본의 잘못된 소유자·권한을 정상화해 숨기는 경로를 막는다. 기존 terminal invocation, D1 실제 container exit0/OOMfalse, overlay/source/image, D2 identity, 운영 6개 image 및 lane-clean 검사는 유지한다. 원본 파일 제외 범위를 넓히거나 공식 validator를 수정하지 않는다.

## 직접 수행한 검사

WSL Ubuntu-26.04에서 Python AST로 생성기 두 단계를 가상 Path에 실행해 35d6 → c7e → 63c 최종 바이트를 정확히 재현했다. 원본/최종 collector의 remote body compile도 PASS였다. 실제 제품·운영 helper를 실행하지 않았다.

최종 remote body에서 snapshot/fingerprint/validation 경계를 추출해 자체 root-owned 임시 디렉터리의 실제 파일·권한을 사용했다. **20 cases PASS: 정상 1 + 거부 19**. 거부 사례는 validation 누락·추가 키·잘못된 lifecycle 수·bool attempt·version·mode·FK 값 변조, root/file/directory 권한, UID/GID, symlink/FIFO, 추가 파일, 원본 bytes/mode drift, validator validation bytes 및 다른 evidence drift이다. 공식 validator는 이 fixture에서 exact-file-set과 출력 바이트 계약을 재현하는 대역이며 실제 canonical validator 수행으로 집계하지 않는다.

실행 명령 경계: wsl -d Ubuntu-26.04 -u root -- bash -lc 에서 stdin Python scratch; generator AST/compile; 실제 remote 읽기 전용 Python은 승인된 기존 SSH transport를 재사용했다. 최초 자체 fixture 실행의 Path 이름 누락을 수정한 뒤 20건 전체가 완료됐다. 대상 helper/product 수정은 없었다.

## 실제 기존 종료 증거 — 직접 읽기 전용 확인

실제 chain invocation e95d3c64de9e4a7296c186cb22143b50은 ActiveState=active, SubState=exited, Result=success, ExecMainStatus=0이었다. 실행 중 activating 상태를 success로 오인한 결과가 아니다.

D1 retained container 00e70a1236c2fcb2d803072b76d7fdb10682c299c298fbc888acac0266d3edbc는 exited/exit0/OOMfalse이며 image는 실제 overlay 검증한 sha256:871577c770a18be619c196bd3b9524075b9bf3226e13fe32ddc86e2e040224a4와 같았다.

launch 이후 이전 run 목록에 없는 신규 D2 결과는 한 건이었다: phase=passed, status=complete, recovery_attempt=0, execution identity SHA256 43f38a553319234a271dda48588b2db05d7eed27ab76d6af505cf60f37640387. result 원문 SHA256 cedf21ddd6bba89e61b0fb0f98363d30e461a06ee3bfc960384846e4e4c57070.

기존 validation 원문 SHA256 84b0a84265af4a2d773467720b7d5f293e702baa5fe38ea7455a32e8267ae935. 값은 version1/normal/evidence-validated/attempt0/lifecycle64/reports2/FK constraints21이었다. 실제 원본 root 및 모든 entry의 UID/GID0·0700/0600·regular/directory가 통과했고 result/validation bytes 재확인이 일치했다. ACTIVE/BLOCKED는 존재 및 dangling symlink 모두 없었다.

이 실제 읽기는 기존 결과의 terminal/metadata/bytes 관측이다. 공식 validator 재실행, D1 passed-count와 전체 D2 audit의 신규 collector 최종 검증을 대신하지 않는다. 그 실행은 root 담당이며 이 원문 시점 NOT_RUN이다. 자체 안전 요약 cache SHA256 a066565708ca98dd5d3796010d9e506c69e150f0885d3bd64d994a740d01343c.

## 수행하지 않은 것

새 build/tag/repin/rename/cleanup, D1/D2 재실행, native fault, browser/UI, 서비스·DB·제품 수정 및 PR 작업을 수행하지 않았다. peer 원문은 열람하지 않았다. 이 좁은 PASS는 제품 변경·새 운영 검사 성공으로 확대하지 않는다.

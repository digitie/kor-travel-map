# Map D1·D2 retry2 ESM overlay 하니스 독립 검토

판정: **PASS — 아래 고정 bytes의 좁은 정적·로컬 하니스 검토**. 추가 blocking finding은 발견하지 않았다. Common a960 / Map 1a3 / PinVi 005 제품 FULL113 판정과 구분한다. 실제 derived image build·archive 이동·repin·D1/D2는 이번 검토에서 **NOT_RUN**이다.

## 고정한 검토 bytes

| 대상 | SHA256 |
| --- | --- |
| ESM overlay helper | ee825d52292a9126c17ab26f73a0b04eeccc7d2a4c4273fe929b1ca86a187977 |
| retry2 chain shell | a815ecd317f19bb268e816da02e06a065973eacc0d89bba17d4c6952f095c694 |
| map-chain-ticks-retry2-prepare.py | 162c07eabc9edba023cbd2b8ef6c3396fe3d97f6ef3c08af0f2be55eb245a5b0 |
| map-pinvi-chain16-ticks-retry2-launch.py | 89f40551efd25c75f6a71460931f9d70cf18d800c00b7ba8e5f3fce35db43eaa |
| map-chain-owned-archive-preserve-retry1.py | f60479b6738a690a5b6a2b528cb81c0255b2728221914f764833e68b942b1448 |
| map-pinvi-chain16-ticks-retry2-collect.py | 4def75e6bcbe9eaf0c9ee03a8b13da1c4774c0928a36c0552438bf18034210d7 |
| map-chain-ticks-retry2-collector-seal.py | ce04c1d7c125679cde90004323d9914bab65e50a5ab6a352f39b8f1d76fa6516 |

최초 a3c16 overlay는 legacy layer.tar 이름만 처리했지만 최종 검토 bytes는 manifest가 선택한 config/마지막 layer를 사용해 OCI blob 이름도 지원한다. 초기 body를 최종 실행 성공으로 승격하지 않았으며 어떤 버전도 운영 실행하지 않았다.

## source·격리·증거 연결

생성기는 fixed Map 1a3의 package.json을 Git object에서 읽고 hash를 봉인한다. 실제 before hash는 `493836767291ac8c77515eb3820aa3a55068b39144e7ad0fca9489c408733cff`이다. patch는 이 hash 및 type 부재를 확인하고 type=module 한 key를 추가한다. own cache scratch의 실제 Node와 Docker RUN 형태의 /bin/sh -c 인용으로 실행해 exit0·유효 JSON·마지막 newline을 확인했다. 제품 또는 Docker filesystem은 수정하지 않았다.

own parent tag는 기존 image ID를 보존하고 derived tag/proof 경로는 새 이름·부재 검사를 사용한다. 네트워크 없는 빌드의 Dockerfile은 해당 parent와 한 JSON patch RUN 및 mode/parent labels로 제한된다. derived RootFS는 parent 전체 layer prefix+한 추가 layer여야 하며, docker save의 selected config bytes SHA가 실제 child image ID와 일치하고 diff_ids도 inspect RootFS와 일치해야 한다.

stream parser는 큰 base layer를 디스크에 저장하지 않는다. candidate 한 파일 최대8MiB·총128MiB, manifest1MiB, gzip 해제8MiB 상한을 확인했다. 최종 layer의 정규 파일은 frontend/package.json 한 개만 허용하며 symlink/hardlink/whiteout/예상외 file·directory와 중복 package를 거부한다. after JSON에서 type을 제거한 결과가 fixed before JSON과 정확히 같아야 한다. 이런 layer whitelist는 parent prefix만 확인하던 제안의 나머지 source 변경 경계를 보강한다.

stageC 뒤·repin 전에 overlay가 실행되며 기존 공식 repin과 M01/D1/D2 흐름을 유지한다. D1은 같은 selected derived immutable ID를 사용하고 기존 네 spec/assertion, six env allowlist, 전체 private stdout, strict exit 경계를 유지한다. 실패한 원본 image/container/log/source archive는 삭제하지 않는다. preserve의 구조는 이전 검토된 no-replace/dev+inode/UID/proc/allowed-directory/lane guard를 유지하고 새 failed own invocation·목적지 namespace에만 맞췄다.

최신 collector seal은 실제 overlay proof를 읽고 PASS/source/semantic one-key/파일 whitelist/derived ID를 검사한다. actual image mode/parent labels, 설치된 sealed helper hash와 결합하며, retained own D1 container가 같은 image·exited·exit0·OOM 아님·task label임을 확인한다. 공식 D2 result의 execution identity도 같은 derived image ID를 사용한다. 최종 receipt에 proof 내용/hash와 D1 container ID를 포함한다. 초기 collector의 source label만으로 판단하던 연결 경계는 이 현재본에서 보강됐다.

## 직접 수행한 검증

Python stdin AST probe로 현재 실제 parser·seal 검증식을 실행했다. subprocess/Docker/Path 읽기는 결정론적 local fake로 대체했다. 실제 SSH·Docker·image save는 실행하지 않았고 원본 helper를 호출하지 않았다.

- overlay parser **12건**: legacy/OCI/OCI-gzip 정상 3건 PASS; 추가 file, symlink, hardlink, 중복 package, whiteout, semantic extra key, layer digest 불일치, config digest 불일치, gzip expansion cap 9건 REJECT.
- collector seal **15건**: 정상 1건 PASS; false/문자열 false status, derived/source 불일치, semantic extra, unexpected file, parent/mode label 불일치, helper hash drift, D1 image/exit/OOM/status/task label 불일치 14건 REJECT.
- 생성기 AST의 읽기·대입만 평가해 실제 overlay/chain/launch/preserve bytes를 정확히 재현했다. 별도 seal을 적용한 collector도 실제 파일과 BYTE_EXACT였다. 생성기나 seal의 쓰기 부분은 실행하지 않았다.
- outer Python **6파일 compile**, 완전 치환 launcher2/collector1/preserve1 Python 블록 compile, 치환 shell3개와 chain bash -n 모두 PASS.
- Node JSON patch의 실제 로컬 scratch·shell 인용 실행 PASS. 제품 source 또는 원본 저장소에 쓰지 않았다.

collector seal probe의 첫 fake 응답은 Docker inspect 배열이 아니라 dictionary여서 검증 전 KeyError가 났다. fake를 실제 Docker inspect 배열 계약에 맞춘 뒤 위15건을 재검증했다. 제품/하니스 코드는 수정하지 않았다. 작성자 및 다른 리뷰어의 실행 수치를 위 직접 수행 결과에 합산하지 않았다.

## 운영 판정 경계

이 PASS는 sealed 테스트 하니스의 검토 결과다. 새 image 실존·actual overlay proof·rootfs/source 결과, 새 D1/D2 strict terminal receipt와 purge/lane 상태는 아직 본인이 실행·확인하지 않았다. 기존 제품 FULL113·여섯 operating image attestation·UI4 PASS·이전 이미지 native inheritance를 새 derived test image 실행 성공으로 집계하지 않는다.

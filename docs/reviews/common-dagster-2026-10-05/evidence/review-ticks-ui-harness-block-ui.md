# ticks UI 하니스 초기 독립 정적 리뷰

<!-- SPDX-License-Identifier: MIT -->
<!-- SPDX-FileCopyrightText: 2026 kor-travel contributors -->

판정: **하니스 BLOCK**. J-TICKS-HARNESS-P2-01 OPEN. 제품 현재885 FULL BLOCK/C7 finding 및 기존 native 실제 PASS와 별도다.

검토 bytes:
- map-pinvi-operating-ui-ticks-launch.py a49fdfe14d2b7ecaef31ec1bb765cad50a22a882fed2ec356e90ce3deca67dbe
- map-pinvi-operating-ticks-test-collect.py 291bb6c5930feaa743d00930a6dc48d81db7c862c03f99172a8f99eb85384aea
- map-operating-ticks-screenshots-collect.py a1aa5b196d0de4fe3b585a123015c83befff65068d6f4942b77eb24a861f2a3e

## J-TICKS-HARNESS-P2-01 — receipt output/input 경로 불일치

P2 OPEN. collector91은 kind ui일 때 기존 map-pinvi-ui-operating-evidence.json을 출력한다. screenshots9는 새 map-pinvi-ui-operating-ticks-evidence.json을 읽는다. 따라서 네 실제 case가 통과해도 새 screenshot collector가 결과를 찾지 못한다. 기존 receipt가 있으면 collector가 immutable gate에서 막히는 별도 혼동도 생긴다.

최소 수정: UI-only collector 최종 target을 명시한 ticks receipt 경로로 맞춘다. 실제 실행 없이 두 path literal을 비교해 확인한 실패 시나리오다.

그 외 검토: 새 evidence-ticks namespace와 absent/canonical0700 mkdir, 별도 UUID·runtime-ticks-attestation·identity/container/source 연결,1.60 pinned image, strict boolean·정확한 네 조합/여덟 PNG digest 및 시간 경계, staging/atomic promotion을 유지한다. native branch는 kind ui assert로 실행되지 않으며 native 기존 증거를 덮어쓰지 않는다. browser assertion MJS7e4는 기존 검토 source 그대로다.

세 helper의 Map885 provenance는 현재 제품C7 P1로 rollout 승인이 보류된 범위다. 차기 C7fixed source가 새 SHA가 되면 attestation/pin literals를 동일 candidate로 다시 연결해야 한다. 현재 정적 준비만으로 실제885/새후속 rollout UI 성공을 주장하지 않는다.

EXECUTED: 세 파일 source/hash 읽기, local Python3 및 완전 치환 UI remote2 compile.
NOT_RUN: 하니스 main/운영 launch/SSH/인증/브라우저/실제 receipt·PNG 다운로드·시각·개인정보 검사. 소스·제품·공개 archive·기존 원문 수정 없음.

검토/보존 시각(UTC): 2026-10-05T18:16:57.355492+00:00

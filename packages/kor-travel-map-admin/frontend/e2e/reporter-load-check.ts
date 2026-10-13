import type { Reporter } from "@playwright/test/reporter";

import C7RedactedReporter from "./c7-redacted-reporter";
import MockedFailureReporter from "./mocked-failure-reporter";

/**
 * `npm run e2e:list` 전용 reporter — 커스텀 reporter를 **로드만** 한다.
 *
 * reporter도 spec처럼 Playwright의 CommonJS 변환으로 `require()`된다. 그래서 ESM 전용
 * 패키지를 import하면 실제 실행에서만 죽는다. 그런데 두 reporter를 그대로 `--list`에
 * 걸면 `onEnd`가 돌아 파일을 쓰거나(C7 요약) 실행 env를 요구한다(mocked checkpoint).
 * 이 reporter는 둘의 모듈을 값으로 참조해 import 그래프 전체를 require시키되 인스턴스는
 * 만들지 않는다 — 훅이 없으니 아무것도 쓰지 않는다. `printsToStdio()`가 false라
 * Playwright가 list-mode reporter를 앞에 붙여 목록·로드 오류를 그대로 출력한다.
 */
const LOADED_REPORTERS: readonly unknown[] = [
  C7RedactedReporter,
  MockedFailureReporter,
];

export default class ReporterLoadCheck implements Reporter {
  printsToStdio(): boolean {
    return LOADED_REPORTERS.length === 0;
  }
}

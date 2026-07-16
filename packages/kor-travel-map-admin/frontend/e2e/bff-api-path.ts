const BFF_API_PREFIX = "/api/proxy";

/**
 * mocked 브라우저 요청이 인증 BFF를 반드시 통과했는지 검증하고 backend API
 * pathname으로 되돌린다. direct backend 호출은 테스트 실패로 처리한다.
 */
export function bffApiPath(requestUrl: string): string {
  const pathname = new URL(requestUrl).pathname;
  if (!pathname.startsWith(`${BFF_API_PREFIX}/`)) {
    throw new Error(`BFF를 우회한 API 요청입니다: ${pathname}`);
  }
  return pathname.slice(BFF_API_PREFIX.length);
}

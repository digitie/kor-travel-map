export const ADMIN_FEATURE_CREATE_TOKEN_ENV =
  "KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN";
export const ADMIN_FEATURE_CREATE_TOKEN_HEADER =
  "X-Kor-Travel-Map-Admin-Feature-Create-Token";
export const ADMIN_FEATURE_CREATE_PATH = "/v1/admin/features";

export class ManualFeatureCreateCredentialError extends Error {
  constructor() {
    super("수동 Feature 생성 BFF raw token이 설정되지 않았습니다.");
    this.name = "ManualFeatureCreateCredentialError";
  }
}

export function manualFeatureCreateToken(
  env: Record<string, string | undefined> = process.env,
): string {
  const token = env[ADMIN_FEATURE_CREATE_TOKEN_ENV];
  if (
    token === undefined ||
    token.length < 32 ||
    /\s/.test(token)
  ) {
    throw new ManualFeatureCreateCredentialError();
  }
  return token;
}

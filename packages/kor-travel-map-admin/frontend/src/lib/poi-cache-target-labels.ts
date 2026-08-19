/**
 * POI cache target enum → 한글 라벨.
 *
 * `design.md` §Copy는 enum 값을 raw로 렌더하지 않는다고 못 박는다. 값 정본은 API
 * 스키마이고, 이 파일은 그 값을 화면 낱말로 옮기는 **유일한 표**다.
 *
 * 화면과 live 스펙이 **같은 표를 읽어야** 한다. 라벨이 바뀌었는데 스펙이 옛 문자열을
 * 들고 있으면 CI는 green이고 prod C7 실행에서만 죽는다 — 실제로 스펙이 raw enum
 * (`center_radius`/`provider_default`)을 단언한 채 남아 그렇게 죽었다
 * (`docs/journal.md` 2026-08-19).
 */
export const POI_SCOPE_MODE_LABELS: Record<string, string> = {
  center_radius: "중심점 반경",
  sigungu_by_radius: "시군구 반경",
};

export const POI_REFRESH_POLICY_LABELS: Record<string, string> = {
  provider_default: "provider 기본",
  follow_system: "시스템 추종",
  allow_targeted: "대상 갱신 허용",
  disabled: "비활성화",
};

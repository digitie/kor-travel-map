export interface FeatureAddressValues {
  addressAdmin: string;
  addressExtraJson: string;
  addressLegal: string;
  addressRoad: string;
  adminDongCode: string;
  legalDongCode: string;
  roadAddressManagementNo: string;
  roadNameCode: string;
  sidoCode: string;
  sigunguCode: string;
}

export type FeatureAddressField = keyof FeatureAddressValues;

const ADDRESS_CODE_RULES: Record<
  Extract<
    FeatureAddressField,
    | "adminDongCode"
    | "legalDongCode"
    | "roadAddressManagementNo"
    | "roadNameCode"
    | "sidoCode"
    | "sigunguCode"
  >,
  { label: string; length: number }
> = {
  adminDongCode: { label: "행정동 코드", length: 10 },
  legalDongCode: { label: "법정동 코드", length: 10 },
  roadAddressManagementNo: { label: "도로명주소 관리번호", length: 25 },
  roadNameCode: { label: "도로명 코드", length: 12 },
  sidoCode: { label: "시도 코드", length: 2 },
  sigunguCode: { label: "시군구 코드", length: 5 },
};

export function addressCodeError(
  field: keyof typeof ADDRESS_CODE_RULES,
  value: string,
): string | undefined {
  const raw = value.trim();
  if (raw.length === 0) return undefined;
  const rule = ADDRESS_CODE_RULES[field];
  if (!/^\d+$/.test(raw)) {
    return `${rule.label}는 ${rule.length}자리 숫자여야 합니다.`;
  }
  if (raw.length !== rule.length) {
    return `${rule.label}는 ${rule.length}자리여야 합니다.`;
  }
  return undefined;
}

export function validateAddressCodes(
  values: Pick<FeatureAddressValues, keyof typeof ADDRESS_CODE_RULES>,
): void {
  for (const field of Object.keys(ADDRESS_CODE_RULES) as Array<
    keyof typeof ADDRESS_CODE_RULES
  >) {
    const error = addressCodeError(field, values[field]);
    if (error) throw new Error(error);
  }
}

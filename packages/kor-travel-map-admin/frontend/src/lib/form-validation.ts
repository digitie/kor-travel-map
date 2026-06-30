/**
 * 경량 폼 검증 유틸 (T-218a).
 *
 * admin/ops 폼 화면은 controlled `useState` 기반이고 react-hook-form을 쓰지 않는다.
 * 제출 시 필드별 검증 메시지와 "첫 에러 필드"(포커스 이동용)를 한 번에 계산하기 위한
 * 프레임워크 비의존 헬퍼다. 신규 런타임 의존성 없음.
 */

export type FieldValidator<T> = (value: T[keyof T], values: T) => string | null;

export type FieldRule<T> = {
  /** 검증 대상 필드 키. `errors`/`firstErrorField`의 키가 된다. */
  field: keyof T & string;
  /** null이면 통과, string이면 에러 메시지. */
  validate: FieldValidator<T>;
};

export type ValidationResult<T> = {
  isValid: boolean;
  /** 필드별 첫 에러 메시지(필드당 1개). */
  errors: Partial<Record<keyof T & string, string>>;
  /** 규칙 선언 순서 기준 첫 에러 필드(포커스 이동용). 없으면 null. */
  firstErrorField: (keyof T & string) | null;
};

/**
 * 규칙 선언 순서대로 검증한다. 한 필드에 여러 규칙이 있으면 먼저 실패한 메시지만 남긴다.
 * `firstErrorField`는 규칙 순서 기준 첫 실패 필드라, 폼 레이아웃 순서대로 규칙을 선언하면
 * 화면 최상단 에러 필드로 포커스를 옮길 수 있다.
 */
export function validateForm<T extends Record<string, unknown>>(
  values: T,
  rules: Array<FieldRule<T>>,
): ValidationResult<T> {
  const errors: Partial<Record<keyof T & string, string>> = {};
  let firstErrorField: (keyof T & string) | null = null;

  for (const rule of rules) {
    if (errors[rule.field] !== undefined) {
      // 같은 필드의 후속 규칙은 첫 에러가 이미 잡혔으면 건너뛴다.
      continue;
    }
    const message = rule.validate(values[rule.field], values);
    if (message !== null) {
      errors[rule.field] = message;
      if (firstErrorField === null) {
        firstErrorField = rule.field;
      }
    }
  }

  return {
    isValid: firstErrorField === null,
    errors,
    firstErrorField,
  };
}

/** 공백 trim 후 비어있지 않은 문자열인지. */
export function required<T>(message = "필수 입력 항목입니다."): FieldValidator<T> {
  return (value) => {
    if (value === null || value === undefined) {
      return message;
    }
    if (typeof value === "string" && value.trim().length === 0) {
      return message;
    }
    return null;
  };
}

/** 유한한 숫자로 파싱되는지(+선택 범위). 빈 문자열은 통과시키므로 `required`와 조합한다. */
export function numberInRange<T>(
  options: { min?: number; max?: number; message?: string } = {},
): FieldValidator<T> {
  const { min, max } = options;
  return (value) => {
    if (value === null || value === undefined || value === "") {
      return null;
    }
    const parsed = typeof value === "number" ? value : Number(value);
    if (!Number.isFinite(parsed)) {
      return options.message ?? "숫자를 입력하세요.";
    }
    if (min !== undefined && parsed < min) {
      return options.message ?? `${min} 이상이어야 합니다.`;
    }
    if (max !== undefined && parsed > max) {
      return options.message ?? `${max} 이하여야 합니다.`;
    }
    return null;
  };
}

export const KOREA_COORD_BOUNDS = {
  lon: { min: 124, max: 132 },
  lat: { min: 33, max: 39.5 },
} as const;

export const KOREA_COORD_MESSAGE =
  "좌표는 대한민국 범위 안의 숫자로 입력하세요. 경도는 124~132, 위도는 33~39.5 사이입니다.";

/** WGS84 경도(lon): 대한민국 권역 [124, 132]. */
export function koreaLongitude<T>(
  message = KOREA_COORD_MESSAGE,
): FieldValidator<T> {
  return numberInRange({
    min: KOREA_COORD_BOUNDS.lon.min,
    max: KOREA_COORD_BOUNDS.lon.max,
    message,
  });
}

/** WGS84 위도(lat): 대한민국 권역 [33, 39.5]. */
export function koreaLatitude<T>(
  message = KOREA_COORD_MESSAGE,
): FieldValidator<T> {
  return numberInRange({
    min: KOREA_COORD_BOUNDS.lat.min,
    max: KOREA_COORD_BOUNDS.lat.max,
    message,
  });
}

export function isKoreaCoordinate(lon: number, lat: number): boolean {
  return (
    Number.isFinite(lon) &&
    Number.isFinite(lat) &&
    lon >= KOREA_COORD_BOUNDS.lon.min &&
    lon <= KOREA_COORD_BOUNDS.lon.max &&
    lat >= KOREA_COORD_BOUNDS.lat.min &&
    lat <= KOREA_COORD_BOUNDS.lat.max
  );
}

/** 빈 값은 허용하고, 입력된 경우에는 한국 전화번호/국제번호에서 흔한 문자를 허용한다. */
export function phoneNumber<T>(
  message = "전화번호는 숫자, 하이픈, 괄호, 공백, +만 사용할 수 있습니다.",
): FieldValidator<T> {
  return (value) => {
    if (value === null || value === undefined || value === "") return null;
    if (typeof value !== "string") return message;
    const raw = value.trim();
    if (raw.length === 0) return null;
    const digits = raw.replace(/\D/g, "");
    if (digits.length < 7 || digits.length > 15) return message;
    return /^\+?[0-9][0-9()\-\s]{6,24}$/.test(raw) ? null : message;
  };
}

/** 빈 값은 허용하고, 입력된 경우에는 http(s) URL만 허용한다. */
export function httpUrl<T>(
  label = "웹사이트 주소",
): FieldValidator<T> {
  return (value) => {
    if (value === null || value === undefined || value === "") return null;
    if (typeof value !== "string") {
      return `${label}는 http:// 또는 https://로 시작해야 합니다.`;
    }
    const raw = value.trim();
    if (raw.length === 0) return null;
    let parsed: URL;
    try {
      parsed = new URL(raw);
    } catch {
      return `${label}는 http:// 또는 https://로 시작해야 합니다.`;
    }
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      return `${label}는 http:// 또는 https://로 시작해야 합니다.`;
    }
    return null;
  };
}

/** JSON으로 파싱되는지. 빈 문자열은 통과시키므로 선택 payload에 적합하다. */
export function jsonObject<T>(
  message = "올바른 JSON 형식이 아닙니다.",
): FieldValidator<T> {
  return (value) => {
    if (value === null || value === undefined || value === "") {
      return null;
    }
    if (typeof value !== "string") {
      return message;
    }
    try {
      JSON.parse(value);
      return null;
    } catch {
      return message;
    }
  };
}

/** 여러 검증기를 순서대로 적용해 첫 실패 메시지를 반환한다. */
export function combine<T>(
  ...validators: Array<FieldValidator<T>>
): FieldValidator<T> {
  return (value, values) => {
    for (const validator of validators) {
      const message = validator(value, values);
      if (message !== null) {
        return message;
      }
    }
    return null;
  };
}

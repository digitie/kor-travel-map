export function envOrDefault(environment, name, fallback) {
  return environment[name] || fallback;
}

export function frontendBuildInputs(environment = process.env) {
  const vworldApiKey = envOrDefault(
    environment,
    "NEXT_PUBLIC_VWORLD_API_KEY",
    "",
  );
  return [
    [
      "NEXT_PUBLIC_KOR_TRAVEL_MAP_API",
      envOrDefault(
        environment,
        "NEXT_PUBLIC_KOR_TRAVEL_MAP_API",
        "http://127.0.0.1:12701",
      ),
    ],
    [
      "NEXT_PUBLIC_KOR_TRAVEL_MAP_DAGSTER_URL",
      envOrDefault(
        environment,
        "NEXT_PUBLIC_KOR_TRAVEL_MAP_DAGSTER_URL",
        "http://127.0.0.1:12702",
      ),
    ],
    [
      "NEXT_PUBLIC_KOR_TRAVEL_GEO_BASE_URL",
      envOrDefault(
        environment,
        "NEXT_PUBLIC_KOR_TRAVEL_GEO_BASE_URL",
        "http://127.0.0.1:12501",
      ),
    ],
    ["NEXT_PUBLIC_VWORLD_API_KEY", vworldApiKey],
    // geo 소비자 키는 VWorld 키로 떨어지지 않는다 — VWorld 키는 kor-travel-geo가
    // 상류로 나갈 때 쓰는 것이고 geo는 그 값을 401(E0401)로 거절한다. 사슬로 이어
    // 두면 "설정이 있다"는 착시만 만들고 실패를 첫 요청까지 미룬다(T-VN-H46B).
    [
      "NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY",
      envOrDefault(environment, "NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY", ""),
    ],
  ];
}

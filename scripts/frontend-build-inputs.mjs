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
    [
      "NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY",
      envOrDefault(
        environment,
        "NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY",
        "",
      ),
    ],
  ];
}

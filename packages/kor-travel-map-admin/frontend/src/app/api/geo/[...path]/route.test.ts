import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

const VALID_GEO_API_KEY = "G".repeat(32);

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe("geo BFF credential boundary", () => {
  it("requires the server-only Geo key even when public aliases exist", async () => {
    vi.stubEnv("KOR_TRAVEL_GEO_API_KEY", "");
    vi.stubEnv("KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY", "root-geo-key");
    vi.stubEnv("NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY", "public-geo-key");
    vi.stubEnv("NEXT_PUBLIC_VWORLD_API_KEY", "vworld-provider-key");
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const { GET } = await import("./route");

    const response = await GET(
      new NextRequest("http://127.0.0.1:12705/api/geo/v2/geocode?q=test"),
      { params: Promise.resolve({ path: ["v2", "geocode"] }) },
    );

    expect(response.status).toBe(503);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it.each([
    "   ",
    "x".repeat(31),
    "x".repeat(33),
    `${"x".repeat(31)}-`,
    `${"x".repeat(31)}\n`,
    `${VALID_GEO_API_KEY} `,
  ])(
    "rejects an invalid server-only Geo key before fetch",
    async (apiKey) => {
      vi.stubEnv("KOR_TRAVEL_GEO_API_KEY", apiKey);
      const fetchSpy = vi.spyOn(globalThis, "fetch");
      const { GET } = await import("./route");

      const response = await GET(
        new NextRequest("http://127.0.0.1:12705/api/geo/v2/geocode?q=test"),
        { params: Promise.resolve({ path: ["v2", "geocode"] }) },
      );

      expect(response.status).toBe(503);
      await expect(response.json()).resolves.toMatchObject({
        code: "GEO_API_KEY_NOT_CONFIGURED",
      });
      expect(fetchSpy).not.toHaveBeenCalled();
    },
  );

  it("sends only the server-only Geo key in a header", async () => {
    vi.stubEnv("KOR_TRAVEL_GEO_API_KEY", VALID_GEO_API_KEY);
    vi.stubEnv("NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY", "public-geo-key");
    vi.stubEnv("NEXT_PUBLIC_VWORLD_API_KEY", "vworld-provider-key");
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response("{}", { status: 200 }));
    const { GET } = await import("./route");

    const response = await GET(
      new NextRequest("http://127.0.0.1:12705/api/geo/v2/geocode?q=test"),
      { params: Promise.resolve({ path: ["v2", "geocode"] }) },
    );

    expect(response.status).toBe(200);
    const target = new URL(String(fetchSpy.mock.calls[0]?.[0]));
    expect(target.searchParams.has("key")).toBe(false);
    const init = fetchSpy.mock.calls[0]?.[1];
    const headers = new Headers(init?.headers);
    expect(headers.get("X-KTG-API-Key")).toBe(VALID_GEO_API_KEY);
    expect(headers.get("X-KTG-API-Key")).not.toBe("public-geo-key");
    expect(headers.get("X-KTG-API-Key")).not.toBe("vworld-provider-key");
  });

  it("does not let a browser query override the server-only key", async () => {
    vi.stubEnv("KOR_TRAVEL_GEO_API_KEY", VALID_GEO_API_KEY);
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response("{}", { status: 200 }));
    const { GET } = await import("./route");

    const response = await GET(
      new NextRequest(
        "http://127.0.0.1:12705/api/geo/v2/geocode?q=test&key=browser-key",
      ),
      { params: Promise.resolve({ path: ["v2", "geocode"] }) },
    );

    expect(response.status).toBe(200);
    const target = new URL(String(fetchSpy.mock.calls[0]?.[0]));
    expect(target.searchParams.has("key")).toBe(false);
    const headers = new Headers(fetchSpy.mock.calls[0]?.[1]?.headers);
    expect(headers.get("X-KTG-API-Key")).toBe(VALID_GEO_API_KEY);
  });

  it.each([".", ".."])(
    "rejects traversal segment %s before forwarding the Geo credential",
    async (segment) => {
      vi.stubEnv("KOR_TRAVEL_GEO_API_KEY", VALID_GEO_API_KEY);
      const fetchSpy = vi.spyOn(globalThis, "fetch");
      const { GET } = await import("./route");

      const response = await GET(
        new NextRequest("http://127.0.0.1:12705/api/geo/v2/geocode?q=test"),
        { params: Promise.resolve({ path: ["v2", segment, "admin"] }) },
      );

      expect(response.status).toBe(403);
      expect(fetchSpy).not.toHaveBeenCalled();
    },
  );

  it.each([
    [401, { error: { code: "E0401" } }],
    [400, { error: { code: "E0100", field: "key" } }],
  ])(
    "fails closed when Geo rejects the configured key (%i)",
    async (status, payload) => {
      vi.stubEnv("KOR_TRAVEL_GEO_API_KEY", VALID_GEO_API_KEY);
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        Response.json(payload, { status }),
      );
      const { POST } = await import("./route");

      const response = await POST(
        new NextRequest("http://127.0.0.1:12705/api/geo/v2/reverse", {
          method: "POST",
          body: JSON.stringify({ lon: 127, lat: 37.5 }),
        }),
        { params: Promise.resolve({ path: ["v2", "reverse"] }) },
      );

      expect(response.status).toBe(503);
      await expect(response.json()).resolves.toEqual({
        detail: "kor-travel-geo가 Map UI 공개 API 키를 거부했습니다.",
        code: "GEO_API_KEY_REJECTED",
      });
    },
  );

  it("preserves a non-credential 400 response", async () => {
    vi.stubEnv("KOR_TRAVEL_GEO_API_KEY", VALID_GEO_API_KEY);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      Response.json(
        { error: { code: "E0200", field: "lon" } },
        { status: 400 },
      ),
    );
    const { POST } = await import("./route");

    const response = await POST(
      new NextRequest("http://127.0.0.1:12705/api/geo/v2/reverse", {
        method: "POST",
        body: JSON.stringify({ lon: 999, lat: 37.5 }),
      }),
      { params: Promise.resolve({ path: ["v2", "reverse"] }) },
    );

    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toEqual({
      error: { code: "E0200", field: "lon" },
    });
  });
});

import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe("geo BFF credential boundary", () => {
  it("does not reuse the VWorld provider key when the Geo key is absent", async () => {
    vi.stubEnv("KOR_TRAVEL_GEO_API_KEY", "");
    vi.stubEnv("NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY", "");
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

  it("uses only the dedicated Geo public key", async () => {
    vi.stubEnv("KOR_TRAVEL_GEO_API_KEY", "geo-public-key");
    vi.stubEnv("NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY", "");
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
    expect(target.searchParams.get("key")).toBe("geo-public-key");
    expect(target.searchParams.get("key")).not.toBe("vworld-provider-key");
  });
});

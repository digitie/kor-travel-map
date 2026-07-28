import { NextResponse } from "next/server";

const EXACT_GIT_REVISION = /^[0-9a-f]{40}$/;

export function GET() {
  const revision = process.env.NEXT_PUBLIC_KOR_TRAVEL_MAP_GIT_COMMIT;
  if (!revision || !EXACT_GIT_REVISION.test(revision)) {
    return NextResponse.json(
      { error: "BUILD_REVISION_UNAVAILABLE" },
      {
        status: 503,
        headers: { "cache-control": "no-store" },
      },
    );
  }
  return NextResponse.json(
    { revision },
    { headers: { "cache-control": "no-store" } },
  );
}

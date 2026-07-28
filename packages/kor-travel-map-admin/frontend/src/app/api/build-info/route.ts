import { NextResponse } from "next/server";

import { FRONTEND_SOURCE_DIGEST } from "@/generated/frontend-build-info";

const EXACT_GIT_REVISION = /^[0-9a-f]{40}$/;
const EXACT_SHA256 = /^[0-9a-f]{64}$/;

export function buildInfoResponse(
  revision: string | undefined,
  sourceDigest: string,
) {
  if (
    !revision ||
    !EXACT_GIT_REVISION.test(revision) ||
    !EXACT_SHA256.test(sourceDigest)
  ) {
    return NextResponse.json(
      { error: "BUILD_REVISION_UNAVAILABLE" },
      {
        status: 503,
        headers: { "cache-control": "no-store" },
      },
    );
  }
  return NextResponse.json(
    { revision, source_digest: sourceDigest },
    { headers: { "cache-control": "no-store" } },
  );
}

export function GET() {
  return buildInfoResponse(
    process.env.NEXT_PUBLIC_KOR_TRAVEL_MAP_GIT_COMMIT,
    FRONTEND_SOURCE_DIGEST,
  );
}

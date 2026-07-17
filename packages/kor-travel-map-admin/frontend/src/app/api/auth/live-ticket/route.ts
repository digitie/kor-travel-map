import { NextRequest, NextResponse } from "next/server";

import {
  adminUsernameFromEnv,
  requestHasSameOrigin,
  requestHasValidSession,
} from "@/lib/auth";
import {
  issueOpsLiveTicket,
  opsLiveSigningSecret,
} from "@/lib/ops-live-ticket";

const NO_STORE_HEADERS = {
  "Cache-Control": "no-store, max-age=0",
  Pragma: "no-cache",
} as const;

export const runtime = "nodejs";

export async function POST(request: NextRequest) {
  const origin = request.headers.get("origin");
  const fetchSite = request.headers.get("sec-fetch-site");
  if (
    !origin ||
    fetchSite !== "same-origin" ||
    !requestHasSameOrigin(request)
  ) {
    return NextResponse.json(
      { error: "INVALID_ORIGIN" },
      { status: 403, headers: NO_STORE_HEADERS },
    );
  }
  if (!(await requestHasValidSession(request))) {
    return NextResponse.json(
      { error: "AUTH_REQUIRED" },
      { status: 401, headers: NO_STORE_HEADERS },
    );
  }
  const secret = opsLiveSigningSecret();
  if (secret === null) {
    return NextResponse.json(
      { error: "LIVE_AUTH_MISCONFIGURED" },
      { status: 503, headers: NO_STORE_HEADERS },
    );
  }

  let ticket: ReturnType<typeof issueOpsLiveTicket>;
  try {
    ticket = issueOpsLiveTicket({
      actor: adminUsernameFromEnv(),
      secret,
    });
  } catch {
    return NextResponse.json(
      { error: "LIVE_AUTH_MISCONFIGURED" },
      { status: 503, headers: NO_STORE_HEADERS },
    );
  }
  return NextResponse.json(
    {
      expires_at: new Date(ticket.expiresAt * 1_000).toISOString(),
      subprotocol: ticket.subprotocol,
    },
    { headers: NO_STORE_HEADERS },
  );
}

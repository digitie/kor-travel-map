import { createHmac, randomBytes } from "node:crypto";

import {
  OPS_LIVE_PROTOCOL_PREFIX,
  OPS_LIVE_TICKET_TTL_SECONDS,
} from "./ops-live-contract";

export const OPS_LIVE_SECRET_MIN_LENGTH = 32;

const OPS_LIVE_TICKET_AUDIENCE = "kor-travel-map-admin-ops-live";
const OPS_LIVE_ACTOR_MAX_LENGTH = 80;
const OPS_LIVE_NONCE_MAX_LENGTH = 128;
const BASE64URL_PATTERN = /^[A-Za-z0-9_-]+$/;

type OpsLiveTicketPayload = {
  aud: typeof OPS_LIVE_TICKET_AUDIENCE;
  exp: number;
  iat: number;
  nonce: string;
  sub: string;
  v: 1;
};

export type IssuedOpsLiveTicket = {
  expiresAt: number;
  subprotocol: string;
};

export function opsLiveSigningSecret(
  env: Record<string, string | undefined> = process.env,
): string | null {
  const value = env.KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET?.trim();
  return value && value.length >= OPS_LIVE_SECRET_MIN_LENGTH ? value : null;
}

export function issueOpsLiveTicket({
  actor,
  secret,
  nowSeconds = Math.floor(Date.now() / 1_000),
  nonce = randomBytes(18).toString("base64url"),
}: {
  actor: string;
  secret: string;
  nowSeconds?: number;
  nonce?: string;
}): IssuedOpsLiveTicket {
  const normalizedActor = actor.trim();
  if (!normalizedActor || normalizedActor.length > OPS_LIVE_ACTOR_MAX_LENGTH) {
    throw new Error("ops live actor가 비어 있거나 너무 깁니다.");
  }
  if (
    !nonce ||
    nonce.length > OPS_LIVE_NONCE_MAX_LENGTH ||
    !BASE64URL_PATTERN.test(nonce)
  ) {
    throw new Error("ops live nonce 형식이 올바르지 않습니다.");
  }
  if (secret.length < OPS_LIVE_SECRET_MIN_LENGTH) {
    throw new Error("ops live ticket 서명 secret이 너무 짧습니다.");
  }
  const expiresAt = nowSeconds + OPS_LIVE_TICKET_TTL_SECONDS;
  const payload: OpsLiveTicketPayload = {
    aud: OPS_LIVE_TICKET_AUDIENCE,
    exp: expiresAt,
    iat: nowSeconds,
    nonce,
    sub: normalizedActor,
    v: 1,
  };
  const payloadPart = Buffer.from(JSON.stringify(payload), "utf8").toString(
    "base64url",
  );
  const signaturePart = createHmac("sha256", secret)
    .update(payloadPart, "ascii")
    .digest("base64url");
  return {
    expiresAt,
    subprotocol: `${OPS_LIVE_PROTOCOL_PREFIX}${payloadPart}.${signaturePart}`,
  };
}

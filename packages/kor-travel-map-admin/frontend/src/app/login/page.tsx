import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";

import { LoginForm } from "@/components/login-form";
import {
  SESSION_COOKIE_NAME,
  sanitizeLocalPath,
  verifySessionCookieValueNow,
} from "@/lib/auth";

export default async function LoginPage({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = (await searchParams) ?? {};
  const nextPath = sanitizeLocalPath(
    typeof params.next === "string" ? params.next : undefined,
  );
  const [cookieStore, headerStore] = await Promise.all([cookies(), headers()]);
  const session = cookieStore.get(SESSION_COOKIE_NAME)?.value;
  if (await verifySessionCookieValueNow(session, process.env, headerStore)) {
    redirect(nextPath);
  }
  return <LoginForm nextPath={nextPath} />;
}

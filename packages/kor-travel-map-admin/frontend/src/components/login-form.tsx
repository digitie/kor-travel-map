"use client";

import { useState } from "react";
import { LoginForm as CommonLoginForm, type LoginSubmission } from "@kor-travel/ui/login-form";
import { sanitizeLocalPath } from "@kor-travel/ui/navigation";

import { clearDomainIdempotencyKeys } from "@/api/client";

/** 인증·세션·CSRF는 Map BFF가 소유하고 폼은 공통 컴포넌트를 사용한다. */
export function LoginForm({ nextPath }: { nextPath: string }) {
  const [error, setError] = useState<string | null>(null);

  async function submit({ credentials, nextPath: safeNext }: LoginSubmission) {
    const response = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ ...credentials, next: safeNext }),
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) {
      setError(response.status === 503 ? "로그인 환경변수가 설정되지 않았습니다."
        : response.status === 429 ? "로그인 시도가 너무 많습니다. 잠시 후 다시 시도하세요."
        : response.status === 403 ? "허용되지 않은 요청입니다. 로그인 화면을 새로고침하세요."
        : "아이디 또는 비밀번호가 올바르지 않습니다.");
      return;
    }
    const payload = (await response.json()) as { next?: string };
    clearDomainIdempotencyKeys();
    window.location.assign(sanitizeLocalPath(payload.next ?? safeNext));
  }

  return <main className="map-common-surface flex min-h-dvh flex-col justify-center bg-surface-page text-text-primary">
    <h1 className="sr-only">관리자 로그인</h1>
    <CommonLoginForm brand="kor-travel-map admin" description="내부 전용 관리 콘솔"
      defaultUsername="admin" nextPath={nextPath} onSubmit={submit} error={error}
      onClearError={() => setError(null)} testId="map-common-login"
      footer={<p>kor-travel-map admin · 내부 전용 콘솔</p>} />
  </main>;
}

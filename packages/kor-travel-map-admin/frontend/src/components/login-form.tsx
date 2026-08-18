"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench(login knob) · design-system: design.md · designed-as-app

import { FormEvent, useState } from "react";
import { LogInIcon } from "lucide-react";

import { clearDomainIdempotencyKeys } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/**
 * 로그인 (design.md §Macrostructure · login knob, m5):
 * 단일 가운데 열 · 타이포 워드마크 · 폼 하나 · 카드 프레임/아이콘 타일 없음 · footer 줄 위 hairline.
 * 오류는 CTA 위 예약 슬롯(항상 렌더되는 live region — M13)에 한 줄로.
 */
export function LoginForm({ nextPath }: { nextPath: string }) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    // P1-5: 제출 중에도 CTA는 탭 순서에 남는다(Button loading = aria-disabled). 두 번째 제출은
    // 여기서 조용히 끊는다 — native disabled로 포커스를 뺏지 않기 위한 짝이다.
    if (busy) return;
    const form = event.currentTarget as HTMLFormElement;
    const formData = new FormData(form);
    const submittedUsername = String(formData.get("username") ?? "");
    const submittedPassword = String(formData.get("password") ?? "");
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          username: submittedUsername,
          password: submittedPassword,
          next: nextPath,
        }),
      });
      if (response.status === 503) {
        setError("로그인 환경변수가 설정되지 않았습니다.");
        return;
      }
      if (response.status === 429) {
        setError("로그인 시도가 너무 많습니다. 잠시 후 다시 시도하세요.");
        return;
      }
      if (response.status === 403) {
        setError("허용되지 않은 요청입니다. 로그인 화면을 새로고침하세요.");
        return;
      }
      if (!response.ok) {
        setError("아이디 또는 비밀번호가 올바르지 않습니다.");
        return;
      }
      const payload = (await response.json()) as { next?: string };
      // 같은 browser tab에서 다른 admin principal로 바뀌어도 이전 actor의
      // uncertain command UUID/submission을 재사용하지 않는다.
      clearDomainIdempotencyKeys();
      window.location.assign(payload.next ?? nextPath);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-dvh flex-col bg-surface-page text-text-primary">
      <div className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center px-6 py-12">
        {/* 타이포 워드마크 — 좌측 정렬, h1 위 plain text(m5). */}
        <p className="flex items-baseline gap-1.5 text-sm font-semibold tracking-tight">
          <span>kor-travel-map</span>
          <span className="text-2xs font-medium text-text-tertiary">admin</span>
        </p>
        <h1 className="mt-5 text-xl leading-tight font-bold tracking-tight">
          관리자 로그인
        </h1>
        <form
          className="mt-8 flex flex-col gap-5"
          aria-busy={busy}
          onSubmit={submit}
        >
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium" htmlFor="admin-username">
              아이디
            </label>
            <Input
              aria-describedby={error ? "login-error" : undefined}
              aria-invalid={error ? true : undefined}
              autoComplete="username"
              id="admin-username"
              name="username"
              readOnly={busy}
              value={username}
              onChange={(event) => setUsername(event.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium" htmlFor="admin-password">
              비밀번호
            </label>
            <Input
              aria-describedby={error ? "login-error" : undefined}
              aria-invalid={error ? true : undefined}
              autoComplete="current-password"
              id="admin-password"
              name="password"
              readOnly={busy}
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </div>
          {/* M13: CTA 위 예약 메시지 슬롯 — 항상 렌더(높이 예약), 오류 시 텍스트만 채운다. */}
          <p
            aria-live="assertive"
            className="min-h-[1lh] text-xs text-destructive"
            id="login-error"
            role="alert"
          >
            {error}
          </p>
          {/* loading = Button `loading`(spinner 오버레이 + aria-busy, 라벨 유지) — 조용한 disable 금지(M19). */}
          <Button className="w-full" loading={busy} type="submit">
            <LogInIcon aria-hidden="true" data-icon="inline-start" />
            로그인
          </Button>
        </form>
        {/* footer 줄 — 위 hairline (design.md login knob). */}
        <p className="mt-10 border-t border-border pt-4 text-2xs text-text-tertiary">
          kor-travel-map admin · 내부 전용 콘솔
        </p>
      </div>
    </main>
  );
}

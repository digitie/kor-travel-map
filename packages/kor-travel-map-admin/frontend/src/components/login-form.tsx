"use client";

import { FormEvent, useState } from "react";
import { LockKeyholeIcon, LogInIcon } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function LoginForm({ nextPath }: { nextPath: string }) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ username, password, next: nextPath }),
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
      window.location.assign(payload.next ?? nextPath);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-surface-page px-4 py-10 text-text-primary">
      <section className="w-full max-w-sm rounded-lg border border-surface-muted bg-card p-6 shadow-[var(--shadow-card)]">
        <div className="mb-6 flex items-center gap-3">
          <span className="flex size-10 items-center justify-center rounded-lg bg-brand-tint text-brand">
            <LockKeyholeIcon className="size-5" />
          </span>
          <div>
            <p className="text-[12px] font-medium text-text-secondary">kor-travel-map</p>
            <h1 className="text-[20px] font-bold">관리자 로그인</h1>
          </div>
        </div>
        <form className="space-y-4" aria-busy={busy} onSubmit={submit}>
          <div className="space-y-1.5">
            <label className="text-[13px] font-medium" htmlFor="admin-username">
              아이디
            </label>
            <Input
              aria-describedby={error ? "login-error" : undefined}
              aria-invalid={error ? true : undefined}
              autoComplete="username"
              disabled={busy}
              id="admin-username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-[13px] font-medium" htmlFor="admin-password">
              비밀번호
            </label>
            <Input
              aria-describedby={error ? "login-error" : undefined}
              aria-invalid={error ? true : undefined}
              autoComplete="current-password"
              disabled={busy}
              id="admin-password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </div>
          <Button className="w-full" disabled={busy} type="submit">
            <LogInIcon data-icon="inline-start" />
            로그인
          </Button>
          {error ? (
            <Alert variant="destructive">
              <AlertTitle>로그인 실패</AlertTitle>
              <AlertDescription id="login-error">{error}</AlertDescription>
            </Alert>
          ) : null}
        </form>
      </section>
    </main>
  );
}

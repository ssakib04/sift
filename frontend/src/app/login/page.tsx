"use client";

import { FormEvent, Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { buttonClass } from "@/components/ui/button";
import { fieldClass } from "@/components/ui/field";
import { GuestFrame } from "@/components/ui/guest-frame";
import { PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
import { apiRequest, rememberRecruiter } from "@/lib/api";

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}

function LoginForm() {
  const router = useRouter();
  const search = useSearchParams();
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      const result = await apiRequest<{ token: string }>("/api/v1/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      rememberRecruiter(result.token);
      const next = search.get("next") || "/jobs";
      router.replace(next.startsWith("/") && !next.startsWith("//") ? next : "/jobs");
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : "Sign-in failed.");
      setBusy(false);
    }
  }

  return (
    <GuestFrame>
      <form onSubmit={(event) => void onSubmit(event)} className="w-full">
        <Panel>
          <div className="space-y-4 p-6">
            <PageHeader eyebrow="Sift" title="Recruiter sign-in" />
            <label className="block space-y-2 text-sm text-mist">
              <span>Password</span>
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password"
                className={fieldClass}
              />
            </label>
            {message ? <p className="text-sm text-mist">{message}</p> : null}
            <button type="submit" disabled={busy || password.length === 0} className={buttonClass()}>
              Sign in
            </button>
          </div>
        </Panel>
      </form>
    </GuestFrame>
  );
}

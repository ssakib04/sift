"use client";

import { FormEvent, Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

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
    <main className="flex min-h-screen items-center justify-center bg-slate-950 px-6 text-slate-100">
      <form onSubmit={(event) => void onSubmit(event)} className="w-full max-w-sm space-y-4">
        <p className="text-sm uppercase tracking-[0.2em] text-slate-400">Sift</p>
        <h1 className="text-3xl font-semibold">Recruiter sign-in</h1>
        <label className="block space-y-2 text-sm">
          <span className="text-slate-300">Password</span>
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
            className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100"
          />
        </label>
        {message ? <p className="text-sm text-slate-300">{message}</p> : null}
        <button
          type="submit"
          disabled={busy || password.length === 0}
          className="rounded-lg bg-white px-4 py-2 text-sm font-medium text-slate-950 disabled:opacity-60"
        >
          Sign in
        </button>
      </form>
    </main>
  );
}

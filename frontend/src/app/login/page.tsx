"use client";

import { FormEvent, Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { Atmosphere, RoomSwitch } from "@/components/ui/atmosphere";
import { apiRequest, rememberRecruiter } from "@/lib/api";

import "./auth-stage.css";

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
  const [visible, setVisible] = useState(false);
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
      const next = search.get("next") || "/";
      router.replace(next.startsWith("/") && !next.startsWith("//") ? next : "/");
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : "Sign-in failed.");
      setBusy(false);
    }
  }

  return (
    <div className="relative min-h-dvh text-ivory">
      <Atmosphere showSwitcher={false} lifted>
      <main className="auth-main">
        <section className="auth-panel" aria-label="Recruiter sign-in">
          <div className="auth-art">
            <img
              src="/brand/sift-golden-hour.jpg"
              alt="Sift. You set the bar. Sift finds the fit. Less manual screening. Smarter matching. More time for the people who matter. Intelligent hiring starts here."
              width={1024}
              height={576}
              fetchPriority="high"
              draggable={false}
              className="auth-artwork"
            />
            <div aria-hidden className="auth-art-fade" />
          </div>
          <form onSubmit={(event) => void onSubmit(event)} className="auth-form" aria-busy={busy}>
            <RoomSwitch className="auth-room-switch" />
            <div className="auth-form-inner">
              <p className="auth-kicker">Recruiter</p>
              <h1>Sign in</h1>
              <p className="auth-lede">Enter your password to continue.</p>
              <div className="auth-fields">
                <div className="auth-label">
                  <label htmlFor="recruiter-password">Password</label>
                  <span className="auth-field">
                    <input
                      id="recruiter-password"
                      name="password"
                      type={visible ? "text" : "password"}
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                      autoComplete="current-password"
                      autoFocus
                      placeholder="Enter password"
                      aria-invalid={message ? true : undefined}
                      aria-describedby={message ? "recruiter-sign-in-error" : undefined}
                      className="auth-input"
                    />
                    <button
                      type="button"
                      className="auth-reveal"
                      aria-label={visible ? "Hide password" : "Show password"}
                      aria-pressed={visible}
                      onClick={() => setVisible((current) => !current)}
                    >
                      {visible ? <EyeOffIcon /> : <EyeIcon />}
                    </button>
                  </span>
                </div>
                {message ? (
                  <p id="recruiter-sign-in-error" role="alert" className="auth-error">
                    {message}
                  </p>
                ) : null}
                <button type="submit" disabled={busy || password.length === 0} className="auth-submit">
                  {busy ? "Signing in…" : "Sign in"}
                </button>
              </div>
            </div>
          </form>
        </section>
      </main>
      </Atmosphere>
    </div>
  );
}

function EyeIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M2.5 12s3.5-6.5 9.5-6.5S21.5 12 21.5 12s-3.5 6.5-9.5 6.5S2.5 12 2.5 12Z"
        stroke="currentColor"
        strokeWidth="1.6"
      />
      <circle cx="12" cy="12" r="2.6" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  );
}

function EyeOffIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M4 5.5 19 19" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <path
        d="M9.2 6.4A10.8 10.8 0 0 1 12 6c6 0 9.5 6 9.5 6a17 17 0 0 1-3.1 3.7"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
      <path
        d="M6.1 8.2C3.9 9.8 2.5 12 2.5 12S6 18.5 12 18.5c1.1 0 2.1-.2 3-.6"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  );
}

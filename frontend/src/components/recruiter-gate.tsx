"use client";

import { ReactNode, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

import { apiRequest, recruiterToken } from "@/lib/api";

function isGuestPath(pathname: string): boolean {
  return pathname.startsWith("/login") || pathname.startsWith("/invite") || pathname.startsWith("/interview");
}

export function RecruiterGate({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const guest = isGuestPath(pathname);
  const [ready, setReady] = useState(guest);

  useEffect(() => {
    if (isGuestPath(pathname)) {
      setReady(true);
      return;
    }
    if (!recruiterToken()) {
      setReady(false);
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
      return;
    }
    setReady(true);
    let cancelled = false;
    apiRequest("/api/v1/auth/me")
      .catch(() => {
        if (!cancelled) {
          setReady(false);
          router.replace(`/login?next=${encodeURIComponent(pathname)}`);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [pathname, router]);

  if (!ready) {
    return null;
  }
  return <>{children}</>;
}

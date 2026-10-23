"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { ApplicantNotice, ApplicantNoticeList, apiRequest, recruiterToken } from "@/lib/api";

export function ApplicantNotices() {
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [open, setOpen] = useState(false);
  const [notices, setNotices] = useState<ApplicantNotice[]>([]);
  const [unread, setUnread] = useState(0);

  useEffect(() => {
    setReady(Boolean(recruiterToken()));
  }, []);

  useEffect(() => {
    if (!ready) {
      return;
    }
    let cancelled = false;
    function load() {
      apiRequest<ApplicantNoticeList>("/api/v1/notifications")
        .then((payload) => {
          if (cancelled) {
            return;
          }
          setNotices(payload.notices);
          setUnread(payload.unread_count);
        })
        .catch(() => {
          if (!cancelled) {
            setNotices([]);
          }
        });
    }
    load();
    const timer = window.setInterval(load, 20000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [ready]);

  async function openNotice(notice: ApplicantNotice) {
    try {
      await apiRequest(`/api/v1/notifications/${notice.id}/read`, { method: "POST" });
      setNotices((current) => current.map((item) => (item.id === notice.id ? { ...item, read: true } : item)));
      setUnread((count) => Math.max(0, count - (notice.read ? 0 : 1)));
    } catch {
      // The profile is still the right place to go.
    }
    setOpen(false);
    if (notice.job_id) {
      router.push(`/jobs?job=${notice.job_id}&tab=people#people`);
      return;
    }
    if (notice.candidate_id) {
      router.push(`/candidates/${notice.candidate_id}`);
    }
  }

  if (!ready) {
    return null;
  }

  const label = unread > 0 ? `Notifications, ${unread} unread` : "Notifications";

  return (
    <div className="fixed right-4 top-4 z-50 lg:right-6 lg:top-6">
      <button
        type="button"
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label={label}
        onClick={() => setOpen((value) => !value)}
        className="relative flex h-11 w-11 items-center justify-center rounded-full border border-ivory/15 bg-night/80 text-ivory shadow-lift hover:border-amber/60 hover:text-amber"
      >
        <BellIcon />
        {unread > 0 ? (
          <span className="absolute -right-1 -top-1 flex h-5 min-w-5 items-center justify-center rounded-full bg-amber px-1 text-[11px] font-semibold leading-none text-night">
            {unread > 9 ? "9+" : unread}
          </span>
        ) : null}
      </button>
      {open ? (
        <div
          role="dialog"
          aria-label="New applicants"
          className="absolute right-0 z-50 mt-2 w-80 max-w-[calc(100vw-2rem)] overflow-hidden rounded-card border border-white/15 bg-[linear-gradient(180deg,rgb(44_22_28/0.55),rgb(16_10_12/0.66))] p-3 shadow-[inset_0_1px_0_rgb(255_220_214/0.26),0_12px_28px_rgb(20_10_16/0.18)] backdrop-blur-xl"
        >
          <p className="px-1 pb-2 text-xs font-semibold uppercase tracking-[0.16em] text-mist">New applicants</p>
          {notices.length === 0 ? <p className="px-1 py-2 text-sm text-mist">No applicants have registered yet.</p> : null}
          <ul className="max-h-80 space-y-1 overflow-y-auto">
            {notices.map((notice) => (
              <li key={notice.id}>
                <button
                  type="button"
                  onClick={() => void openNotice(notice)}
                  className="w-full rounded-control px-2 py-2 text-left hover:bg-ivory/5"
                >
                  <p className={`text-sm ${notice.read ? "text-mist" : "text-ivory"}`}>{notice.message}</p>
                  <p className="mt-1 text-xs text-mist">{new Date(notice.created_at).toLocaleString()}</p>
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function BellIcon() {
  return (
    <svg aria-hidden viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M6 9.5a6 6 0 0 1 12 0c0 4.2 1.2 5.8 1.8 6.5H4.2C4.8 15.3 6 13.7 6 9.5Z"
      />
      <path strokeLinecap="round" d="M10 18.5a2 2 0 0 0 4 0" />
    </svg>
  );
}

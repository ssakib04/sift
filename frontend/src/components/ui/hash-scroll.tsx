"use client";

import { usePathname, useSearchParams } from "next/navigation";
import { useEffect } from "react";

export function HashScroll() {
  const pathname = usePathname();
  const search = useSearchParams();

  useEffect(() => {
    const id = window.location.hash.replace(/^#/, "");
    if (!id) {
      return;
    }
    let attempts = 0;
    const timer = window.setInterval(() => {
      const node = document.getElementById(id);
      attempts += 1;
      if (node) {
        node.scrollIntoView({ behavior: "smooth", block: "start" });
        window.clearInterval(timer);
      } else if (attempts > 20) {
        window.clearInterval(timer);
      }
    }, 150);
    return () => window.clearInterval(timer);
  }, [pathname, search]);

  return null;
}

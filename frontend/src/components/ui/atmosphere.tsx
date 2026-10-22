"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";

import { recruiterToken } from "@/lib/api";

type Room = {
  id: string;
  label: string;
  floor: string;
  light: string;
  mid: string;
  deep: string;
  shade: string;
  glow: string;
  pool: string;
  poolSoft: string;
  veil: string;
  veilMid: string;
};

const ROOMS: readonly Room[] = [
  {
    id: "rose",
    label: "Rose",
    floor: "#1c1618",
    light: "#d4a8b4",
    mid: "#8d5d6c",
    deep: "#4a3038",
    shade: "#2a1e24",
    glow: "#e4c4cc",
    pool: "#7d8c86",
    poolSoft: "#8e9a90",
    veil: "rgb(18 12 16 / 0.5)",
    veilMid: "rgb(28 18 22 / 0.16)",
  },
  {
    id: "moon",
    label: "Moon",
    floor: "#16181c",
    light: "#c5d0dc",
    mid: "#5d6e80",
    deep: "#303844",
    shade: "#1e242c",
    glow: "#d5dee8",
    pool: "#7d8c96",
    poolSoft: "#8e9aa4",
    veil: "rgb(14 16 20 / 0.5)",
    veilMid: "rgb(22 26 32 / 0.16)",
  },
  {
    id: "wine",
    label: "Wine",
    floor: "#1a1214",
    light: "#d4a0a8",
    mid: "#8a4554",
    deep: "#4a2832",
    shade: "#2a1a20",
    glow: "#e4c0c6",
    pool: "#7a6878",
    poolSoft: "#8a7a86",
    veil: "rgb(18 10 12 / 0.5)",
    veilMid: "rgb(32 18 22 / 0.16)",
  },
  {
    id: "moss",
    label: "Moss",
    floor: "#141816",
    light: "#b7c6b4",
    mid: "#5a6e5c",
    deep: "#2c3830",
    shade: "#1c2420",
    glow: "#d4e0d0",
    pool: "#8a7d68",
    poolSoft: "#9a8e78",
    veil: "rgb(12 16 14 / 0.5)",
    veilMid: "rgb(22 28 24 / 0.16)",
  },
];

const STORAGE_KEY = "sift-room";

function roomById(id: string): Room {
  return ROOMS.find((room) => room.id === id) ?? ROOMS[0];
}

export function Atmosphere() {
  const path = usePathname();
  const [roomId, setRoomId] = useState(ROOMS[0].id);
  const [besideBell, setBesideBell] = useState(true);
  const room = roomById(roomId);

  useEffect(() => {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved && ROOMS.some((item) => item.id === saved)) {
      setRoomId(saved);
    }
    setBesideBell(Boolean(recruiterToken()));
  }, []);

  useEffect(() => {
    document.body.style.background = room.floor;
  }, [room.floor]);

  function choose(id: string) {
    setRoomId(id);
    window.localStorage.setItem(STORAGE_KEY, id);
  }

  return (
    <>
      <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden" style={{ background: room.floor }}>
        <div
          className="absolute inset-0"
          style={{
            backgroundImage: `radial-gradient(ellipse at 100% -8%, ${room.light} 0%, ${room.mid} 10%, ${room.deep} 32%, ${room.shade} 60%, ${room.floor} 100%)`,
          }}
        />
        <div className="absolute -right-20 -top-32 h-[24rem] w-[32rem] rounded-full blur-[110px]" style={{ backgroundColor: room.light, opacity: 0.36 }} />
        <div className="absolute right-[6%] top-[8%] h-[12rem] w-[18rem] rounded-full blur-[90px]" style={{ backgroundColor: room.glow, opacity: 0.18 }} />
        <div className="absolute right-[4%] top-[42%] h-[18rem] w-[28rem] rounded-full blur-[110px]" style={{ backgroundColor: room.pool, opacity: 0.32 }} />
        <div className="absolute bottom-[-6rem] left-[12%] h-[24rem] w-[42rem] rounded-full blur-[120px]" style={{ backgroundColor: room.poolSoft, opacity: 0.3 }} />
        <div className="absolute bottom-[8%] left-[34%] h-[14rem] w-[26rem] rounded-full blur-[90px]" style={{ backgroundColor: room.pool, opacity: 0.22 }} />
        <div
          className="absolute inset-0"
          style={{ backgroundImage: `linear-gradient(100deg, ${room.veil} 0%, ${room.veilMid} 34%, transparent 62%)` }}
        />
        <div className="atmosphere-grain absolute inset-0" />
      </div>
      <div
        className={`fixed z-40 flex items-center gap-1 rounded-full border border-white/15 bg-[#120e10]/70 p-1 shadow-[0_12px_30px_rgb(8_4_6/0.35)] backdrop-blur-md ${
          path.startsWith("/interview")
            ? "bottom-6 left-1/2 -translate-x-1/2"
            : besideBell
              ? "right-[4.25rem] top-4 lg:right-[4.75rem] lg:top-6"
              : "right-4 top-4 lg:right-6 lg:top-6"
        }`}
      >
        {ROOMS.map((item) => {
          const selected = item.id === room.id;
          return (
            <button
              key={item.id}
              type="button"
              aria-pressed={selected}
              onClick={() => choose(item.id)}
              className={`flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-semibold ${
                selected ? "bg-ivory/15 text-ivory" : "text-mist hover:bg-ivory/10 hover:text-ivory"
              }`}
            >
              <span aria-hidden className="h-2 w-2 rounded-full" style={{ backgroundColor: item.light }} />
              {item.label}
            </button>
          );
        })}
      </div>
    </>
  );
}

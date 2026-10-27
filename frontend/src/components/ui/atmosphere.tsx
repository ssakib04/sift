"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

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
  dot: string;
  accent: string;
  ink: string;
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
    dot: "rgba(255, 235, 240, 0.16)",
    accent: "#d4a3b0",
    ink: "#241014",
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
    dot: "rgba(225, 235, 255, 0.14)",
    accent: "#d5dee8",
    ink: "#14181c",
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
    dot: "rgba(255, 235, 240, 0.16)",
    accent: "#d4a0a8",
    ink: "#1a1012",
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
    dot: "rgba(230, 255, 240, 0.14)",
    accent: "#c5d4c0",
    ink: "#121614",
  },
];

const STORAGE_KEY = "sift-room";

function roomById(id: string): Room {
  return ROOMS.find((room) => room.id === id) ?? ROOMS[0];
}

function mixHex(from: string, toward: string, amount: number): string {
  const parse = (hex: string) => [0, 1, 2].map((index) => Number.parseInt(hex.slice(1 + index * 2, 3 + index * 2), 16));
  const [fromRed, fromGreen, fromBlue] = parse(from);
  const [towardRed, towardGreen, towardBlue] = parse(toward);
  const mix = (start: number, end: number) => Math.round(start + (end - start) * amount).toString(16).padStart(2, "0");
  return `#${mix(fromRed, towardRed)}${mix(fromGreen, towardGreen)}${mix(fromBlue, towardBlue)}`;
}

type RoomControls = {
  room: Room;
  choose: (id: string) => void;
};

const RoomContext = createContext<RoomControls | null>(null);

export function RoomSwitch({ className = "" }: { className?: string }) {
  const controls = useContext(RoomContext);
  if (!controls) {
    return null;
  }
  const { room, choose } = controls;
  return (
    <div
      className={`room-switch flex items-center gap-1 rounded-full border border-white/15 bg-[#120e10]/70 p-1 shadow-[0_12px_30px_rgb(8_4_6/0.35)] backdrop-blur-md ${className}`}
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
  );
}

export function Atmosphere({
  children,
  showSwitcher = true,
  lifted = false,
}: {
  children?: ReactNode;
  showSwitcher?: boolean;
  lifted?: boolean;
}) {
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
    const root = document.documentElement;
    root.style.setProperty("--room-floor", room.floor);
    root.style.setProperty("--room-light", room.light);
    root.style.setProperty("--room-mid", room.mid);
    root.style.setProperty("--room-deep", room.deep);
    root.style.setProperty("--room-shade", room.shade);
    root.style.setProperty("--room-glow", room.glow);
    root.style.setProperty("--room-accent", room.accent);
    root.style.setProperty("--room-ink", room.ink);
    const backdrop = lifted ? mixHex(room.floor, room.light, 0.2) : room.floor;
    document.body.style.background = backdrop;
    document.body.style.setProperty("--dot-color", room.dot);
  }, [lifted, room]);

  function choose(id: string) {
    setRoomId(id);
    window.localStorage.setItem(STORAGE_KEY, id);
  }

  const backdrop = lifted ? mixHex(room.floor, room.light, 0.2) : room.floor;
  return (
    <RoomContext.Provider value={{ room, choose }}>
      <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden" style={{ background: backdrop }}>
        <div
          className="absolute inset-0"
          style={{
            backgroundImage: `radial-gradient(ellipse at 100% -8%, ${room.light} 0%, ${room.mid} 10%, ${room.deep} 32%, ${room.shade} 60%, ${backdrop} 100%)`,
          }}
        />
        <div className="absolute -right-20 -top-32 h-[24rem] w-[32rem] rounded-full blur-[110px]" style={{ backgroundColor: room.light, opacity: lifted ? 0.48 : 0.36 }} />
        <div className="absolute right-[6%] top-[8%] h-[12rem] w-[18rem] rounded-full blur-[90px]" style={{ backgroundColor: room.glow, opacity: lifted ? 0.26 : 0.18 }} />
        <div className="absolute right-[4%] top-[42%] h-[18rem] w-[28rem] rounded-full blur-[110px]" style={{ backgroundColor: room.pool, opacity: lifted ? 0.4 : 0.32 }} />
        <div className="absolute bottom-[-6rem] left-[12%] h-[24rem] w-[42rem] rounded-full blur-[120px]" style={{ backgroundColor: room.poolSoft, opacity: lifted ? 0.38 : 0.3 }} />
        <div className="absolute bottom-[8%] left-[34%] h-[14rem] w-[26rem] rounded-full blur-[90px]" style={{ backgroundColor: room.pool, opacity: lifted ? 0.28 : 0.22 }} />
        <div
          className="absolute inset-0"
          style={{ backgroundImage: `linear-gradient(100deg, ${room.veil} 0%, ${room.veilMid} 34%, transparent 62%)` }}
        />
        <div className="atmosphere-grain absolute inset-0" />
      </div>
      {showSwitcher ? (
        <RoomSwitch
          className={`fixed z-40 ${
            besideBell ? "right-[4.25rem] top-4 lg:right-[4.75rem] lg:top-6" : "right-4 top-4 lg:right-6 lg:top-6"
          }`}
        />
      ) : null}
      {children}
    </RoomContext.Provider>
  );
}

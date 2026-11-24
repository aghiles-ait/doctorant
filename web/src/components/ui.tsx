import type { ReactNode } from "react";

export type Tone = "" | "cur" | "ok" | "gate" | "bad";

export function Badge({ children, tone = "" }: { children: ReactNode; tone?: Tone }) {
  return <span className={`badge ${tone}`}>{children}</span>;
}

export function Figures({ items }: { items: [ReactNode, string][] }) {
  return (
    <div className="kv">
      {items.map(([value, name]) => (
        <div key={name}><b>{value}</b><span>{name}</span></div>
      ))}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>;
}

export const verdictTone = (v?: string | null): Tone => (v === "ACCEPTABLE" || v === "approve" ? "ok" : v ? "bad" : "");

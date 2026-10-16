import type { Track } from "@/lib/api";

const TRACK: Record<Track, { name: string; cls: string }> = {
  "01": { name: "01 Act", cls: "bg-red-100 text-red-800 border-red-300" },
  "02": { name: "02 Remember", cls: "bg-blue-100 text-blue-800 border-blue-300" },
  "03": { name: "03 Company Brain", cls: "bg-green-100 text-green-800 border-green-300" },
};

export function TrackBadges({ tracks }: { tracks: Track[] }) {
  return (
    <span className="inline-flex gap-1">
      {[...new Set(tracks)].sort().map((t) => (
        <span key={t} className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold ${TRACK[t]?.cls ?? ""}`}>
          {TRACK[t]?.name ?? t}
        </span>
      ))}
    </span>
  );
}

export function SourceChips({ sources, onOpen }: { sources: string[]; onOpen: (id: string) => void }) {
  if (!sources.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-1">
      <span className="text-[11px] text-gray-500">Sources:</span>
      {sources.map((s) => (
        <button key={s} onClick={() => onOpen(s)}
                className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-[11px] text-gray-700 hover:bg-gray-200">
          {s}
        </button>
      ))}
    </div>
  );
}

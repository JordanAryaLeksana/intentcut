import type { HighlightCandidate } from "@/lib/api/highlights";

export function formatTimestamp(totalSeconds: number): string {
  if (!Number.isFinite(totalSeconds) || totalSeconds < 0) return "--:--:--";
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = Math.floor(totalSeconds % 60);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`;
}

export function markerPercent(
  start: number,
  end: number,
  duration: number,
): { left: string; width: string } {
  if (!Number.isFinite(duration) || duration <= 0) {
    return { left: "0%", width: "0%" };
  }
  const clamp = (n: number) => Math.min(100, Math.max(0, n));
  return {
    left: `${clamp((start / duration) * 100).toFixed(3)}%`,
    width: `${clamp(((end - start) / duration) * 100).toFixed(3)}%`,
  };
}

export function matchStoryboardCut(
  candidate: HighlightCandidate,
  cuts: {
    start_seconds: number;
    end_seconds: number;
    editorial_reason?: string;
    playback_order?: number;
  }[],
): { editorial_reason?: string; playback_order?: number } | null {
  const hit = cuts.find(
    (cut) =>
      Math.abs(cut.start_seconds - candidate.start_seconds) < 1e-6 &&
      Math.abs(cut.end_seconds - candidate.end_seconds) < 1e-6,
  );
  return hit ?? null;
}

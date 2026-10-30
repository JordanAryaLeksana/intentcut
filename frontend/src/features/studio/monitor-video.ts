import type { AIArtifact } from "@/lib/api/contracts";

/** Resolve only the exact selected immutable video, never another rendition. */
export function monitorVideo(items: readonly AIArtifact[], selectedArtifactId?: string): AIArtifact | undefined {
  return items.find(item => (item.kind === "video" || item.kind === "rendition") &&
    (selectedArtifactId === undefined || item.id === selectedArtifactId));
}

/** Keep a frame reference attached to the monitor when the rendered version changes. */
export function visualReference(source: string, currentVideo?: string): string {
  return source === "current-video" ? currentVideo ?? "" : source;
}

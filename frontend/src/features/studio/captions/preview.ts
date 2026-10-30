import type { CaptionDraft } from "./store";

export function previewCues(draft?: CaptionDraft) {
  return draft?.edits.filter(c=>c.enabled && c.text.trim()).map(c=>({
    start: draft.saved.cues[c.index].start_ms/1000,
    end: draft.saved.cues[c.index].end_ms/1000,
    text: c.text.replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;"),
  })) ?? [];
}

/** Pure tour sequencing and placement; DOM work stays in studio-tour. */

export const TAKE_TOUR_EVENT = "intentcut:take-tour";

export interface TourStep {
  id: string;
  target: string;
  title: string;
  body: string;
}

export const TOUR_STEPS: TourStep[] = [
  {
    id: "media",
    target: "media",
    title: "Media Library — Upload your footage",
    body: "Add the videos you already have. Nothing is changed yet — you choose what to use.",
  },
  {
    id: "director",
    target: "director",
    title: "AI Director — Describe the story you want to create",
    body: "Tell the AI Director the story you have in mind, pick your footage, and create your first cut.",
  },
  {
    id: "timeline",
    target: "timeline",
    title: "Timeline — Review and refine your edit",
    body: "See your story in order. Reorder or remove moments, then save your draft when it feels right.",
  },
  {
    id: "export",
    target: "export",
    title: "Export — Render and download your finished video",
    body: "When you are happy with your draft, render it here and download the finished video.",
  },
];

export function stepIndexAfter(current: number, direction: 1 | -1): number {
  return Math.min(TOUR_STEPS.length - 1, Math.max(0, current + direction));
}

export function isLastStep(index: number): boolean {
  return index === TOUR_STEPS.length - 1;
}

export type TourPlacement = "center" | "below" | "above";

/** Missing, hidden, off-screen, or cramped targets use a centered card. */
export function placementFor(
  rect: { top: number; bottom: number; width: number; height: number } | null,
  viewport: { width: number; height: number },
): TourPlacement {
  if (!rect || rect.width === 0 || rect.height === 0) return "center";
  if (viewport.width < 640) return "center";
  if (rect.bottom <= 0 || rect.top >= viewport.height) return "center";
  if (rect.bottom + 220 <= viewport.height) return "below";
  if (rect.top - 220 >= 0) return "above";
  return "center";
}

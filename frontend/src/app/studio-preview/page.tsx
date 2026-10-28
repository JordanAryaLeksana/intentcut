import type { Metadata } from "next";
import { StudioShell } from "@/features/studio/studio-shell";

export const metadata: Metadata = {
  title: "Studio Preview — IntentCut",
  description: "A presentational preview of the IntentCut creative workspace.",
};

export default function StudioPreviewPage() {
  return <StudioShell />;
}

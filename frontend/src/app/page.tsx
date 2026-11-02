import type { Metadata } from "next";
import { LandingPage } from "@/features/landing/landing-page";

export const metadata: Metadata = {
  title: "IntentCut — Your AI Storytelling Director",
  description: "Turn raw footage into a story worth telling. Explore AI-assisted storyboarding, first-cut generation, editable captions, and real MP4 rendering with IntentCut.",
};

export default function Home() {
  return <LandingPage />;
}

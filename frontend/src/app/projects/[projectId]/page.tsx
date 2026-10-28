import { Suspense } from "react";
import { notFound } from "next/navigation";
import { StudioShell } from "@/features/studio/studio-shell";
import { isProjectId } from "@/lib/api/client";
async function ProjectWorkspace({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  if (!isProjectId(projectId)) notFound();
  return <StudioShell projectId={projectId} />;
}

export default function ProjectPage({ params }: { params: Promise<{ projectId: string }> }) { return <Suspense fallback={<p role="status" className="p-8">Opening project…</p>}><ProjectWorkspace params={params} /></Suspense>; }

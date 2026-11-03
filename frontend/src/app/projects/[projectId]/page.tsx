import { Suspense } from "react";
import { notFound, redirect } from "next/navigation";
import { StudioShell } from "@/features/studio/studio-shell";
import { canonicalId, isProjectId } from "@/lib/api/transport";

function isRedirect(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "digest" in error &&
    String((error as { digest: unknown }).digest).startsWith("NEXT_REDIRECT")
  );
}

async function ProjectWorkspace({
  params,
}: {
  params: Promise<{ projectId: string }>;
}) {
  const { projectId } = await params;
  if (!isProjectId(projectId)) notFound();
  const id = canonicalId(projectId);
  // Legacy UUID links move once to the readable canonical URL. If the
  // API cannot be reached, still open the project instead of blocking it.
  let slug: string | null = null;
  try {
    const base = process.env.NEXT_PUBLIC_API_BASE_URL;
    if (base) {
      const response = await fetch(`${base.replace(/\/$/, "")}/projects/${id}`, {
        cache: "no-store",
      });
      if (response.ok) {
        const value: unknown = await response.json();
        if (
          typeof value === "object" &&
          value !== null &&
          "slug" in value &&
          typeof (value as { slug: unknown }).slug === "string"
        ) {
          slug = (value as { slug: string }).slug;
        }
      }
    }
  } catch (error) {
    if (isRedirect(error)) throw error;
    slug = null;
  }
  if (slug) redirect(`/studio/${slug}`);
  return <StudioShell projectId={id} />;
}

export default function ProjectPage({
  params,
}: {
  params: Promise<{ projectId: string }>;
}) {
  return (
    <Suspense
      fallback={
        <p role="status" className="p-8">
          Opening project…
        </p>
      }
    >
      <ProjectWorkspace params={params} />
    </Suspense>
  );
}

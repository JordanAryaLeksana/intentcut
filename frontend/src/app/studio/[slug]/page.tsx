import { Suspense } from "react";
import { redirect } from "next/navigation";
import { StudioBySlug } from "@/features/projects/studio-by-slug";
import { legacyRedirectForStudioSlug } from "@/lib/api/projects";

async function SlugWorkspace({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const legacy = legacyRedirectForStudioSlug(slug);
  if (legacy) redirect(legacy);
  return <StudioBySlug slug={slug} />;
}

export default function StudioSlugPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  return (
    <Suspense
      fallback={
        <p role="status" className="p-8">
          Opening your project…
        </p>
      }
    >
      <SlugWorkspace params={params} />
    </Suspense>
  );
}

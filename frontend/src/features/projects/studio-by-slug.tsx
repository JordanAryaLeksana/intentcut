"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { StudioShell } from "@/features/studio/studio-shell";
import { getProjectBySlug, isProjectSlug } from "@/lib/api/projects";
import { ApiError } from "@/lib/api/transport";

export function StudioBySlug({ slug }: { slug: string }) {
  const valid = isProjectSlug(slug);
  const project = useQuery({
    queryKey: ["projects", "by-slug", slug] as const,
    queryFn: ({ signal }) => getProjectBySlug(slug, signal),
    enabled: valid,
    retry: false,
    staleTime: 30_000,
  });

  if (!valid || (project.isError && project.error instanceof ApiError && (project.error.status === 404 || project.error.code === "invalid_slug"))) {
    return (
      <main className="p-8">
        <h1>We couldn’t find that project</h1>
        <p>It may have been removed, or the link may be incomplete.</p>
        <p>
          <Link href="/studio">See all your projects</Link>
          {" · "}
          <Link href="/studio">Start a new project</Link>
        </p>
      </main>
    );
  }
  if (project.isPending) {
    return (
      <p role="status" className="p-8">
        Opening your project…
      </p>
    );
  }
  if (project.isError) {
    return (
      <main className="p-8">
        <h1>Your project is saved, but we couldn’t open it just now</h1>
        <p>Check your connection, then try again. Nothing was changed.</p>
        <button type="button" onClick={() => void project.refetch()}>
          Try again
        </button>{" "}
        <Link href="/studio">See all your projects</Link>
      </main>
    );
  }
  // Internal Studio work keeps using the canonical UUID unchanged.
  return <StudioShell projectId={project.data.id} />;
}

"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { listProjects, projectStudioPath } from "@/lib/api/projects";

export function ProjectLibrary() {
  const projects = useQuery({
    queryKey: ["projects", "library"] as const,
    queryFn: ({ signal }) => listProjects(signal),
    retry: false,
    staleTime: 10_000,
  });

  return (
    <section aria-labelledby="library-heading">
      <h2 id="library-heading">Your projects</h2>
      {projects.isPending && <p role="status">Loading your projects…</p>}
      {projects.isError && (
        <div>
          <p role="alert">
            We couldn’t load your projects just now. Your work is saved —
            try again in a moment.
          </p>
          <button type="button" onClick={() => void projects.refetch()}>
            Try again
          </button>
        </div>
      )}
      {projects.isSuccess && projects.data.length === 0 && (
        <p>No projects yet. Name your first story above to get started.</p>
      )}
      {projects.isSuccess && projects.data.length > 0 && (
        <ul>
          {projects.data.map((project) => (
            <li key={project.id}>
              <article>
                <h3>{project.name}</h3>
                <p>
                  Created{" "}
                  {new Date(project.created_at).toLocaleDateString(undefined, {
                    year: "numeric",
                    month: "short",
                    day: "numeric",
                  })}
                </p>
                <Link href={projectStudioPath(project)}>Open project</Link>
              </article>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { listProjects, projectStudioPath } from "@/lib/api/projects";
import "./project-library.css";

export function ProjectLibrary() {
  const projects = useQuery({
    queryKey: ["projects", "library"] as const,
    queryFn: ({ signal }) => listProjects(signal),
    retry: false,
    staleTime: 10_000,
  });

  return (
    <section className="project-library" aria-labelledby="library-heading">
      <header className="project-library-header">
        <span className="project-library-sectionNumber" aria-hidden="true">02</span>
        <div>
          <h2 id="library-heading">Your projects</h2>
          <p>Pick up where your story left off.</p>
        </div>
      </header>
      {projects.isPending && (
        <div className="project-library-state" role="status">
          <p className="project-library-stateTitle">Loading your projects…</p>
          <p>Your stories will appear here in a moment.</p>
        </div>
      )}
      {projects.isError && (
        <div className="project-library-state project-library-stateError">
          <div role="alert">
            <p className="project-library-stateTitle">We couldn’t load your projects just now.</p>
            <p>Your work is saved — try again in a moment.</p>
          </div>
          <button
            type="button"
            className="button button-secondary project-library-retry"
            disabled={projects.isFetching}
            onClick={() => void projects.refetch()}
          >
            {projects.isFetching ? "Trying again…" : "Try again"}
          </button>
        </div>
      )}
      {projects.isSuccess && projects.data.length === 0 && (
        <div className="project-library-state" role="status">
          <p className="project-library-stateTitle">No projects yet.</p>
          <p>Name your first story above to get started.</p>
        </div>
      )}
      {projects.isSuccess && projects.data.length > 0 && (
        <ul className="project-library-grid" role="list">
          {projects.data.map((project) => (
            <li key={project.id}>
              <article className="project-library-card" aria-labelledby={`project-${project.id}`}>
                <span className="project-library-mark" aria-hidden="true">/</span>
                <h3 id={`project-${project.id}`}>{project.name}</h3>
                <p className="project-library-date">
                  Created{" "}
                  <time dateTime={project.created_at}>
                    {new Date(project.created_at).toLocaleDateString(undefined, {
                      year: "numeric",
                      month: "short",
                      day: "numeric",
                    })}
                  </time>
                </p>
                <div className="project-library-cardFooter">
                  <Link
                    className="project-library-link"
                    href={projectStudioPath(project)}
                    aria-label={`Open in Studio: ${project.name}`}
                  >
                    Open in Studio
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                      <path d="M5 12h14m-6-6 6 6-6 6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </Link>
                </div>
              </article>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

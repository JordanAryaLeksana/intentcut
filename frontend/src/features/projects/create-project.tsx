"use client";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { createProject } from "@/lib/api/projects";
import Link from "next/link";
import "./create-project.css";

export function CreateProject() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), []);
  return (
    <div className="create-project-page">
      <a href="#create-project" className="create-project-skipLink">Skip to project brief</a>
      <header className="create-project-header">
        <Link href="/" className="create-project-brand" aria-label="IntentCut home" translate="no">
          <span aria-hidden="true">/</span> IntentCut
        </Link>
        <span className="create-project-headerLabel">Creative workspace</span>
      </header>
      <main id="create-project" tabIndex={-1} className="create-project-main">
        <div className="create-project-introduction">
          <p className="create-project-eyebrow">Director’s Brief</p>
          <h1>Every story starts<br />with <span>an intention.</span></h1>
          <p className="create-project-lede">
            Give your next story a name. A dedicated space for your footage,
            your ideas, and the edit ahead.
          </p>
        </div>
        <div className="create-project-composition">
          <section className="create-project-brief" aria-labelledby="brief-heading">
            <div className="create-project-sectionHeader">
              <span className="create-project-sectionNumber" aria-hidden="true">01</span>
              <div>
                <h2 id="brief-heading">Name your project</h2>
                <p>A working title. A place to begin.</p>
              </div>
            </div>
            <form
              className="create-project-form"
              aria-busy={busy}
              onSubmit={async (event) => {
                event.preventDefault();
                if (pending.current) return;
                const controller = new AbortController();
                pending.current = controller;
                setBusy(true);
                setError("");
                try {
                  const project = await createProject(name, controller.signal);
                  router.push(`/projects/${project.id}`);
                } catch (err) {
                  if (!controller.signal.aborted)
                    setError(
                      err instanceof Error
                        ? err.message
                        : "Could not create the project.",
                    );
                  pending.current = null;
                  setBusy(false);
                }
              }}
            >
              <div>
                <div className="create-project-labelRow">
                  <label htmlFor="project-name">Project name <span className="create-project-required">(required)</span></label>
                  <span className="create-project-counter" aria-hidden="true">{name.length}/200</span>
                </div>
                <input
                  id="project-name"
                  name="name"
                  required
                  maxLength={200}
                  value={name}
                  disabled={busy}
                  onChange={(event) => setName(event.target.value)}
                  aria-describedby="project-hint project-error"
                  placeholder="e.g. A weekend in motion"
                  className="create-project-input"
                />
                <p id="project-hint" className="create-project-hint">
                  Use 1–200 characters. Choose a name that feels like your story.
                </p>
              </div>
              <p id="project-error" role="alert" className="create-project-error">
                {error}
              </p>
              <button
                type="submit"
                disabled={busy || !name.trim()}
                className="button button-primary create-project-submit"
              >
                {busy ? "Creating project…" : "Create project"}
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M5 12h14m-6-6 6 6-6 6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>
              </button>
              <p role="status" className="create-project-status">
                {busy
                  ? "Creating your workspace. Please keep this page open."
                  : "Your project will open in Studio once it’s created."}
              </p>
            </form>
          </section>
          <aside className="create-project-overview" aria-labelledby="overview-heading">
            <p className="create-project-eyebrow">Project overview</p>
            <div className="create-project-overviewTitle">
              <span className="create-project-projectMark" aria-hidden="true">/</span>
              <h2 id="overview-heading">{name.trim() || "Your next story"}</h2>
            </div>
            <dl className="create-project-facts">
              <div><dt>Status</dt><dd>{busy ? "Creating…" : error ? "Creation unconfirmed" : "Not created yet"}</dd></div>
              <div><dt>Project link</dt><dd>Assigned on creation</dd></div>
            </dl>
            <div className="create-project-nextNote">
              <h3>A canvas for what’s next</h3>
              <p>Once your project is created, you can bring your footage into Studio and shape your first cut.</p>
            </div>
          </aside>
        </div>
        <footer className="create-project-footer"><span>IntentCut Studio</span><span>Your story. Your direction.</span></footer>
      </main>
    </div>
  );
}

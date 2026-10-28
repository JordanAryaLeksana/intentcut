"use client";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { createProject } from "@/lib/api/client";

export function CreateProject() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), []);
  return <main className="mx-auto max-w-xl px-6 py-16">
    <p className="eyebrow mb-6">IntentCut Studio</p><h1 className="text-4xl font-medium">Start with a story.</h1>
    <p className="mt-5 text-muted-foreground">Create a project to save video files to your local IntentCut backend.</p>
    <form className="mt-10 space-y-5" onSubmit={async event => {
      event.preventDefault(); if (pending.current) return;
      const controller = new AbortController(); pending.current = controller; setBusy(true); setError("");
      try { const project = await createProject(name, controller.signal); router.push(`/projects/${project.id}`); }
      catch (err) { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "Could not create the project."); pending.current = null; setBusy(false); }
    }}>
      <div><label htmlFor="project-name" className="block text-sm font-medium">Project name</label>
      <input id="project-name" name="name" required maxLength={200} value={name} disabled={busy} onChange={event=>setName(event.target.value)} aria-describedby="project-hint project-error" className="mt-2 w-full rounded-md border border-input bg-surface p-3" />
      <p id="project-hint" className="mt-2 text-xs text-muted-foreground">1–200 characters. Your project receives a unique URL.</p></div>
      <p id="project-error" role="alert" className="text-sm text-destructive">{error}</p>
      <button type="submit" disabled={busy || !name.trim()} className="button button-primary disabled:opacity-50">{busy ? "Creating project…" : "Create project"}</button>
      <p role="status" className="text-sm text-muted-foreground">{busy ? "Waiting for the backend. Please keep this page open." : "Local development · No automatic retries"}</p>
    </form>
  </main>;
}

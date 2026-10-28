import Link from "next/link";

export function StudioTopBar({ projectId }: { projectId?: string }) {
  return (
    <header className="studio-topbar">
      <Link href="/" className="studio-brand" aria-label="IntentCut design foundation" translate="no"><span aria-hidden="true">/</span> IntentCut</Link>
      <div className="studio-project"><h1>{projectId ? `Project ${projectId.slice(0, 8)}` : "Untitled project"}</h1><span className="studio-badge">{projectId ? "Local backend" : "Preview"}</span></div>
      <Link href="/studio" className="studio-status underline underline-offset-4">Create project</Link>
      <p className="studio-export">Export <span>Unavailable in preview</span></p>
    </header>
  );
}

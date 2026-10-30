import "./studio.css";
import { StudioTopBar } from "./studio-top-bar";
import { MediaLibrary } from "./media-library";
import { ProgramMonitor } from "./program-monitor";
import { StudioDock } from "./studio-dock";
import { NarrativeTimeline } from "./narrative-timeline";

export function StudioShell({ projectId }: { projectId?: string }) {
  return (
    <div className="studio-shell">
      <a href="#workspace" className="button button-primary sr-only focus:not-sr-only focus:absolute focus:left-6 focus:top-4 focus:z-10">Skip to workspace</a>
      <StudioTopBar projectId={projectId} />
      <main
        id="workspace"
        tabIndex={-1}
        className="studio-workspace"
        aria-label="Studio workspace"
      >
        <ProgramMonitor projectId={projectId} />

        <MediaLibrary
          key={projectId ?? "preview"}
          projectId={projectId}
        />

        <StudioDock key={`dock-${projectId ?? "preview"}`} projectId={projectId} />

        <NarrativeTimeline projectId={projectId} />
      </main>
      <footer className="studio-footer"><span>IntentCut Studio</span><span>Draft editing · Versioned saves</span></footer>
    </div>
  );
}

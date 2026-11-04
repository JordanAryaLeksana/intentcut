"use client";

import { useEditingScope, WorkflowBoundary, selectWorkflow } from "./workflow";
import { workflowScope } from "@/lib/api/workflow";
import { useRef, useState } from "react";
import { CaptionsPanel } from "./captions/captions-panel";
import { VisualsPanel } from "./visuals/visuals-panel";
import { AIDirector } from "./ai-director/ai-director";
import { useProjectMedia } from "./media/hooks/use-project-media";
import { useSelectedMediaIds } from "./store/use-editor-store";
import { useDraftStore } from "./store/use-draft-store";
import { DraftControls } from "./draft-timeline";
import { HighlightNavigator } from "./highlights/highlight-navigator";
import { formatBytes } from "./media/selection";

type DockTab = "director" | "inspector" | "captions" | "visuals" | "highlights";
const TABS: DockTab[] = ["director", "inspector", "captions", "visuals", "highlights"];

export function dockTabForKey(current: DockTab, key: string): DockTab | null {
  if (key === "Home") return TABS[0];
  if (key === "End") return TABS[TABS.length - 1];
  if (key === "ArrowRight" || key === "ArrowLeft") {
    return TABS[(TABS.indexOf(current) + (key === "ArrowLeft" ? TABS.length - 1 : 1)) % TABS.length];
  }
  return null;
}

function SourceInspector({ projectId }: { projectId: string }) {
  const media = useProjectMedia(projectId);
  const selected = useSelectedMediaIds(projectId);
  const sources = media.data?.filter((item) => selected.includes(item.id)) ?? [];

  if (media.isPending) return <p role="status">Loading your footage…</p>;
  if (media.isError) {
    return (
      <div>
        <p role="alert">We couldn’t load your footage details.</p>
        <button type="button" className="button button-secondary" onClick={() => void media.refetch()}>Try again</button>
      </div>
    );
  }
  if (!sources.length) {
    return <p>Pick footage in Media Library to see its details here.</p>;
  }

  return (
    <div className="studio-inspectorSources">
      <p className="studio-overline">{sources.length} video{sources.length === 1 ? "" : "s"} picked</p>
      {sources.map((source) => (
        <article key={source.id} className="studio-inspectorSource">
          <h3>{source.original_filename}</h3>
          <dl>
            <div><dt>Length</dt><dd className="technical">{source.duration_seconds.toFixed(1)} seconds</dd></div>
            <div><dt>Picture size</dt><dd>{source.video.width} × {source.video.height}</dd></div>
            <div><dt>File size</dt><dd>{formatBytes(source.size_bytes)}</dd></div>
          </dl>
          <details>
            <summary>Details for support</summary>
            <p className="studio-sourceId technical">{source.id} · {source.video.codec}</p>
          </details>
        </article>
      ))}
      <p>These details never change. What you tick in Media Library is what AI Director will use.</p>
    </div>
  );
}

function CutInspector({ projectId }: { projectId: string }) {
  const { scope } = useEditingScope(projectId);
  const draft = useDraftStore((state) => state.byProject[scope]);
  const media = useProjectMedia(projectId);
  const index = draft?.cuts.findIndex((cut) => cut.id === draft.selectedId) ?? -1;
  const cut = draft?.cuts[index];
  if (!draft || !cut) return <><p>Tap a moment in Timeline to see where it came from.</p><SourceInspector projectId={projectId} /></>;
  const source = media.data?.find((item) => item.id === cut.media_id);
  return <article className="studio-inspectorSource">
    <h3>Moment {index + 1}</h3>
    <dl>
      <div><dt>From</dt><dd>{source?.original_filename ?? "Your footage"}</dd></div>
      <div><dt>Where in your footage</dt><dd>{cut.start_seconds.toFixed(1)}s – {cut.end_seconds.toFixed(1)}s</dd></div>
      <div><dt>Length</dt><dd>{(cut.end_seconds - cut.start_seconds).toFixed(1)} seconds</dd></div>
      <div><dt>Plays</dt><dd>{index + 1} of {draft.cuts.length} in your story</dd></div>
      <div><dt>Why it’s here</dt><dd>{cut.editorial_reason ?? "Picked to tell your story."}</dd></div>
    </dl>
    <DraftControls projectId={projectId} draft={draft} />
    <p className="studio-storyboardNote">Where a moment comes from never changes. Reordering only changes this draft — save, then make a new video to watch it.</p>
  </article>;
}

export function StudioDock({ projectId }: { projectId?: string }) {
  const { scope, workflow } = useEditingScope(projectId ?? "");
  const [previewTab, setPreviewTab] = useState<DockTab>("director");
  const projectTab = useDraftStore((state) => projectId ? state.dockTabByProject[scope] : undefined);
  const setDockTab = useDraftStore((state) => state.setDockTab);
  const active = projectId ? projectTab ?? (workflow === "highlights" ? "highlights" : "director") : previewTab;
  const setActive = (tab: DockTab) => {
    if (!projectId) { setPreviewTab(tab); return; }
    const nextWorkflow = tab === "highlights" ? "highlights" : tab === "director" ? "first_cut" : workflow;
    selectWorkflow(projectId, nextWorkflow);
    setDockTab(workflowScope(projectId, nextWorkflow), tab);
  };
  const buttons = useRef<Partial<Record<DockTab, HTMLButtonElement | null>>>({});

  return (
    <aside className="studio-dock" aria-label="Inspector and AI tools">
      <div className="studio-dockTabs" role="tablist" aria-label="Editing tools">
        {TABS.map((tab) => (
          <button
            key={tab}
            ref={(node) => { buttons.current[tab] = node; }}
            id={`dock-tab-${tab}`}
            role="tab"
            type="button"
            aria-selected={active === tab}
            aria-controls={`dock-panel-${tab}`}
            tabIndex={active === tab ? 0 : -1}
            onClick={() => setActive(tab)}
            onKeyDown={(event) => {
              const next = dockTabForKey(tab, event.key);
              if (!next) return;
              event.preventDefault();
              setActive(next);
              buttons.current[next]?.focus();
            }}
          >
            {tab === "director" ? "AI First Cut" : tab === "inspector" ? "Details" : tab === "captions" ? "Captions" : tab === "visuals" ? "AI Visuals" : "Highlights"}
          </button>
        ))}
      </div>
      {/* Keep all panels mounted: tab changes must not cancel uploads, lose a
          creative brief, restart recovery, or reset a storyboard viewer. */}
      <div className="studio-dockPanel" id="dock-panel-director" role="tabpanel" aria-labelledby="dock-tab-director" tabIndex={0} hidden={active !== "director"}>
        <WorkflowBoundary workflow="first_cut"><AIDirector projectId={projectId} /></WorkflowBoundary>
      </div>
      <div className="studio-dockPanel studio-inspector" id="dock-panel-inspector" role="tabpanel" aria-labelledby="dock-tab-inspector" tabIndex={0} hidden={active !== "inspector"}>
        <header className="studio-panelHeader"><h2>Details</h2><span>About this moment</span></header>
        <div className="studio-inspectorBody">
          {projectId ? <CutInspector key={projectId} projectId={projectId} /> : <p>Open a project to see details here.</p>}
        </div>
      </div>
      <div className="studio-dockPanel" id="dock-panel-captions" role="tabpanel" aria-labelledby="dock-tab-captions" tabIndex={0} hidden={active !== "captions"}>
        <CaptionsPanel projectId={projectId} />
      </div>
      <div className="studio-dockPanel" id="dock-panel-visuals" role="tabpanel" aria-labelledby="dock-tab-visuals" tabIndex={0} hidden={active!=="visuals"}><VisualsPanel projectId={projectId}/></div>
      <div className="studio-dockPanel" id="dock-panel-highlights" role="tabpanel" aria-labelledby="dock-tab-highlights" tabIndex={0} hidden={active !== "highlights"}>
        <WorkflowBoundary workflow="highlights"><HighlightNavigator projectId={projectId} /></WorkflowBoundary>
      </div>
    </aside>
  );
}

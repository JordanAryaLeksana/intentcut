"use client";

import { useRef, useState } from "react";
import { CaptionsPanel } from "./captions/captions-panel";
import { VisualsPanel } from "./visuals/visuals-panel";
import { AIDirector } from "./ai-director/ai-director";
import { useProjectMedia } from "./media/hooks/use-project-media";
import { useSelectedMediaIds } from "./store/use-editor-store";
import { useDraftStore } from "./store/use-draft-store";
import { DraftControls } from "./draft-timeline";
import { formatBytes } from "./media/selection";

type DockTab = "director" | "inspector" | "captions" | "visuals";
const TABS: DockTab[] = ["director", "inspector", "captions", "visuals"];

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

  if (media.isPending) return <p role="status">Loading source metadata…</p>;
  if (media.isError) {
    return (
      <div>
        <p role="alert">Could not load source metadata.</p>
        <button type="button" className="button button-secondary" onClick={() => void media.refetch()}>Retry metadata</button>
      </div>
    );
  }
  if (!sources.length) {
    return <p>Choose saved footage in the Media Pool to inspect its source metadata.</p>;
  }

  return (
    <div className="studio-inspectorSources">
      <p className="studio-overline">{sources.length} selected source{sources.length === 1 ? "" : "s"}</p>
      {sources.map((source) => (
        <article key={source.id} className="studio-inspectorSource">
          <h3>{source.original_filename}</h3>
          <dl>
            <div><dt>Duration</dt><dd className="technical">{source.duration_seconds.toFixed(3)} s</dd></div>
            <div><dt>Resolution</dt><dd>{source.video.width} × {source.video.height}</dd></div>
            <div><dt>Video codec</dt><dd>{source.video.codec}</dd></div>
            <div><dt>File size</dt><dd>{formatBytes(source.size_bytes)}</dd></div>
            <div><dt>Media ID</dt><dd className="studio-sourceId technical">{source.id}</dd></div>
          </dl>
        </article>
      ))}
      <p>Source metadata is read-only. Selection is used by AI Story Director.</p>
    </div>
  );
}

function CutInspector({ projectId }: { projectId: string }) {
  const draft = useDraftStore((state) => state.byProject[projectId]);
  const media = useProjectMedia(projectId);
  const index = draft?.cuts.findIndex((cut) => cut.id === draft.selectedId) ?? -1;
  const cut = draft?.cuts[index];
  if (!draft || !cut) return <><p>Select a timeline cut to inspect and edit its draft playback order.</p><SourceInspector projectId={projectId} /></>;
  const source = media.data?.find((item) => item.id === cut.media_id);
  return <article className="studio-inspectorSource">
    <h3>Cut {index + 1}</h3>
    <dl>
      <div><dt>Source</dt><dd>{source?.original_filename ?? "Source filename unavailable"}</dd></div>
      <div><dt>Media ID</dt><dd className="studio-sourceId technical">{cut.media_id ?? "Not supplied"}</dd></div>
      <div><dt>Source range</dt><dd>{cut.start_seconds.toFixed(6)} – {cut.end_seconds.toFixed(6)} s</dd></div>
      <div><dt>Source duration</dt><dd>{(cut.end_seconds - cut.start_seconds).toFixed(6)} s</dd></div>
      <div><dt>Draft playback order</dt><dd>{index + 1} of {draft.cuts.length}</dd></div>
      <div><dt>Published playback index</dt><dd>{cut.playback_order ?? "Not supplied"}</dd></div>
      <div><dt>Source window index</dt><dd>{cut.source_window_index ?? "Not supplied"}</dd></div>
      <div><dt>Editorial reason</dt><dd>{cut.editorial_reason ?? "Not supplied by this storyboard"}</dd></div>
    </dl>
    <DraftControls projectId={projectId} draft={draft} />
    <p className="studio-storyboardNote">Source ranges are read-only. Editing affects the working draft; save and render to produce a new video version.</p>
  </article>;
}

export function StudioDock({ projectId }: { projectId?: string }) {
  const [previewTab, setPreviewTab] = useState<DockTab>("director");
  const projectTab = useDraftStore((state) => projectId ? state.dockTabByProject[projectId] : undefined);
  const setDockTab = useDraftStore((state) => state.setDockTab);
  const active = projectId ? projectTab ?? "director" : previewTab;
  const setActive = (tab: DockTab) => projectId ? setDockTab(projectId, tab) : setPreviewTab(tab);
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
            {tab === "director" ? "AI Story Director" : tab === "inspector" ? "Inspector" : tab === "captions" ? "Captions" : "AI Visuals"}
          </button>
        ))}
      </div>
      {/* Keep all panels mounted: tab changes must not cancel uploads, lose a
          creative brief, restart recovery, or reset a storyboard viewer. */}
      <div className="studio-dockPanel" id="dock-panel-director" role="tabpanel" aria-labelledby="dock-tab-director" tabIndex={0} hidden={active !== "director"}>
        <AIDirector projectId={projectId} />
      </div>
      <div className="studio-dockPanel studio-inspector" id="dock-panel-inspector" role="tabpanel" aria-labelledby="dock-tab-inspector" tabIndex={0} hidden={active !== "inspector"}>
        <header className="studio-panelHeader"><h2>Inspector</h2><span>Draft / source</span></header>
        <div className="studio-inspectorBody">
          {projectId ? <CutInspector key={projectId} projectId={projectId} /> : <p>Open a project to inspect its saved footage.</p>}
        </div>
      </div>
      <div className="studio-dockPanel" id="dock-panel-captions" role="tabpanel" aria-labelledby="dock-tab-captions" tabIndex={0} hidden={active !== "captions"}>
        <CaptionsPanel projectId={projectId} />
      </div>
      <div className="studio-dockPanel" id="dock-panel-visuals" role="tabpanel" aria-labelledby="dock-tab-visuals" tabIndex={0} hidden={active!=="visuals"}><VisualsPanel projectId={projectId}/></div>
    </aside>
  );
}

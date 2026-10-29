"use client";

import { useReducer, useRef, useState } from "react";
import { ACCEPT_VIDEO, fileKey, formatBytes, selectVideos } from "./media/selection";
import "./media/media-library.css";
import { PersistedMedia } from "./media/persisted-media";

type State = { files: File[]; errors: string[]; announcement: string };
type Action = { type: "add"; files: File[] } | { type: "remove"; key: string } | { type: "saved"; files: File[] };
function reducer(state: State, action: Action): State {
  if (action.type === "saved") return { files: state.files.filter(file => !action.files.includes(file)), errors: [], announcement: "Confirmed files saved by the backend." };
  if (action.type === "remove") {
    const removed = state.files.find(file => fileKey(file) === action.key);
    return { files: state.files.filter(file => fileKey(file) !== action.key), errors: [], announcement: `${removed?.name ?? "Video"} removed from this local list.` };
  }
  const result = selectVideos(state.files, action.files);
  return { ...result, announcement: `${result.added} video${result.added === 1 ? "" : "s"} added locally. ${result.files.length} selected. Nothing uploaded.` };
}

export function MediaLibrary({ projectId }: { projectId?: string }) {
  const [state, dispatch] = useReducer(reducer, { files: [], errors: [], announcement: "" });
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const dragDepth = useRef(0);
  const input = useRef<HTMLInputElement>(null);
  const chooseButton = useRef<HTMLButtonElement>(null);

  return (
    <section className="studio-panel studio-library" aria-labelledby="library-heading">
      <header className="studio-panelHeader"><h2 id="library-heading">Media Pool</h2><span className="technical">{state.files.length} local</span></header>
      <div className="media-library-content">
        <details className="studio-import" open={projectId ? undefined : true}>
          <summary>Import footage <span>Local videos</span></summary>
        <div className="media-dropzone" data-dragging={dragging}
          onDragEnter={event => { event.preventDefault(); dragDepth.current += 1; setDragging(true); }}
          onDragOver={event => { event.preventDefault(); event.dataTransfer.dropEffect = "copy"; }}
          onDragLeave={event => { event.preventDefault(); dragDepth.current = Math.max(0, dragDepth.current - 1); if (!dragDepth.current) setDragging(false); }}
          onDrop={event => { event.preventDefault(); dragDepth.current = 0; setDragging(false); if (!busy) dispatch({ type: "add", files: Array.from(event.dataTransfer.files) }); }}>
          <svg width="28" height="28" viewBox="0 0 28 28" fill="none" aria-hidden="true"><rect x="3" y="5" width="22" height="18" rx="2" stroke="currentColor"/><path d="M14 9v10m-5-5h10" stroke="currentColor"/></svg>
          <h3>{dragging ? "Drop videos here" : "Bring your footage"}</h3>
          <p>Drop video files here or browse your device.</p>
          <input ref={input} disabled={busy} type="file" accept={ACCEPT_VIDEO} multiple hidden aria-label="Choose local videos" onChange={event => { const files = Array.from(event.currentTarget.files ?? []); if (files.length) dispatch({ type: "add", files }); event.currentTarget.value = ""; }} />
          <button ref={chooseButton} disabled={busy} type="button" className="button button-primary media-choose" aria-describedby="media-limits media-privacy" onClick={() => input.current?.click()}>Choose videos</button>
          <p id="media-limits" className="media-limits">MP4, WebM, MOV, M4V<br />Up to 20 files · 2 GiB each</p>
        </div>
        <div role="status" aria-live="polite" aria-atomic="true" className="sr-only">{state.announcement}</div>
        <div role="alert" aria-atomic="true">
          {state.errors.length > 0 && <div className="media-errors"><h3>Some files weren’t added</h3><ul>{state.errors.map((error, index) => <li key={index}>{error}</li>)}</ul></div>}
        </div>
        {state.files.length === 0 ? <div className="media-empty"><h3>{projectId ? "No local videos selected" : "Your library is empty"}</h3><p>Select videos to see their filenames and sizes here.</p></div> :
          <ul className="media-list" aria-label="Local video files">{state.files.map(file => (
            <li key={fileKey(file)} className="media-file">
              <span className="media-file-type technical">{file.name.split(".").pop()?.toUpperCase()}</span>
              <h3>{file.name}</h3>
              <p className="technical">{formatBytes(file.size)} <span>· Local file</span></p>
              <button type="button" className="media-remove" disabled={busy} aria-label={`Remove ${file.name}`} onClick={() => { dispatch({ type: "remove", key: fileKey(file) }); chooseButton.current?.focus(); }}>Remove<span className="sr-only"> from local list</span></button>
            </li>
          ))}</ul>}
        </details>
        {projectId && <PersistedMedia projectId={projectId} files={state.files} onBusy={setBusy} onSaved={files=>dispatch({ type: "saved", files })} />}
        <p id="media-privacy" className="media-privacy">{projectId ? "Selected files stay in this tab until you upload them. Only confirmed saved media survives a reload. Browser File objects are never persisted." : "Only in this tab. Files are not uploaded or saved. Reloading or leaving this page clears the list."}</p>
      </div>
    </section>
  );
}

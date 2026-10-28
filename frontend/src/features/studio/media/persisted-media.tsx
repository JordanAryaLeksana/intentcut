"use client";
import { useEffect, useRef, useState } from "react";
import { ApiError, listAllMedia, uploadMedia, type MediaAsset } from "@/lib/api/client";
import { formatBytes } from "./selection";

export function PersistedMedia({ projectId, files, onSaved, onBusy }: { projectId: string; files: File[]; onSaved: (files: File[]) => void; onBusy: (busy: boolean) => void }) {
  const [items, setItems] = useState<MediaAsset[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const mutation = useRef<AbortController | null>(null);
  const read = useRef<AbortController | null>(null);
  useEffect(() => {
    const c = new AbortController(); read.current = c;
    listAllMedia(projectId, c.signal).then(setItems).catch(err=>{if (!c.signal.aborted) setError(err.message);}).finally(()=>{if (!c.signal.aborted) setLoading(false);});
    return () => { read.current?.abort(); mutation.current?.abort(); };
  }, [projectId]);
  async function refresh() {
    read.current?.abort(); const c = new AbortController(); read.current=c; setLoading(true); setError("");
    try { setItems(await listAllMedia(projectId,c.signal)); }
    catch(err) { if (!c.signal.aborted) setError(err instanceof Error ? err.message : "Could not load saved media."); }
    finally { if (!c.signal.aborted) setLoading(false); }
  }
  async function upload() {
    if (mutation.current || uncertain) return;
    const c = new AbortController(); mutation.current = c; const submitted = [...files];
    setUploading(true); onBusy(true); setError(""); setMessage("Sending videos and waiting for server confirmation…");
    try {
      const result = await uploadMedia(projectId, submitted, c.signal);
      setItems(previous => [...previous.filter(item=>!result.items.some(saved=>saved.id===item.id)), ...result.items]);
      onSaved(submitted); setMessage(`${result.items.length} videos saved by the backend.`);
      await refresh();
    } catch(err) {
      const api = err instanceof ApiError ? err : null;
      setError(`${api?.fileIndex !== undefined ? `File ${api.fileIndex + 1}: ` : ""}${err instanceof Error ? err.message : "Upload failed."}`);
      setMessage("");
      if (!api || api.status===0 && !["upload_limit","configuration_error","invalid_project"].includes(api.code) || api.status>=500) setUncertain(true);
    } finally { mutation.current=null; setUploading(false); onBusy(false); }
  }
  return <div className="media-persisted">
    <h3 className="text-sm font-medium">Saved to this project</h3>
    <p className="mt-2 text-xs text-muted-foreground">Upload limits: 10 videos, 128 MiB each, 500 MiB total. Server limits may be lower.</p>
    <div className="mt-3 flex flex-wrap gap-2">
      <button type="button" className="button button-primary disabled:opacity-50" disabled={!files.length || uploading || uncertain} onClick={upload}>{uploading ? "Uploading…" : "Upload selected"}</button>
      {uploading && <button type="button" className="button button-secondary" onClick={()=>mutation.current?.abort()}>Cancel request</button>}
      <button type="button" className="media-remove" disabled={loading || uploading} onClick={refresh}>Refresh saved media</button>
    </div>
    <p role="status" className="mt-2 text-xs text-primary">{message}{loading ? " Loading saved media…" : ""}</p>
    {error && <p role="alert" className="media-errors">{error}</p>}
    {uncertain && <div className="media-errors"><p>The server may have saved these files. Refresh and review saved media before submitting again. Cancellation does not roll back server work.</p><button type="button" className="media-remove" onClick={()=>setUncertain(false)}>I reviewed saved media; allow another upload</button></div>}
    {!loading && !error && !items.length && <p className="mt-3 text-xs text-muted-foreground">No saved videos yet.</p>}
    <ul className="media-list" aria-label="Saved project media">{items.map(item=><li className="media-file" key={item.id}><span className="media-file-type">Saved</span><h3>{item.original_filename}</h3><p>{formatBytes(item.size_bytes)} · {item.duration_seconds.toFixed(2)} s</p><p>{item.video.width} × {item.video.height} · {item.video.codec}</p><p className="break-all">Media ID: {item.id}</p></li>)}</ul>
  </div>;
}

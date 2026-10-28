
export function ProgramMonitor() {
  return (
    <section className={`studio-panel studio-monitor`} aria-labelledby="monitor-heading">
      <header className="studio-panelHeader"><h2 id="monitor-heading">Program Monitor</h2><span className="technical">16:9</span></header>
      <div className="studio-monitorBody">
        <div className="studio-frame">
          <div><svg className="studio-monitorIcon" viewBox="0 0 48 36" fill="none" aria-hidden="true"><path d="M10 1H1v9M38 1h9v9M1 26v9h9m37-9v9h-9" stroke="currentColor" strokeWidth="1.5"/><rect x="17" y="12" width="14" height="12" rx="1" stroke="currentColor"/></svg><h3>Your story takes shape here</h3><p>No media selected</p></div>
        </div>
        <div className="studio-monitorMeta"><span>Program view</span><span>Playback unavailable in preview</span></div>
      </div>
    </section>
  );
}

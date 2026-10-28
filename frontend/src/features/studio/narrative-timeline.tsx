
export function NarrativeTimeline() {
  return (
    <section className={`studio-panel studio-timeline`} aria-labelledby="timeline-heading">
      <header className="studio-panelHeader"><h2 id="timeline-heading">Narrative Timeline</h2><span>Storyboard · Preview</span></header>
      <div className="studio-timelineBody">
        <div className="studio-trackLabel"><span className="studio-overline">Story sequence</span><span className="technical">0 scenes</span></div>
        <div className="studio-emptyTimeline"><div><h3>Every story starts with a first scene</h3><p>Your storyboard will appear here as your narrative develops.</p><span>Scene editing is unavailable in this preview.</span></div></div>
      </div>
    </section>
  );
}

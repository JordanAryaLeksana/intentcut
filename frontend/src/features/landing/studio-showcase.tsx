import Image from "next/image";

const tools = [
  ["01", "Program Monitor", "Review rendered video and select the version you want to preview or download."],
  ["02", "Narrative Timeline", "Read the sequence, rearrange or remove cuts, and save a versioned draft."],
  ["03", "AI Director", "Set your intention, generate a first cut, and review revision proposals."],
  ["04", "Media Library", "Upload source videos, inspect their metadata, and select footage for the first cut."],
  ["05", "Captions", "Review transcribed captions, edit their text, and export a captioned MP4."],
  ["06", "AI Visuals", "Generate or edit images with Muse Image, preview saved assets, and choose a project cover."],
];
export function StudioShowcase() {
  return <section id="studio" className="landing-section landing-studio" aria-labelledby="studio-title">
    <div className="landing-section-heading"><div><p className="landing-kicker">03 / Inside the Studio</p><h2 id="studio-title">Room to see the whole story.</h2></div><p>Footage, editorial decisions, and the finished frame. Together in one focused workspace.</p></div>
    <figure className="landing-workspace-figure">
      <div className="landing-workspace" aria-hidden="true">
        <div className="landing-workspace-bar"><span><b>/</b> IntentCut Studio</span><span>Workspace illustration</span></div>
        <div className="landing-workspace-body">
          <div className="landing-mock-library"><span className="landing-mock-label">04 / Media Library</span>{[1,2,3].map(n=><div key={n}><Image src={`/landing/frame-${n}.svg`} width={160} height={100} alt="" /><span>Frame study 0{n}</span></div>)}</div>
          <div className="landing-mock-monitor"><span className="landing-mock-label">01 / Program Monitor</span><div className="landing-monitor-image"><Image src="/landing/frame-2.svg" width={960} height={600} alt="" /><span>A story takes shape.</span></div><p>Review the frame. Decide what comes next.</p></div>
          <div className="landing-mock-director"><span className="landing-mock-label">03 / AI Director</span><h3>What should this story feel like?</h3><p>Your creative direction gives the edit a point of view.</p><div className="landing-mock-note">Intention → Editorial plan → First cut</div><span className="landing-mock-label">05 / Captions</span><p>Words that belong to the story.</p><span className="landing-mock-label">06 / AI Visuals</span><p>A visual identity for your project.</p></div>
        </div>
        <div className="landing-mock-timeline"><span className="landing-mock-label">02 / Narrative Timeline</span><div>{[1,2,3,2,1].map((n,i)=><div key={i}><Image src={`/landing/frame-${n}.svg`} width={160} height={100} alt="" /><span>Cut {String(i+1).padStart(2,"0")}</span></div>)}</div></div>
      </div>
      <figcaption>Illustrative workspace composition · original abstract artwork, not a product screenshot or generated edit.</figcaption>
    </figure>
    <div className="landing-tool-grid">{tools.map(([n,title,description])=><article key={n}><span className="landing-index">{n}</span><div><h3>{title}</h3><p>{description}</p></div></article>)}</div>
  </section>;
}

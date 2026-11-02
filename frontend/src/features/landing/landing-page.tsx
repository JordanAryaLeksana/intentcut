import Link from "next/link";
import Image from "next/image";
import { LandingNavigation } from "./navigation";
import { LivingStoryboard } from "./living-storyboard";
import { StudioShowcase } from "./studio-showcase";
import "./landing.css";

const workflow = [
  ["Create your project", "Give your story a name. Project creation opens your workspace in Studio."],
  ["Upload your footage", "Bring source videos into the Studio Media Library, then choose the saved footage to work with."],
  ["Set the direction", "Describe the story you want to tell and choose a target duration in AI Director."],
  ["Make the first cut", "Muse Spark helps analyze the footage and plan a sequence. A background worker renders the edit."],
  ["Review. Refine. Export.", "Review the result, edit your draft or request a revision, then render and download an MP4."],
];
export function LandingPage() {
  return <div className="landing">
    <a className="landing-skip" href="#landing-main">Skip to content</a>
    <div className="landing-container"><LandingNavigation /></div>
    <main id="landing-main" tabIndex={-1}>
      <section className="landing-hero landing-container" aria-labelledby="hero-title">
        <div className="landing-hero-top"><p className="landing-kicker">Your AI storytelling director</p><span className="landing-edition">A new perspective on the edit</span></div>
        <div className="landing-hero-copy"><h1 id="hero-title">Turn raw footage<br />into a story<br /><em>worth telling.</em></h1><div className="landing-hero-aside"><span className="landing-cross" aria-hidden="true">+</span><p>From understanding your footage to crafting the first cut. You direct the story. AI helps bring it together.</p><div className="landing-hero-actions"><Link className="landing-button" href="/studio">Start Creating <span aria-hidden="true">↗</span></Link><a className="landing-text-link" href="#workflow">Explore How It Works <span aria-hidden="true">↓</span></a></div></div></div>
        <LivingStoryboard />
        <div className="landing-hero-foot"><span>Built for the Meta Global AI Developer Hackathon 2026</span><span>Human intention. Machine assistance.</span></div>
      </section>
      <div className="landing-container">
        <section id="workflow" className="landing-section landing-workflow" aria-labelledby="workflow-title">
          <div className="landing-workflow-intro"><p className="landing-kicker">01 / From footage to story</p><h2 id="workflow-title">Find the thread.<br /><span>Build the story.</span></h2><p>A collection of clips is a beginning. Give it a direction, discover the sequence, and make the edit your own.</p><div className="landing-contact-sheet" aria-hidden="true">{[1,2,3].map(n=><Image key={n} src={`/landing/frame-${n}.svg`} width={240} height={150} alt="" />)}</div><p className="landing-caption">Original frame studies</p></div>
          <ol className="landing-steps">{workflow.map(([title,body],i)=><li key={title}><span className="landing-index">0{i+1}</span><div><h3>{title}</h3><p>{body}</p></div></li>)}</ol>
        </section>
        <section id="features" className="landing-section" aria-labelledby="features-title">
          <div className="landing-section-heading"><div><p className="landing-kicker">02 / Creative intelligence</p><h2 id="features-title">A considered edit.<br />An expanded toolkit.</h2></div><p>From the first editorial decision to the final export, assistance where it matters. Control where it counts.</p></div>
          <div className="landing-feature-lead"><div className="landing-analysis-art" aria-hidden="true"><Image src="/landing/frame-3.svg" width={960} height={600} alt="" /><span className="landing-viewfinder" /><span className="landing-art-label">Observe / Interpret / Connect</span></div><article><p className="landing-kicker">Muse Spark / Video understanding</p><h3>Look beyond<br />the individual frame.</h3><p>Muse Spark analyzes footage windows to help identify visual content and inform editorial decisions. That understanding supports the story plan and selection of source moments.</p><span className="landing-caption">Illustrated with original abstract artwork</span></article></div>
          <div className="landing-feature-pair"><article><span className="landing-index">Editorial / 01</span><h3>AI Story Director</h3><p>Turn your creative brief and selected footage into an editorial plan and an AI-assisted first cut. Review the storyboard to see how the sequence comes together.</p><div className="landing-sequence" aria-hidden="true"><span>Intention</span><b>→</b><span>Sequence</span><b>→</b><span>First cut</span></div></article><article><span className="landing-index">Editorial / 02</span><h3>Natural-language refinement</h3><p>Ask Muse Spark to reorder or remove existing cuts. Compare the proposed sequence, accept or reject it, and render the saved revision when you’re ready.</p><blockquote>“Move the last cut first.”<cite>Example revision instruction</cite></blockquote></article></div>
          <div className="landing-feature-row"><span className="landing-index">Finish / 01</span><h3>Editable captions</h3><p>Transcribe a rendered video, review and edit caption text, choose which cues to include, and export a captioned MP4.</p><span className="landing-feature-symbol" aria-hidden="true">[Cc]</span></div>
          <div className="landing-feature-row"><span className="landing-index">Finish / 02</span><h3>AI Visuals</h3><p>Create images with Muse Image, edit an image or rendered-frame reference, preview saved assets, and select your project cover.</p><span className="landing-feature-symbol" aria-hidden="true">▧</span></div>
          <div className="landing-feature-row"><span className="landing-index">Finish / 03</span><h3>Real MP4 rendering</h3><p>FFmpeg renders the sequence into an actual video artifact. Preview the result in Studio and download the MP4.</p><span className="landing-feature-symbol landing-mono" aria-hidden="true">.mp4</span></div>
        </section>
        <StudioShowcase />
        <section className="landing-section landing-philosophy" aria-labelledby="philosophy-title"><p className="landing-kicker">04 / Human + AI</p><div className="landing-philosophy-grid"><h2 id="philosophy-title">You direct.<br /><span>AI helps</span><br />create.</h2><div><span className="landing-cross" aria-hidden="true">+</span><p className="landing-large-copy">The point of view<br />is always yours.</p><p>AI can help organize footage and suggest an edit. The decisions that give a story its meaning still belong to you.</p><p>Review the storyboard. Question the order. Keep a moment, remove a cut, or try another direction. A first cut is a conversation, not the final word.</p><div className="landing-principles"><span>Your intention</span><span>Your review</span><span>Your decision</span></div></div></div></section>
        <section className="landing-section landing-engineering" aria-labelledby="engineering-title"><div className="landing-section-heading"><div><p className="landing-kicker">05 / Under the surface</p><h2 id="engineering-title">Creative on the outside.<br />Considered underneath.</h2></div><p>A working media pipeline connecting your creative direction to saved projects, background processing, and rendered artifacts.</p></div><ol className="landing-pipeline"><li><span>01 / Interface</span><strong>Frontend</strong><p>Next.js · TypeScript</p></li><li><span>02 / Coordination</span><strong>Backend orchestration</strong><p>FastAPI · PostgreSQL</p></li><li><span>03 / Interpretation</span><strong>AI processing</strong><p>Background worker<br />Meta Muse Spark · Meta Muse Image</p></li><li><span>04 / Production</span><strong>Media rendering</strong><p>FFmpeg</p></li><li><span>05 / Delivery</span><strong>Artifacts</strong><p>Video · Storyboard · Images</p></li></ol><div className="landing-engineering-note"><span className="landing-index">Built to make something real.</span><p>Project and media records live in PostgreSQL. The backend queues work for processing; workers publish artifacts that Studio can retrieve for review and download.</p></div></section>
        <section className="landing-final" aria-labelledby="final-title"><div className="landing-final-frame" aria-hidden="true"><Image src="/landing/frame-1.svg" width={960} height={600} alt="" /></div><div><p className="landing-kicker">The next frame is yours</p><h2 id="final-title">Your next story starts<br />with a single frame.</h2><Link href="/studio" className="landing-button">Open IntentCut Studio <span aria-hidden="true">↗</span></Link><p>Name your project. Find your direction.</p></div></section>
      </div>
    </main>
    <footer className="landing-footer landing-container"><div><Link href="/" className="landing-brand"><span aria-hidden="true">/</span> IntentCut</Link><p>Your AI Storytelling Director</p></div><nav aria-label="Footer navigation"><a href="#features">Features</a><a href="#workflow">How it works</a><a href="#studio">Inside the Studio</a><Link href="/studio">Open Studio ↗</Link></nav><div className="landing-footer-bottom"><span>Meta Global AI Developer Hackathon 2026</span><span>Original visual studies created for IntentCut.</span></div></footer>
  </div>;
}

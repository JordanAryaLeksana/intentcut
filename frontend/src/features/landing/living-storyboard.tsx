"use client";

import dynamic from "next/dynamic";
import Image from "next/image";
import { Component, useCallback, useEffect, useRef, useState, type ReactNode } from "react";

const Scene = dynamic(() => import("./storyboard-scene"), { ssr: false });
class SceneBoundary extends Component<{children: ReactNode; onFailure: () => void}, {failed: boolean}> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch() { this.props.onFailure(); }
  render() { return this.state.failed ? null : this.props.children; }
}

export function LivingStoryboard() {
  const host = useRef<HTMLDivElement>(null);
  const [eligible, setEligible] = useState(false);
  const [visible, setVisible] = useState(false);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const handleReady = useCallback(() => setReady(true), []);
  const handleFailure = useCallback(() => setFailed(true), []);
  useEffect(() => {
    const query = matchMedia("(min-width: 701px) and (prefers-reduced-motion: no-preference)");
    const connection = (navigator as Navigator & {connection?: {saveData?: boolean}}).connection;
    const update = () => setEligible(query.matches && !connection?.saveData);
    update(); query.addEventListener("change", update);
    const observer = new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting), {rootMargin: "80px"});
    if (host.current) observer.observe(host.current);
    return () => { query.removeEventListener("change", update); observer.disconnect(); };
  }, []);
  return <figure className="landing-storyboard">
    <div className="landing-scene" ref={host} aria-hidden="true">
      <div className="landing-static-scene">
        {[1, 2, 3].map((frame) => <div className={`landing-film landing-film-${frame}`} key={frame}>
          <div className="landing-film-label">INTENTCUT / FRAME 0{frame}</div>
          <Image src={`/landing/frame-${frame}.svg`} width={960} height={600} alt="" priority={frame === 2} />
          <span className="landing-film-footer">{["A place to begin", "Find the connection", "Follow the story"][frame - 1]}</span>
        </div>)}
      </div>
      {eligible && !failed && <div className="landing-webgl" style={{opacity: ready ? 1 : 0}}>
        <SceneBoundary onFailure={handleFailure}><Scene active={visible} onReady={handleReady} onFailure={handleFailure} /></SceneBoundary>
      </div>}
    </div>
    <figcaption><span>Raw footage <b>→</b> Storyboard <b>→</b> First cut</span><small>Original visual study · illustrative, not AI output</small></figcaption>
  </figure>;
}

"use client";

import Link from "next/link";
import { useRef, useState } from "react";

export function LandingNavigation() {
  const [open, setOpen] = useState(false);
  const toggle = useRef<HTMLButtonElement>(null);
  return <header className="landing-nav" onKeyDown={event => {
    if (event.key === "Escape" && open) { setOpen(false); toggle.current?.focus(); }
  }}>
    <Link href="/" className="landing-brand" aria-label="IntentCut home"><span aria-hidden="true">/</span> IntentCut</Link>
    <button ref={toggle} className="landing-menu" aria-expanded={open} aria-controls="landing-links" onClick={() => setOpen(!open)}>{open ? "Close menu −" : "Menu +"}</button>
    <nav id="landing-links" className="landing-links" data-open={open} aria-label="Main navigation">
      <a href="#features" onClick={() => setOpen(false)}>Features</a>
      <a href="#workflow" onClick={() => setOpen(false)}>How it works</a>
      <a href="#studio" onClick={() => setOpen(false)}>Inside the Studio</a>
      <Link href="/studio" className="landing-button landing-button-small">Open Studio <span aria-hidden="true">↗</span></Link>
    </nav>
  </header>;
}

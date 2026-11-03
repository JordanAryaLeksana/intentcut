"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  TAKE_TOUR_EVENT,
  TOUR_STEPS,
  isLastStep,
  placementFor,
  stepIndexAfter,
} from "./studio-tour-logic";
import "./studio-tour.css";

interface Spot {
  top: number;
  left: number;
  width: number;
  height: number;
  placement: "center" | "below" | "above";
}

export function StudioTour() {
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState(0);
  const [spot, setSpot] = useState<Spot | null>(null);
  const started = useRef(false);
  const card = useRef<HTMLDivElement>(null);
  const restoreFocus = useRef<Element | null>(null);

  const close = useCallback(() => {
    setOpen(false);
    const target = restoreFocus.current;
    if (target instanceof HTMLElement) target.focus();
  }, []);

  // Launch once per Studio entry (mount). Ordinary rerenders never
  // relaunch, and nothing is persisted to suppress future entries.
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    restoreFocus.current = document.activeElement;
    const timer = window.setTimeout(() => setOpen(true), 350);
    return () => window.clearTimeout(timer);
  }, []);

  // Help → "Take a tour" reopens from the first step at any time.
  useEffect(() => {
    const reopen = () => {
      restoreFocus.current = document.activeElement;
      setStep(0);
      setOpen(true);
    };
    window.addEventListener(TAKE_TOUR_EVENT, reopen);
    return () => window.removeEventListener(TAKE_TOUR_EVENT, reopen);
  }, []);

  const measure = useCallback(() => {
    const current = TOUR_STEPS[step];
    const element = current
      ? document.querySelector(`[data-tour="${current.target}"]`)
      : null;
    if (!(element instanceof HTMLElement)) {
      setSpot({ top: 0, left: 0, width: 0, height: 0, placement: "center" });
      return;
    }
    const rect = element.getBoundingClientRect();
    const visible =
      rect.width > 0 &&
      rect.height > 0 &&
      getComputedStyle(element).display !== "none" &&
      getComputedStyle(element).visibility !== "hidden";
    setSpot({
      top: rect.top,
      left: rect.left,
      width: rect.width,
      height: rect.height,
      placement: placementFor(
        visible ? rect : null,
        { width: window.innerWidth, height: window.innerHeight },
      ),
    });
  }, [step]);

  useEffect(() => {
    if (!open) return;
    // Defer measuring past this render so the lint rule against
    // synchronous setState in effects stays satisfied.
    const frame = window.requestAnimationFrame(measure);
    card.current?.focus();
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [open, measure]);

  // Keyboard works even if focus has left the card; the tour never
  // touches editing state, so global handling is safe here.
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
      if (event.key === "ArrowRight") setStep((s) => stepIndexAfter(s, 1));
      if (event.key === "ArrowLeft") setStep((s) => stepIndexAfter(s, -1));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, close]);

  if (!open) return null;
  const current = TOUR_STEPS[step];
  const last = isLastStep(step);
  const cardStyle =
    spot && spot.placement !== "center"
      ? {
          top:
            spot.placement === "below"
              ? `${Math.min(window.innerHeight - 240, spot.top + spot.height + 12)}px`
              : undefined,
          bottom:
            spot.placement === "above"
              ? `${Math.max(12, window.innerHeight - spot.top + 12)}px`
              : undefined,
          left: `${Math.max(12, Math.min(window.innerWidth - 372, spot.left))}px`,
        }
      : undefined;

  return (
    <div className="studio-tour">
      {spot && spot.placement !== "center" && (
        <div
          aria-hidden="true"
          className="studio-tourSpot"
          style={{
            top: spot.top - 6,
            left: spot.left - 6,
            width: spot.width + 12,
            height: spot.height + 12,
          }}
        />
      )}
      <div
        ref={card}
        role="dialog"
        aria-modal="false"
        aria-label={`Studio tour, step ${step + 1} of ${TOUR_STEPS.length}: ${current.title}`}
        tabIndex={-1}
        className={`studio-tourCard is-${spot?.placement ?? "center"}`}
        style={cardStyle}
      >
        <p className="studio-tourProgress" role="status">
          Step {step + 1} of {TOUR_STEPS.length}
        </p>
        <h2>{current.title}</h2>
        <p>{current.body}</p>
        <div className="studio-tourActions">
          <button type="button" className="button button-secondary" onClick={close}>
            Skip
          </button>
          <button
            type="button"
            className="button button-secondary"
            disabled={step === 0}
            onClick={() => setStep((s) => stepIndexAfter(s, -1))}
          >
            Back
          </button>
          {last ? (
            <button type="button" className="button button-primary" onClick={close}>
              Finish
            </button>
          ) : (
            <button
              type="button"
              className="button button-primary"
              onClick={() => setStep((s) => stepIndexAfter(s, 1))}
            >
              Next
            </button>
          )}
        </div>
        <p className="studio-tourHint">Use Next and Back, arrow keys, or Escape to exit. Your work is not changed.</p>
      </div>
    </div>
  );
}

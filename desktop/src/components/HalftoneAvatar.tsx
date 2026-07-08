import { useEffect, useRef } from "react";

// Halftone-dots avatar, echoing the logo + landing page: a circular field of
// white dots whose brightness pulses from the centre, alive and reacting to what
// Jardo is doing. Pure canvas, no video (so no play-button overlay ever).
//
// State drives the mood:
//   idle/waiting  — slow, dim breathing
//   listening     — brighter, quicker ripple (it's hearing you)
//   thinking/…    — a bright node orbits the ring
//   speaking/done — lively pulse (it's talking)
//   stuck/off_task/error — warm/desaturated, restless

type Props = { state: string; size: number; className?: string };

const WARM = { r: 224, g: 180, b: 115 }; // amber, for stuck/off-task
const BAD = { r: 226, g: 140, b: 140 }; // red, for error
const WHITE = { r: 255, g: 255, b: 255 };

function paletteFor(state: string) {
  if (state === "error") return BAD;
  if (state === "stuck" || state === "off_task") return WARM;
  return WHITE;
}

// Per-state animation parameters (speed, pulse amplitude, base brightness, orbit).
function paramsFor(state: string) {
  switch (state) {
    case "listening":
      return { speed: 0.07, amp: 0.42, base: 0.72, orbit: 0.0 };
    case "speaking":
    case "done":
    case "progressing":
      return { speed: 0.1, amp: 0.5, base: 0.66, orbit: 0.0 };
    case "thinking":
      return { speed: 0.045, amp: 0.22, base: 0.52, orbit: 1.0 };
    case "stuck":
    case "off_task":
    case "error":
      return { speed: 0.05, amp: 0.3, base: 0.5, orbit: 0.6 };
    default: // idle / waiting / unknown
      return { speed: 0.025, amp: 0.16, base: 0.48, orbit: 0.0 };
  }
}

export function HalftoneAvatar({ state, size, className }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const stateRef = useRef(state);
  stateRef.current = state;

  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const cv = canvasRef.current;
    if (!cv) return;
    const ctx = cv.getContext("2d");
    if (!ctx) return;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    cv.width = size * dpr;
    cv.height = size * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const cx = size / 2;
    const cy = size / 2;
    const radius = size / 2;
    const gap = Math.max(4, size / 13); // dot grid spacing scales with the avatar
    const dotMax = gap * 0.42;

    let t = 0;
    let raf = 0;

    function smooth(a: number, b: number, x: number) {
      const s = Math.max(0, Math.min(1, (x - a) / (b - a)));
      return s * s * (3 - 2 * s);
    }

    function frame() {
      const p = paramsFor(stateRef.current);
      const col = paletteFor(stateRef.current);
      t += p.speed;
      ctx!.clearRect(0, 0, size, size);

      // A pulse travelling outward from the centre gives the "breathing" feel.
      const pulse = Math.sin(t) * 0.5 + 0.5;
      // Optional orbiting bright node (thinking / restless states).
      const ox = cx + Math.cos(t * 1.6) * radius * 0.55 * p.orbit;
      const oy = cy + Math.sin(t * 1.6) * radius * 0.55 * p.orbit;

      for (let y = gap / 2; y < size; y += gap) {
        for (let x = gap / 2; x < size; x += gap) {
          const dx = x - cx;
          const dy = y - cy;
          const dist = Math.hypot(dx, dy);
          if (dist > radius) continue; // clip to the circle
          const nd = dist / radius; // 0 centre → 1 edge

          // Radial falloff, brighter in the middle, modulated by the pulse so the
          // ring of brightness expands and contracts.
          const ring = 1 - Math.abs(nd - pulse * 0.7);
          let v = p.base * (1 - nd * 0.5) + p.amp * Math.max(0, ring);

          // Orbiting node adds a local highlight.
          if (p.orbit > 0) {
            const od = Math.hypot(x - ox, y - oy) / radius;
            v += (1 - smooth(0, 0.28, od)) * 0.5 * p.orbit;
          }

          // Soft edge fade so the disc doesn't hard-clip.
          v *= 1 - smooth(0.82, 1.0, nd);
          v = Math.max(0, Math.min(1, v));
          if (v < 0.05) continue;

          ctx!.beginPath();
          ctx!.arc(x, y, v * dotMax, 0, Math.PI * 2);
          ctx!.fillStyle = `rgba(${col.r},${col.g},${col.b},${0.08 + v * 0.9})`;
          ctx!.fill();
        }
      }

      if (!reduce) raf = requestAnimationFrame(frame);
    }

    frame(); // draw at least one frame (and keep animating unless reduced-motion)
    return () => cancelAnimationFrame(raf);
  }, [size]);

  return (
    <canvas
      ref={canvasRef}
      className={className}
      style={{ width: size, height: size }}
      aria-hidden="true"
    />
  );
}

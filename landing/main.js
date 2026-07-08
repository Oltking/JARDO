/* Jardo landing, vanilla, no deps.
   Halftone hero (the logo's dot-matrix, alive), scroll reveals, nav state,
   magnetic buttons, stat count-ups. All motion respects reduced-motion. */

(() => {
  "use strict";
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* year -------------------------------------------------------- */
  const y = document.getElementById("year");
  if (y) y.textContent = new Date().getFullYear();

  /* nav: solidify after scrolling past the fold ----------------- */
  const nav = document.getElementById("nav");
  const onScroll = () => nav.classList.toggle("is-stuck", window.scrollY > 24);
  onScroll();
  window.addEventListener("scroll", onScroll, { passive: true });

  /* scroll reveal ----------------------------------------------- */
  const reveals = document.querySelectorAll(".reveal");
  if (reduce || !("IntersectionObserver" in window)) {
    reveals.forEach((el) => el.classList.add("in"));
  } else {
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e, i) => {
          if (e.isIntersecting) {
            // gentle stagger for siblings entering together
            e.target.style.transitionDelay = `${Math.min(i * 70, 280)}ms`;
            e.target.classList.add("in");
            io.unobserve(e.target);
          }
        });
      },
      { threshold: 0.16, rootMargin: "0px 0px -8% 0px" }
    );
    reveals.forEach((el) => io.observe(el));
  }

  /* stat count-ups ---------------------------------------------- */
  const stats = document.querySelectorAll(".stat__num");
  const runCount = (el) => {
    const target = parseFloat(el.dataset.count || "0");
    const suffix = el.dataset.suffix || "";
    const decimals = (el.dataset.count || "").includes(".") ? 1 : 0;
    if (reduce) { el.textContent = target.toFixed(decimals) + suffix; return; }
    const dur = 1300;
    const t0 = performance.now();
    const tick = (now) => {
      const p = Math.min((now - t0) / dur, 1);
      const eased = 1 - Math.pow(1 - p, 3);
      el.textContent = (target * eased).toFixed(decimals) + suffix;
      if (p < 1) requestAnimationFrame(tick);
      else el.textContent = target.toFixed(decimals) + suffix;
    };
    requestAnimationFrame(tick);
  };
  if ("IntersectionObserver" in window) {
    const sio = new IntersectionObserver((entries) => {
      entries.forEach((e) => { if (e.isIntersecting) { runCount(e.target); sio.unobserve(e.target); } });
    }, { threshold: 0.6 });
    stats.forEach((s) => sio.observe(s));
  } else {
    stats.forEach(runCount);
  }

  /* magnetic buttons -------------------------------------------- */
  if (!reduce && window.matchMedia("(pointer: fine)").matches) {
    document.querySelectorAll(".magnetic").forEach((el) => {
      const strength = 0.28;
      el.addEventListener("mousemove", (ev) => {
        const r = el.getBoundingClientRect();
        const dx = ev.clientX - (r.left + r.width / 2);
        const dy = ev.clientY - (r.top + r.height / 2);
        el.style.transform = `translate(${dx * strength}px, ${dy * strength}px)`;
      });
      el.addEventListener("mouseleave", () => { el.style.transform = ""; });
    });
  }

  /* halftone hero ----------------------------------------------- */
  const canvas = document.getElementById("halftone");
  if (canvas && !reduce) initHalftone(canvas);
  else if (canvas) canvas.style.display = "none";

  function initHalftone(cv) {
    const ctx = cv.getContext("2d");
    let dpr, W, H, cols, rows, gap, dotMax, t = 0;
    const pointer = { x: 0.5, y: 0.42, active: false };

    function resize() {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      const r = cv.getBoundingClientRect();
      W = r.width; H = r.height;
      cv.width = W * dpr; cv.height = H * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      // denser dots on large screens, coarser on phones, matches the mark's grain
      gap = W < 620 ? 22 : W < 1100 ? 26 : 30;
      cols = Math.ceil(W / gap) + 1;
      rows = Math.ceil(H / gap) + 1;
      dotMax = gap * 0.42;
    }

    // A soft "light" drifts across the field; dot size/opacity follow it plus
    // the pointer, reproducing the logo's bright-core-to-dark fade, animated.
    function frame() {
      t += 0.006;
      ctx.clearRect(0, 0, W, H);
      const lx = 0.72 + Math.cos(t * 0.7) * 0.14;
      const ly = 0.4 + Math.sin(t * 0.9) * 0.12;
      const px = pointer.x, py = pointer.y;

      // How bright the ambient drifting-light field is allowed to get. The
      // pointer halo is kept separate and at full strength, so lowering this
      // dims the background dots without touching the mouse-follow glow.
      const AMBIENT = 0.6;
      for (let j = 0; j < rows; j++) {
        for (let i = 0; i < cols; i++) {
          const x = i * gap, y = j * gap;
          const nx = x / W, ny = y / H;
          // ambient field from the drifting light (+ subtle shimmer)
          const d = Math.hypot(nx - lx, (ny - ly) * (H / W));
          let a = 1 - smooth(0.08, 0.62, d);
          a += Math.sin((i + j) * 0.5 + t * 2.2) * 0.03;
          a = Math.max(0, Math.min(1, a));
          // pointer halo, left exactly as before (the mouse glow stays bright)
          let pHalo = 0;
          if (pointer.active) {
            const dp = Math.hypot(nx - px, (ny - py) * (H / W));
            pHalo = (1 - smooth(0.0, 0.22, dp)) * 0.6;
          }
          // geometry: size still driven by both, so the field keeps its shape
          const v = Math.min(1, a + pHalo);
          if (v < 0.04) continue;
          const rad = v * dotMax;
          // brightness: dim the ambient white, keep the pointer's punch intact
          const alpha = Math.min(1, 0.03 + a * 0.9 * AMBIENT + pHalo * 0.9);
          ctx.beginPath();
          ctx.arc(x, y, rad, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(255,255,255,${alpha})`;
          ctx.fill();
        }
      }
      raf = requestAnimationFrame(frame);
    }

    function smooth(a, b, x) {
      const t2 = Math.max(0, Math.min(1, (x - a) / (b - a)));
      return t2 * t2 * (3 - 2 * t2);
    }

    let raf;
    window.addEventListener("resize", resize);
    window.addEventListener("pointermove", (e) => {
      const r = cv.getBoundingClientRect();
      pointer.x = (e.clientX - r.left) / r.width;
      pointer.y = (e.clientY - r.top) / r.height;
      pointer.active = true;
    });
    window.addEventListener("pointerleave", () => { pointer.active = false; });
    // pause when the hero scrolls out of view (save the battery)
    const vis = new IntersectionObserver((es) => {
      es.forEach((e) => {
        if (e.isIntersecting) { if (!raf) raf = requestAnimationFrame(frame); }
        else if (raf) { cancelAnimationFrame(raf); raf = null; }
      });
    }, { threshold: 0 });
    vis.observe(cv);

    resize();
    raf = requestAnimationFrame(frame);
  }
})();

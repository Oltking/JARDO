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
      const AMBIENT = 0.3;
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
          const alpha = Math.min(1, 0.04 + a * 0.9 * AMBIENT + pHalo * 0.9);
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

/* Live app scene: Jardo listens, speaks, opens a terminal, and supervises Claude
   in it, with the avatar reacting and chat bubbles fading in/out. Loops in view. */
(() => {
  "use strict";
  const scene = document.getElementById("scene");
  const avatarEl = document.getElementById("sceneAvatar");
  const stateEl = document.getElementById("sceneState");
  const chatEl = document.getElementById("sceneChat");
  const termWin = document.getElementById("sceneTerm");
  const termBody = document.getElementById("sceneTermBody");
  if (!scene || !avatarEl || !chatEl || !termBody) return;
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---- halftone avatar reacting to state ----
  const ctx = avatarEl.getContext("2d");
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const S = 128;
  avatarEl.width = S * dpr; avatarEl.height = S * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  let state = "listening";
  const PARAMS = {
    listening: { speed: 0.07, amp: 0.42, base: 0.66, tint: [255, 255, 255] },
    speaking: { speed: 0.11, amp: 0.5, base: 0.62, tint: [255, 255, 255] },
    watching: { speed: 0.03, amp: 0.18, base: 0.5, tint: [255, 255, 255] },
    approve: { speed: 0.09, amp: 0.5, base: 0.7, tint: [143, 214, 173] },
    decline: { speed: 0.09, amp: 0.5, base: 0.7, tint: [230, 162, 162] },
    idle: { speed: 0.02, amp: 0.14, base: 0.46, tint: [255, 255, 255] },
  };
  const smooth = (a, b, x) => { const t = Math.max(0, Math.min(1, (x - a) / (b - a))); return t * t * (3 - 2 * t); };
  let t = 0, raf = 0;
  function draw() {
    const p = PARAMS[state] || PARAMS.idle;
    t += p.speed;
    ctx.clearRect(0, 0, S, S);
    const cx = S / 2, cy = S / 2, R = S / 2, gap = 9, dotMax = gap * 0.42;
    const pulse = Math.sin(t) * 0.5 + 0.5;
    const [cr, cg, cb] = p.tint;
    for (let y = gap / 2; y < S; y += gap) {
      for (let x = gap / 2; x < S; x += gap) {
        const nd = Math.hypot(x - cx, y - cy) / R;
        if (nd > 1) continue;
        const ring = 1 - Math.abs(nd - pulse * 0.7);
        let v = p.base * (1 - nd * 0.5) + p.amp * Math.max(0, ring);
        v *= 1 - smooth(0.82, 1, nd);
        v = Math.max(0, Math.min(1, v));
        if (v < 0.05) continue;
        ctx.beginPath(); ctx.arc(x, y, v * dotMax, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${cr},${cg},${cb},${0.08 + v * 0.9})`; ctx.fill();
      }
    }
    if (!reduce) raf = requestAnimationFrame(draw);
  }

  // ---- helpers ----
  const sleep = (ms) => new Promise((r) => setTimeout(r, reduce ? ms / 3 : ms));
  function setState(label, cls) {
    state = cls || label;
    if (stateEl) { stateEl.textContent = label; stateEl.className = "app__state" + (cls === "approve" || cls === "decline" ? " " + cls : ""); }
  }
  function chat(who, text) {
    const b = document.createElement("div");
    b.className = `cbub ${who}`; b.textContent = text;
    chatEl.appendChild(b);
    while (chatEl.children.length > 3) {
      const old = chatEl.firstChild; old.classList.add("out");
      setTimeout(() => old.remove(), 500);
      if (chatEl.children.length > 4) chatEl.firstChild.remove();
      break;
    }
  }
  const clearChat = () => { chatEl.innerHTML = ""; };
  const openTerm = () => termWin && termWin.classList.add("is-open");
  const closeTerm = () => termWin && termWin.classList.remove("is-open");
  function line(html) {
    const l = document.createElement("span");
    l.className = "term__line"; l.innerHTML = html;
    termBody.appendChild(l);
    while (termBody.children.length > 9) termBody.firstChild.remove();
  }
  const termClear = () => { termBody.innerHTML = ""; };

  // ---- choreography ----
  let running = false;
  async function run() {
    while (running) {
      clearChat(); termClear(); closeTerm(); setState("listening", "listening");
      await sleep(1200);
      chat("you", "hey jardo, build me a landing page with claude");
      await sleep(1400);
      setState("speaking", "speaking");
      chat("jardo", "On it. Opening your terminal and starting Claude.");
      await sleep(1600);
      openTerm(); setState("supervising claude", "watching");
      await sleep(700);
      line('<span class="muted">$</span> claude "build a bakery landing page"');
      await sleep(900);
      line('<span class="muted">●</span> Bash(npm create vite@latest bakery-site)');
      await sleep(700);
      line('<span class="prompt">Do you want to proceed? 1) Yes  2) No</span>');
      await sleep(700);
      setState("approved", "approve");
      chat("jardo", "Approved. Safe and on-task.");
      line('jardo <span class="term__verdict ok">✓ approved</span>');
      await sleep(1300); setState("supervising claude", "watching");
      line('<span class="muted">●</span> Write index.html, styles.css');
      await sleep(700);
      line('<span class="prompt">Proceed? 1) Yes  2) No</span>');
      await sleep(600);
      line('jardo <span class="term__verdict ok">✓ approved</span>');
      await sleep(1100);
      line('<span class="muted">●</span> Bash(rm -rf ~/Documents)');
      await sleep(700);
      line('<span class="prompt">Proceed? 1) Yes  2) No</span>');
      await sleep(700);
      setState("declined", "decline");
      chat("jardo", "Declined. Destructive and off-goal, told Claude to continue safely.");
      line('jardo <span class="term__verdict no">✗ declined</span>');
      await sleep(1800); setState("supervising claude", "watching");
      chat("you", "where am i?");
      await sleep(1200);
      setState("speaking", "speaking");
      chat("jardo", "Goal: bakery landing page. 4 files written, dev server live. Nothing needs you.");
      await sleep(4200);
    }
  }

  function start() { if (running) return; running = true; if (!reduce) raf = requestAnimationFrame(draw); else draw(); run(); }
  function stop() { running = false; if (raf) cancelAnimationFrame(raf), (raf = 0); }

  if ("IntersectionObserver" in window) {
    const io = new IntersectionObserver((es) => es.forEach((e) => (e.isIntersecting ? start() : stop())), { threshold: 0.25 });
    io.observe(scene);
  } else start();
})();

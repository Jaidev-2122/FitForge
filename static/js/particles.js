/* FitForge particles — visible dust swirling in slow orbital drift.
   Canvas-based for smoothness; respects prefers-reduced-motion. */
(function () {
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const host = document.querySelector(".bg-layer");
  if (!host) return; // only render on the waves background mode

  const canvas = document.createElement("canvas");
  canvas.style.cssText = "position:absolute;inset:0;width:100%;height:100%;";
  host.appendChild(canvas);
  const ctx = canvas.getContext("2d");

  let W, H, particles = [];
  const COUNT = Math.min(70, Math.floor(window.innerWidth / 18));

  function accent(n) {
    return getComputedStyle(document.documentElement)
      .getPropertyValue(n).trim() || "#c8f55a";
  }

  function resize() {
    W = canvas.width = window.innerWidth;
    H = canvas.height = window.innerHeight;
  }
  window.addEventListener("resize", resize);
  resize();

  function spawn() {
    const a1 = accent("--accent-1"), a2 = accent("--accent-2");
    particles = Array.from({ length: COUNT }, () => ({
      x: Math.random() * W,
      y: Math.random() * H,
      r: 0.6 + Math.random() * 2.2,          // radius
      baseA: 0.15 + Math.random() * 0.45,    // base alpha
      tw: Math.random() * Math.PI * 2,       // twinkle phase
      twS: 0.005 + Math.random() * 0.015,    // twinkle speed
      angle: Math.random() * Math.PI * 2,    // drift direction
      speed: 0.08 + Math.random() * 0.25,    // drift speed
      swirl: (Math.random() - 0.5) * 0.002,  // slow rotation of direction = swirling
      color: Math.random() < 0.6 ? a1 : a2,
    }));
  }
  spawn();

  // re-tint when the user changes theme colors live
  new MutationObserver(spawn).observe(document.documentElement,
    { attributes: true, attributeFilter: ["style", "data-theme"] });

  function tick() {
    ctx.clearRect(0, 0, W, H);
    for (const p of particles) {
      // swirl: direction slowly rotates, giving orbital drifting paths
      p.angle += p.swirl;
      p.x += Math.cos(p.angle) * p.speed;
      p.y += Math.sin(p.angle) * p.speed;
      // wrap around edges
      if (p.x < -10) p.x = W + 10; if (p.x > W + 10) p.x = -10;
      if (p.y < -10) p.y = H + 10; if (p.y > H + 10) p.y = -10;
      // twinkle
      p.tw += p.twS;
      const alpha = p.baseA * (0.55 + 0.45 * Math.sin(p.tw));
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fillStyle = p.color;
      ctx.globalAlpha = alpha;
      ctx.fill();
      // soft glow for the larger ones
      if (p.r > 1.8) {
        ctx.globalAlpha = alpha * 0.25;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r * 3, 0, Math.PI * 2);
        ctx.fill();
      }
    }
    ctx.globalAlpha = 1;
    requestAnimationFrame(tick);
  }
  // pause when tab hidden (battery-friendly)
  let running = true;
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) running = false;
    else if (!running) { running = true; tick(); }
  });
  tick();
})();

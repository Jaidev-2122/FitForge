/* FitForge music — floating ♪ toggle.
   Default: a soft generated ambient pad (Web Audio — royalty-free by
   construction, no external file). If the user set a custom URL in
   Settings, that plays instead (looped <audio>). Browsers block autoplay,
   so playback always starts from a user tap on the button. */
(function () {
  const btn = document.getElementById("music-toggle");
  if (!btn) return;

  const customUrl = btn.dataset.url || "";
  const startOn = btn.dataset.enabled === "true";

  let audioEl = null;      // for custom URL mode
  let actx = null, nodes = null; // for generated ambient mode
  let playing = false;

  /* ---- generated ambient pad: two detuned sines + slow filter sweep ---- */
  function startAmbient() {
    actx = new (window.AudioContext || window.webkitAudioContext)();
    const master = actx.createGain();
    master.gain.value = 0.0;
    master.connect(actx.destination);

    const filter = actx.createBiquadFilter();
    filter.type = "lowpass";
    filter.frequency.value = 600;
    filter.connect(master);

    // chord: A2, E3, A3 with gentle detune for movement
    const freqs = [110, 164.81, 220, 110.5];
    const oscs = freqs.map(f => {
      const o = actx.createOscillator();
      o.type = "sine";
      o.frequency.value = f;
      const g = actx.createGain();
      g.gain.value = 0.06;
      o.connect(g); g.connect(filter);
      o.start();
      return o;
    });

    // slow LFO sweeping the filter = breathing texture
    const lfo = actx.createOscillator();
    lfo.frequency.value = 0.05;
    const lfoGain = actx.createGain();
    lfoGain.gain.value = 250;
    lfo.connect(lfoGain); lfoGain.connect(filter.frequency);
    lfo.start();

    // fade in gently
    master.gain.linearRampToValueAtTime(0.5, actx.currentTime + 3);
    nodes = { master, oscs, lfo };
  }

  function stopAmbient() {
    if (!actx) return;
    nodes.master.gain.linearRampToValueAtTime(0, actx.currentTime + 1);
    setTimeout(() => { try { actx.close(); } catch (_) {} actx = null; nodes = null; }, 1200);
  }

  /* ---- custom URL mode ---- */
  function startUrl() {
    audioEl = new Audio(customUrl);
    audioEl.loop = true;
    audioEl.volume = 0.5;
    audioEl.play().catch(() => {
      btn.title = "Couldn't play that audio URL — check it in Settings";
      setOff();
    });
  }
  function stopUrl() {
    if (audioEl) { audioEl.pause(); audioEl = null; }
  }

  function setOn() {
    playing = true;
    btn.classList.add("playing");
    btn.textContent = "♪";
    customUrl ? startUrl() : startAmbient();
  }
  function setOff() {
    playing = false;
    btn.classList.remove("playing");
    btn.textContent = "♪";
    customUrl ? stopUrl() : stopAmbient();
  }

  btn.addEventListener("click", () => playing ? setOff() : setOn());

  // If the user enabled music in settings, hint it (pulse) — can't autoplay.
  if (startOn) btn.classList.add("hint");
})();

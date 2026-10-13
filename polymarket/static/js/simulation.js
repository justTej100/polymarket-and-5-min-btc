(function () {
  "use strict";

  var PLAYBACK_INTERVAL_MS = 150;
  var payload = null;
  var tickIndex = 0;
  var playing = false;
  var timer = null;

  function el(id) {
    return document.getElementById(id);
  }

  function stopTimer() {
    if (timer) {
      clearInterval(timer);
      timer = null;
    }
  }

  function applyFrame() {
    if (!payload) return;
    var snapshot = payload.snapshots[tickIndex];
    var history = payload.snapshots.slice(0, tickIndex + 1);
    var tick = payload.ticks[tickIndex] || { signals: [] };
    Board.applySimulationFrame(snapshot, history, tick.signals);

    el("sim-label").textContent =
      "tick " + (tickIndex + 1) + " / " + payload.snapshots.length;
    el("sim-scrub").value = String(tickIndex);
    el("sim-scrub").max = String(Math.max(payload.snapshots.length - 1, 0));

    var source = el("sim-source");
    if (payload.source === "synthetic") {
      source.hidden = false;
      source.textContent = "synthetic demo data";
    } else {
      source.hidden = false;
      source.textContent = "historical window";
    }
  }

  function setPlaying(next) {
    playing = next;
    el("sim-play").textContent = playing ? "Pause" : "Play";
    stopTimer();
    if (playing && payload) {
      timer = setInterval(function () {
        if (tickIndex + 1 >= payload.snapshots.length) {
          setPlaying(false);
          return;
        }
        tickIndex += 1;
        applyFrame();
      }, PLAYBACK_INTERVAL_MS);
    }
  }

  async function loadWindow() {
    setPlaying(false);
    tickIndex = 0;
    el("sim-label").textContent = "loading…";
    el("sim-play").disabled = true;
    el("sim-new").disabled = true;

    try {
      var res = await fetch("/api/backtest");
      payload = await res.json();
      if (payload.error) throw new Error(payload.error);
      el("sim-play").disabled = false;
      el("sim-new").disabled = false;
      applyFrame();
    } catch (err) {
      el("sim-label").textContent = "failed to load window";
      el("sim-new").disabled = false;
      console.error(err);
    }
  }

  Board.init({ features: ["market", "chart", "spatial", "strategies"] });

  el("sim-play").addEventListener("click", function () {
    if (!payload) return;
    setPlaying(!playing);
  });

  el("sim-new").addEventListener("click", loadWindow);

  el("sim-scrub").addEventListener("input", function (event) {
    setPlaying(false);
    tickIndex = Number(event.target.value) || 0;
    applyFrame();
  });

  loadWindow();
})();

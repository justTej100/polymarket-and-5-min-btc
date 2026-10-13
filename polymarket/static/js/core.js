/*
  Shared dashboard helpers. Pages call Board.init({ features: [...] }).
  Features: market, chart, spatial, strategies, leaderboard, copy, live
*/
(function (global) {
  "use strict";

  var HISTORY_LIMIT = 400;
  var HISTORY_MIN_GAP_MS = 900;
  var UP_COLOR = "#22c55e";
  var DOWN_COLOR = "#ef4444";
  var BOARD_HEIGHT = 340;
  var BASELINE_Y = BOARD_HEIGHT / 2;
  var ZONE_PADDING = 28;

  var state = {
    history: [],
    conditionId: null,
    latest: null,
    paper: null,
    copy: null,
    signals: [],
    expandedId: null,
    sortKey: "cash",
    positionedOnly: false,
    confirmingCopy: false,
    stakeDirty: false,
    features: {},
    socket: null,
    reconnectDelay: 1000,
    chart: null,
    series: null,
    strikeLine: null,
    strikeOnChart: null,
    lastBarTime: null,
  };

  function el(id) {
    return document.getElementById(id);
  }

  function has(id) {
    return !!el(id);
  }

  function money(value, signed) {
    var sign = signed ? (value > 0 ? "+" : value < 0 ? "\u2212" : "") : "";
    return (
      sign +
      "$" +
      Math.abs(value).toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })
    );
  }

  function price(value) {
    return value.toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }

  function cents(value) {
    if (value === undefined || value === null || !isFinite(value)) return "\u2014";
    return (value * 100).toFixed(1) + "\u00a2";
  }

  function clockTime(timestamp) {
    return new Intl.DateTimeFormat(undefined, {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    }).format(new Date(timestamp));
  }

  function pnlClass(value) {
    if (value > 0) return "paper__pnl paper__pnl--pos";
    if (value < 0) return "paper__pnl paper__pnl--neg";
    return "paper__pnl";
  }

  function actionFor(direction, hasPosition) {
    if (direction === "YES") return { label: "BUY UP", modifier: "yes" };
    if (direction === "NO") return { label: "BUY DOWN", modifier: "no" };
    if (direction === "BOTH") return { label: "BUY BOTH", modifier: "both" };
    return hasPosition
      ? { label: "EXIT", modifier: "exit" }
      : { label: "HOLD", modifier: "neutral" };
  }

  function standingFor(strategyId) {
    if (!state.paper) return null;
    for (var i = 0; i < state.paper.standings.length; i++) {
      if (state.paper.standings[i].strategyId === strategyId) return state.paper.standings[i];
    }
    return null;
  }

  // ---- market status ------------------------------------------------------

  function renderStatus(connected) {
    if (!has("status-dot")) return;
    var dot = el("status-dot");
    dot.className =
      "status-dot " +
      (connected
        ? "status-dot--live"
        : state.latest
          ? "status-dot--down"
          : "status-dot--pending");

    if (!state.latest) {
      el("market-label").textContent = connected
        ? "Waiting for live market data\u2026"
        : "Disconnected \u2014 retrying\u2026";
      return;
    }

    var latest = state.latest;
    el("market-label").textContent = latest.question || "Bitcoin Up or Down \u2014 5 min";
    el("meta-strike").textContent =
      "Strike $" + price(latest.priceToBeat) + (latest.priceToBeatPending ? "*" : "");

    var minutes = Math.floor(latest.secondsRemaining / 60);
    var seconds = latest.secondsRemaining % 60;
    var clock = el("meta-clock");
    clock.textContent = minutes + ":" + String(seconds).padStart(2, "0") + " left";
    clock.className =
      "market-embed__meta-item" +
      (latest.secondsRemaining <= 30 ? " market-embed__meta-item--urgent" : "");

    var upBuy = latest.upAsk != null ? latest.upAsk : latest.yesPrice;
    var upSell = latest.upBid != null ? latest.upBid : latest.yesPrice;
    var downBuy = latest.downAsk != null ? latest.downAsk : latest.noPrice;
    var downSell = latest.downBid != null ? latest.downBid : latest.noPrice;

    el("up-chance").textContent = (latest.yesPrice * 100).toFixed(0) + "%";
    el("down-chance").textContent = (latest.noPrice * 100).toFixed(0) + "%";
    el("up-buy").textContent = cents(upBuy);
    el("up-sell").textContent = cents(upSell);
    el("down-buy").textContent = cents(downBuy);
    el("down-sell").textContent = cents(downSell);

    el("card-up").className =
      "outcome-card outcome-card--up" +
      (latest.yesPrice >= latest.noPrice ? " outcome-card--leading" : "");
    el("card-down").className =
      "outcome-card outcome-card--down" +
      (latest.noPrice > latest.yesPrice ? " outcome-card--leading" : "");

    if (has("stat-price")) {
      var prices = state.history.map(function (s) {
        return s.currentPrice;
      });
      el("stat-price").textContent = "$" + price(latest.currentPrice);
      el("stat-strike").textContent = "$" + price(latest.priceToBeat);
      el("stat-high").textContent = prices.length
        ? "$" + price(Math.max.apply(null, prices))
        : "\u2014";
      el("stat-low").textContent = prices.length
        ? "$" + price(Math.min.apply(null, prices))
        : "\u2014";
    }
  }

  // ---- chart --------------------------------------------------------------

  function initChart() {
    if (state.chart || typeof LightweightCharts === "undefined" || !has("chart")) return;

    state.chart = LightweightCharts.createChart(el("chart"), {
      layout: {
        background: { type: "solid", color: "transparent" },
        textColor: "#8b93a1",
        fontFamily: 'ui-monospace, "SF Mono", Menlo, Consolas, monospace',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "rgba(255,255,255,0.04)" },
        horzLines: { color: "rgba(255,255,255,0.06)" },
      },
      rightPriceScale: { borderColor: "rgba(255,255,255,0.08)" },
      timeScale: {
        borderColor: "rgba(255,255,255,0.08)",
        timeVisible: true,
        secondsVisible: true,
      },
      crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
      handleScale: false,
      handleScroll: false,
    });

    state.series = state.chart.addBaselineSeries({
      baseValue: { type: "price", price: 0 },
      topLineColor: UP_COLOR,
      topFillColor1: "rgba(34,197,94,0.28)",
      topFillColor2: "rgba(34,197,94,0.03)",
      bottomLineColor: DOWN_COLOR,
      bottomFillColor1: "rgba(239,68,68,0.03)",
      bottomFillColor2: "rgba(239,68,68,0.28)",
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
    });

    window.addEventListener("resize", function () {
      if (state.chart && has("chart")) {
        state.chart.applyOptions({ width: el("chart").clientWidth });
      }
    });
  }

  function toBars(snapshots) {
    var bars = [];
    var seen = null;
    for (var i = 0; i < snapshots.length; i++) {
      var time = Math.floor(snapshots[i].timestamp / 1000);
      var point = { time: time, value: snapshots[i].currentPrice };
      if (time === seen) bars[bars.length - 1] = point;
      else {
        bars.push(point);
        seen = time;
      }
    }
    return bars;
  }

  function setStrike(strike) {
    if (state.strikeOnChart === strike) return;
    state.strikeOnChart = strike;
    state.series.applyOptions({ baseValue: { type: "price", price: strike } });
    if (state.strikeLine) state.series.removePriceLine(state.strikeLine);
    state.strikeLine = state.series.createPriceLine({
      price: strike,
      color: "rgba(255,255,255,0.45)",
      lineWidth: 1,
      lineStyle: LightweightCharts.LineStyle.Dashed,
      axisLabelVisible: true,
      title: "price to beat",
    });
  }

  function renderChart(isFullHistory) {
    if (!state.features.chart) return;
    initChart();
    if (!state.series || !state.latest) return;

    setStrike(state.latest.priceToBeat);

    if (isFullHistory) {
      var bars = toBars(state.history);
      state.series.setData(bars);
      state.lastBarTime = bars.length ? bars[bars.length - 1].time : null;
      state.chart.timeScale().fitContent();
    } else {
      var time = Math.floor(state.latest.timestamp / 1000);
      if (state.lastBarTime === null || time >= state.lastBarTime) {
        state.series.update({ time: time, value: state.latest.currentPrice });
        state.lastBarTime = time;
      }
    }

    var aboveStrike = state.latest.currentPrice >= state.latest.priceToBeat;
    var liveColor = aboveStrike ? UP_COLOR : DOWN_COLOR;
    var changePct =
      ((state.latest.currentPrice - state.latest.priceToBeat) / state.latest.priceToBeat) * 100;

    if (has("chart-price")) {
      var value = el("chart-price");
      value.textContent = "$" + price(state.latest.currentPrice);
      value.style.color = liveColor;

      var delta = el("chart-delta");
      delta.textContent =
        (changePct >= 0 ? "\u25b2" : "\u25bc") +
        " " +
        Math.abs(changePct).toFixed(3) +
        "% vs strike";
      delta.style.color = liveColor;

      if (state.history.length) {
        el("chart-range").textContent =
          clockTime(state.history[0].timestamp) +
          " \u2013 " +
          clockTime(state.latest.timestamp);
        el("chart-open").textContent = "open $" + price(state.history[0].currentPrice);
      }
      el("chart-strike").textContent =
        "strike $" +
        price(state.latest.priceToBeat) +
        (state.latest.priceToBeatPending ? " (provisional)" : "");

      var verdict = el("chart-verdict");
      verdict.textContent =
        (aboveStrike ? "UP " : "DOWN ") +
        (changePct >= 0 ? "+" : "") +
        changePct.toFixed(3) +
        "%";
      verdict.style.color = liveColor;
    }
  }

  // ---- spatial board ------------------------------------------------------

  function verticalOffset(direction, confidence) {
    var maxTravel = BASELINE_Y - ZONE_PADDING;
    var travel = confidence * maxTravel;
    if (direction === "YES") return -travel;
    if (direction === "NO") return travel;
    return 0;
  }

  function displayDirection(direction) {
    return direction === "NEUTRAL" ? "NO DECISION" : direction;
  }

  function renderSpatialBoard(signals) {
    if (!state.features.spatial || !has("spatial-board")) return;
    var list = signals || state.signals;
    var container = el("spatial-board");
    container.textContent = "";

    var zoneYes = document.createElement("div");
    zoneYes.className = "board__zone board__zone--yes";
    var yesLabel = document.createElement("span");
    yesLabel.className = "board__zone-label";
    yesLabel.textContent = "UP / YES";
    zoneYes.appendChild(yesLabel);

    var zoneNo = document.createElement("div");
    zoneNo.className = "board__zone board__zone--no";
    var noLabel = document.createElement("span");
    noLabel.className = "board__zone-label";
    noLabel.textContent = "DOWN / NO";
    zoneNo.appendChild(noLabel);

    var baseline = document.createElement("div");
    baseline.className = "board__baseline";

    var boxes = document.createElement("div");
    boxes.className = "board__boxes";
    boxes.style.height = BOARD_HEIGHT + "px";

    list.forEach(function (s, i) {
      var direction = s.signal.direction;
      var confidence = s.signal.confidence;
      var offset = verticalOffset(direction, confidence);
      var leftPercent = ((i + 0.5) / Math.max(list.length, 1)) * 100;

      var box = document.createElement("div");
      box.className = "board__box board__box--" + direction.toLowerCase();
      box.style.left = leftPercent + "%";
      box.style.top = BASELINE_Y + offset + "px";
      box.title = s.signal.note || "";

      var name = document.createElement("span");
      name.className = "board__box-name";
      name.textContent = s.name;

      var dir = document.createElement("span");
      dir.className = "board__box-dir";
      dir.textContent = displayDirection(direction);

      box.appendChild(name);
      box.appendChild(dir);
      boxes.appendChild(box);
    });

    container.appendChild(zoneYes);
    container.appendChild(zoneNo);
    container.appendChild(baseline);
    container.appendChild(boxes);
  }

  // ---- strategy explainer -------------------------------------------------

  function renderStrategies(signals) {
    if (!state.features.strategies || !has("strategies")) return;
    var list = signals || state.signals;
    var container = el("strategies");
    container.textContent = "";

    list.forEach(function (entry) {
      var standing = standingFor(entry.id);
      var hasPosition = !!(standing && standing.openPositions.length);
      var action = actionFor(entry.signal.direction, hasPosition);

      var row = document.createElement("div");
      row.className = "explainer__row explainer__row--" + entry.signal.direction.toLowerCase();

      var header = document.createElement("div");
      header.className = "explainer__row-header";

      var name = document.createElement("span");
      name.className = "explainer__name";
      name.textContent = entry.name;

      var badge = document.createElement("span");
      badge.className = "explainer__badge explainer__badge--" + action.modifier;
      badge.textContent = action.label;

      header.appendChild(name);
      header.appendChild(badge);

      var description = document.createElement("p");
      description.className = "explainer__description";
      description.textContent = entry.description;

      var note = document.createElement("p");
      note.className = "explainer__note";
      note.textContent = entry.signal.note;

      row.appendChild(header);
      row.appendChild(description);
      row.appendChild(note);

      if (standing) {
        var pnl = document.createElement("div");
        pnl.className = "explainer__pnl";
        var label = document.createElement("span");
        label.textContent = "P&L " + standing.wins + "W / " + standing.losses + "L";
        var amount = document.createElement("span");
        amount.className = "explainer__pnl-value " + pnlClass(standing.totalPnl);
        amount.textContent = money(standing.totalPnl, true);
        pnl.appendChild(label);
        pnl.appendChild(amount);
        row.appendChild(pnl);
      }

      container.appendChild(row);
    });

    if (has("strategy-count")) {
      el("strategy-count").textContent =
        list.length + " strategy books, re-evaluated on every tick";
    }
  }

  // ---- leaderboard --------------------------------------------------------

  var COLUMNS = [
    { label: "#", tip: "Rank by cash \u2014 #1 has the most actual dollars in hand right now." },
    {
      label: "Strategy",
      tip: "Which rule-based strategy this row is. Click a row to expand its full trade history.",
    },
    {
      label: "Cash",
      tip: "Regular dollars, starts at $1,000. Goes down when the strategy buys, up when it sells or a win pays out.",
    },
    {
      label: "This window",
      tip: "Cashed-in profit or loss during the current 5-minute market.",
    },
    {
      label: "Total P&L",
      tip: "All-time cashed-in profit or loss this session.",
    },
    {
      label: "W / L",
      tip: "Windows won / lost.",
    },
    {
      label: "Position",
      tip: "Money currently in play.",
    },
  ];

  var ACTION_LABEL = { BUY: "bought", SELL: "sold", WIN: "won", LOSS: "lost" };

  function sortedStandings() {
    var rows = state.paper.standings.slice();
    rows.sort(function (a, b) {
      if (state.sortKey === "cash") return b.bankroll - a.bankroll;
      if (state.sortKey === "wins") return b.wins - a.wins;
      return b[state.sortKey] - a[state.sortKey];
    });
    if (state.positionedOnly) {
      rows = rows.filter(function (row) {
        return row.openPositions.length > 0;
      });
    }
    return rows;
  }

  function headerRow() {
    var head = document.createElement("div");
    head.className = "paper__row paper__row--head";
    COLUMNS.forEach(function (col) {
      var cell = document.createElement("span");
      cell.className = "paper__col-head";
      cell.tabIndex = 0;
      cell.appendChild(document.createTextNode(col.label));
      var tip = document.createElement("span");
      tip.className = "paper__col-tip";
      tip.setAttribute("role", "tooltip");
      tip.textContent = col.tip;
      cell.appendChild(tip);
      head.appendChild(cell);
    });
    return head;
  }

  function tradeRow(trade) {
    var row = document.createElement("div");
    row.className = "paper__trade";

    var time = document.createElement("span");
    time.className = "paper__trade-time";
    time.textContent = clockTime(trade.timestamp);

    var action = document.createElement("span");
    action.className = "paper__trade-action paper__trade-action--" + trade.action.toLowerCase();
    action.textContent = ACTION_LABEL[trade.action] || trade.action;

    var side = document.createElement("span");
    side.className = "paper__trade-side paper__trade-side--" + trade.side.toLowerCase();
    side.textContent = trade.side;

    var fill = document.createElement("span");
    fill.className = "paper__trade-fill";
    fill.textContent =
      trade.shares.toFixed(1) +
      " shares @ " +
      (trade.price * 100).toFixed(1) +
      "\u00a2 = " +
      money(trade.amountUsd);

    var note = document.createElement("span");
    note.className = "paper__trade-note";
    note.textContent = trade.note;

    row.appendChild(time);
    row.appendChild(action);
    row.appendChild(side);
    row.appendChild(fill);
    row.appendChild(note);
    return row;
  }

  function renderLeaderboard() {
    if (!state.features.leaderboard || !state.paper || !has("leaderboard")) return;

    if (has("paper-subtitle")) {
      el("paper-subtitle").textContent =
        "every strategy trades $" +
        state.paper.startingBankroll.toLocaleString() +
        " of imaginary money \u00b7 hover a column for what it means";
    }

    var lastWindow = state.paper.windows[0] || null;
    var lastWindowEl = el("last-window");
    if (lastWindowEl) {
      if (lastWindow) {
        lastWindowEl.hidden = false;
        lastWindowEl.textContent = "";
        var outcome = document.createElement("span");
        outcome.className = "paper__outcome paper__outcome--" + lastWindow.outcome.toLowerCase();
        outcome.textContent = lastWindow.outcome;
        var text = document.createElement("span");
        text.className = "paper__last-window-text";
        var top = lastWindow.results[0];
        text.appendChild(
          document.createTextNode("Last window resolved " + lastWindow.outcome + " \u2014 ")
        );
        var strong = document.createElement("strong");
        strong.textContent = top ? top.strategyName : "nobody";
        text.appendChild(strong);
        text.appendChild(
          document.createTextNode(" made the most: " + money(top ? top.pnlUsd : 0, true))
        );
        var time = document.createElement("span");
        time.className = "paper__last-window-time";
        time.textContent = clockTime(lastWindow.closedAt);
        lastWindowEl.appendChild(outcome);
        lastWindowEl.appendChild(text);
        lastWindowEl.appendChild(time);
      } else {
        lastWindowEl.hidden = true;
      }
    }

    var table = el("leaderboard");
    table.textContent = "";
    table.appendChild(headerRow());

    sortedStandings().forEach(function (row, index) {
      var expanded = state.expandedId === row.strategyId;
      var button = document.createElement("button");
      button.type = "button";
      button.className = "paper__row" + (expanded ? " paper__row--expanded" : "");
      button.setAttribute("aria-expanded", expanded ? "true" : "false");
      button.addEventListener("click", function () {
        state.expandedId = expanded ? null : row.strategyId;
        renderLeaderboard();
      });

      var rank = document.createElement("span");
      rank.className = "paper__rank";
      rank.textContent =
        index === 0 && state.sortKey === "cash" ? "\ud83c\udfc6" : String(index + 1);

      var name = document.createElement("span");
      name.className = "paper__name";
      name.textContent = row.strategyName;

      var cash = document.createElement("span");
      cash.className = "paper__equity";
      cash.textContent = money(row.bankroll);

      var windowPnl = document.createElement("span");
      windowPnl.className = pnlClass(row.windowPnl);
      windowPnl.textContent = money(row.windowPnl, true);

      var totalPnl = document.createElement("span");
      totalPnl.className = pnlClass(row.totalPnl);
      totalPnl.textContent = money(row.totalPnl, true);

      var wl = document.createElement("span");
      wl.className = "paper__wl";
      var w = document.createElement("span");
      w.className = "paper__wl-w";
      w.textContent = String(row.wins);
      var l = document.createElement("span");
      l.className = "paper__wl-l";
      l.textContent = String(row.losses);
      wl.appendChild(w);
      wl.appendChild(document.createTextNode(" / "));
      wl.appendChild(l);

      var position = document.createElement("span");
      position.className = "paper__position";
      if (!row.openPositions.length) {
        position.textContent = "\u2014";
      } else {
        row.openPositions.forEach(function (p) {
          var chip = document.createElement("span");
          chip.className = "paper__pos-chip paper__pos-chip--" + p.side.toLowerCase();
          chip.textContent =
            p.side + " " + p.shares.toFixed(0) + " @ " + (p.entryPrice * 100).toFixed(0) + "\u00a2";
          position.appendChild(chip);
        });
      }

      button.appendChild(rank);
      button.appendChild(name);
      button.appendChild(cash);
      button.appendChild(windowPnl);
      button.appendChild(totalPnl);
      button.appendChild(wl);
      button.appendChild(position);
      table.appendChild(button);

      if (expanded) {
        var trades = state.paper.ledger.filter(function (t) {
          return t.strategyId === row.strategyId;
        });
        var ledger = document.createElement("div");
        ledger.className = "paper__trades";
        if (!trades.length) {
          var empty = document.createElement("div");
          empty.className = "paper__trade paper__trade--empty";
          empty.textContent = "no trades yet this session";
          ledger.appendChild(empty);
        } else {
          trades.forEach(function (trade) {
            ledger.appendChild(tradeRow(trade));
          });
        }
        table.appendChild(ledger);
      }
    });

    var windowsSection = el("windows-section");
    var windowsList = el("windows");
    if (windowsSection && windowsList) {
      windowsList.textContent = "";
      if (state.paper.windows.length) {
        windowsSection.hidden = false;
        state.paper.windows.forEach(function (w) {
          var item = document.createElement("div");
          item.className = "paper__window";
          var outcomeChip = document.createElement("span");
          outcomeChip.className = "paper__outcome paper__outcome--" + w.outcome.toLowerCase();
          outcomeChip.textContent = w.outcome;
          var timeEl = document.createElement("span");
          timeEl.className = "paper__window-time";
          timeEl.textContent = clockTime(w.closedAt);
          var winner = document.createElement("span");
          winner.className = "paper__window-winner";
          var topW = w.results[0];
          winner.appendChild(
            document.createTextNode((topW ? topW.strategyName : "\u2014") + " ")
          );
          var amount = document.createElement("span");
          amount.className = pnlClass(topW ? topW.pnlUsd : 0);
          amount.textContent = money(topW ? topW.pnlUsd : 0, true);
          winner.appendChild(amount);
          item.appendChild(outcomeChip);
          item.appendChild(timeEl);
          item.appendChild(winner);
          windowsList.appendChild(item);
        });
      } else {
        windowsSection.hidden = true;
      }
    }
  }

  // ---- copy trading -------------------------------------------------------

  function sendCopyConfig(config) {
    config.type = "copy_config";
    if (state.socket && state.socket.readyState === WebSocket.OPEN) {
      state.socket.send(JSON.stringify(config));
    }
    state.confirmingCopy = false;
  }

  function renderCopy() {
    if (!state.features.copy || !state.copy || !has("copy")) return;

    el("copy").className = "copy" + (state.copy.enabled ? " copy--live" : "");

    var badge = el("copy-badge");
    badge.className =
      "copy__badge " + (state.copy.enabled ? "copy__badge--live" : "copy__badge--off");
    badge.textContent = state.copy.enabled
      ? "LIVE \u2014 REAL MONEY"
      : state.copy.available
        ? "ready"
        : "not connected";

    el("copy-address").textContent = state.copy.address
      ? state.copy.address.slice(0, 6) + "..." + state.copy.address.slice(-4)
      : "";

    el("copy-setup").hidden = state.copy.available;
    el("copy-live").hidden = !state.copy.available;

    if (state.copy.available) {
      var select = el("copy-strategy");
      if (select.options.length !== state.copy.strategies.length) {
        select.textContent = "";
        state.copy.strategies.forEach(function (s) {
          var option = document.createElement("option");
          option.value = s.id;
          option.textContent = s.name;
          select.appendChild(option);
        });
      }
      select.value = state.copy.strategyId;

      var stake = el("copy-stake");
      if (!state.stakeDirty) stake.value = state.copy.stakeUsd;
      stake.max = state.copy.maxStakeUsd;

      var wrap = el("copy-toggle-wrap");
      wrap.textContent = "";
      if (state.copy.enabled) {
        var stop = document.createElement("button");
        stop.className = "copy__toggle copy__toggle--stop";
        stop.textContent = "Stop copying";
        stop.addEventListener("click", function () {
          sendCopyConfig({ enabled: false });
        });
        wrap.appendChild(stop);
      } else if (state.confirmingCopy) {
        var confirm = document.createElement("button");
        confirm.className = "copy__toggle copy__toggle--confirm";
        confirm.textContent = "Confirm \u2014 trade real money";
        confirm.addEventListener("click", function () {
          sendCopyConfig({ enabled: true });
        });
        var cancel = document.createElement("button");
        cancel.className = "copy__toggle copy__toggle--cancel";
        cancel.textContent = "Cancel";
        cancel.addEventListener("click", function () {
          state.confirmingCopy = false;
          renderCopy();
        });
        wrap.appendChild(confirm);
        wrap.appendChild(cancel);
      } else {
        var start = document.createElement("button");
        start.className = "copy__toggle";
        start.textContent = "Start copying";
        start.addEventListener("click", function () {
          state.confirmingCopy = true;
          renderCopy();
        });
        wrap.appendChild(start);
      }

      el("copy-warning").textContent = state.copy.enabled
        ? "Every " +
          state.copy.strategyName +
          " entry buys ~$" +
          state.copy.stakeUsd +
          " of the real market; exits sell it back. Wins settle on-chain."
        : "Copying is off. Orders are only placed while this is on and the server is running.";
    }

    var error = el("copy-error");
    error.hidden = !state.copy.lastError;
    error.textContent = state.copy.lastError || "";

    var orders = el("copy-orders");
    orders.textContent = "";
    state.copy.orders.forEach(function (order) {
      var row = document.createElement("div");
      row.className = "copy__order copy__order--" + order.status;
      var time = document.createElement("span");
      time.className = "copy__order-time";
      time.textContent = clockTime(order.timestamp);
      var action = document.createElement("span");
      action.className = "copy__order-action copy__order-action--" + order.action.toLowerCase();
      action.textContent = order.action;
      var detail = document.createElement("span");
      detail.className = "copy__order-detail";
      detail.textContent = order.detail;
      row.appendChild(time);
      row.appendChild(action);
      row.appendChild(detail);
      orders.appendChild(row);
    });
  }

  function wireControls() {
    if (has("sort-pills")) {
      el("sort-pills").addEventListener("click", function (event) {
        var button = event.target.closest("[data-sort]");
        if (!button) return;
        state.sortKey = button.getAttribute("data-sort");
        Array.prototype.forEach.call(el("sort-pills").children, function (pill) {
          pill.classList.toggle(
            "leaderboard-filters__pill--active",
            pill.getAttribute("data-sort") === state.sortKey
          );
        });
        renderLeaderboard();
      });
    }

    if (has("positioned-only")) {
      el("positioned-only").addEventListener("change", function (event) {
        state.positionedOnly = event.target.checked;
        renderLeaderboard();
      });
    }

    if (has("copy-strategy")) {
      el("copy-strategy").addEventListener("change", function (event) {
        sendCopyConfig({ strategyId: event.target.value });
      });
    }

    if (has("copy-stake")) {
      var stake = el("copy-stake");
      stake.addEventListener("input", function () {
        state.stakeDirty = true;
      });
      stake.addEventListener("blur", function (event) {
        var value = Number(event.target.value);
        state.stakeDirty = false;
        if (isFinite(value)) sendCopyConfig({ stakeUsd: value });
      });
    }
  }

  function foldSnapshot(snapshot) {
    if (state.conditionId !== snapshot.conditionId) {
      state.history = [];
      state.lastBarTime = null;
      state.strikeOnChart = null;
    }
    var last = state.history[state.history.length - 1];
    if (!last || snapshot.timestamp - last.timestamp >= HISTORY_MIN_GAP_MS) {
      state.history.push(snapshot);
      if (state.history.length > HISTORY_LIMIT) state.history.shift();
    } else {
      state.history[state.history.length - 1] = snapshot;
    }
    state.conditionId = snapshot.conditionId;
  }

  function applyTick(message) {
    if (message.type === "waiting") {
      renderStatus(true);
      return;
    }

    if (message.type === "copy") {
      state.copy = message.copy;
      renderCopy();
      return;
    }

    var isFullHistory = false;
    if (message.history) {
      state.history = message.history;
      state.conditionId = message.snapshot.conditionId;
      state.lastBarTime = null;
      state.strikeOnChart = null;
      isFullHistory = true;
    } else if (message.snapshot) {
      var previousCondition = state.conditionId;
      foldSnapshot(message.snapshot);
      if (previousCondition !== message.snapshot.conditionId) isFullHistory = true;
    }

    if (message.snapshot) state.latest = message.snapshot;
    if (message.signals) state.signals = message.signals;
    if (message.paper) state.paper = message.paper;
    if (message.copy) state.copy = message.copy;

    renderStatus(true);
    renderChart(isFullHistory);
    renderSpatialBoard();
    renderStrategies();
    renderLeaderboard();
    renderCopy();
  }

  function connectLive() {
    if (!state.features.live) return;
    var protocol = location.protocol === "https:" ? "wss:" : "ws:";
    state.socket = new WebSocket(protocol + "//" + location.host + "/ws");

    state.socket.addEventListener("open", function () {
      state.reconnectDelay = 1000;
      renderStatus(true);
    });

    state.socket.addEventListener("message", function (event) {
      try {
        applyTick(JSON.parse(event.data));
      } catch (err) {
        // ignore
      }
    });

    state.socket.addEventListener("close", function () {
      renderStatus(false);
      setTimeout(connectLive, state.reconnectDelay);
      state.reconnectDelay = Math.min(state.reconnectDelay * 2, 15000);
    });

    state.socket.addEventListener("error", function () {
      state.socket.close();
    });
  }

  /** Apply a simulation frame (snapshot + signals + history slice). */
  function applySimulationFrame(snapshot, history, signals) {
    state.latest = snapshot;
    state.history = history || [];
    state.signals = signals || [];
    state.conditionId = snapshot ? snapshot.conditionId : null;
    state.lastBarTime = null;
    state.strikeOnChart = null;
    renderStatus(true);
    renderChart(true);
    renderSpatialBoard(signals);
    renderStrategies(signals);
  }

  function init(options) {
    options = options || {};
    var features = options.features || [];
    state.features = {};
    features.forEach(function (f) {
      state.features[f] = true;
    });

    wireControls();
    if (state.features.chart) initChart();
    renderStatus(false);
    if (state.features.live) connectLive();
  }

  global.Board = {
    init: init,
    applyTick: applyTick,
    applySimulationFrame: applySimulationFrame,
    renderSpatialBoard: renderSpatialBoard,
    renderStrategies: renderStrategies,
    money: money,
    price: price,
  };
})(window);

/* FIFO calculator: the maths and the page glue of web/calculator.py.
 *
 * Pure functions first (`parseRows`, `compute`, exported for node under test),
 * then the DOM wiring, which runs only where there is a document. Nothing is
 * sent anywhere: the page makes no request. User text reaches the page through
 * textContent only. The rules mirror portfolio/tax/es.py: FIFO, the two-month
 * window either side of a loss sale (art. 33.5.f LIRPF), the savings scale.
 */
(function (root) {
  "use strict";

  var DAY = 86400000;
  var EPS = 1e-9;

  function pad(n) { return n < 10 ? "0" + n : "" + n; }
  function mk(y, m, d) {
    var t = Date.UTC(y, m - 1, d);
    var o = new Date(t);
    if (o.getUTCFullYear() !== y || o.getUTCMonth() !== m - 1 || o.getUTCDate() !== d) return null;
    return t / DAY;
  }
  function ymd(day) {
    var o = new Date(day * DAY);
    return [o.getUTCFullYear(), o.getUTCMonth() + 1, o.getUTCDate()];
  }
  function iso(day) {
    var p = ymd(day);
    return p[0] + "-" + pad(p[1]) + "-" + pad(p[2]);
  }
  // ±months, clamped to the target month's last day (shift_months in base.py).
  function shiftMonths(day, k) {
    var p = ymd(day);
    var idx = p[0] * 12 + (p[1] - 1) + k;
    var y = Math.floor(idx / 12);
    var m = ((idx % 12) + 12) % 12;
    var last = new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
    return mk(y, m + 1, Math.min(p[2], last));
  }

  function parseDate(s) {
    s = String(s).trim();
    var m = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(s);
    if (m) return mk(+m[1], +m[2], +m[3]);
    m = /^(\d{1,2})[\/.-](\d{1,2})[\/.-](\d{4})$/.exec(s);
    if (m) return mk(+m[3], +m[2], +m[1]);
    return null;
  }

  // "1.234,56", "1,234.56", "12,5", "12.5" -> number; NaN when it is none.
  function parseNumber(s) {
    s = String(s).trim().replace(/\s/g, "").replace(/[€$£]/g, "");
    if (!s) return NaN;
    var comma = s.lastIndexOf(","), dot = s.lastIndexOf(".");
    if (comma >= 0 && dot >= 0) {
      s = comma > dot ? s.replace(/\./g, "").replace(",", ".") : s.replace(/,/g, "");
    } else if (comma >= 0) {
      s = s.replace(",", ".");
    }
    return /^-?\d*\.?\d+$/.test(s) || /^-?\d+\.$/.test(s) ? Number(s) : NaN;
  }

  var BUY = /^(buy|b|compra|comprar|c|acquisto|acquista|a)$/i;
  var SELL = /^(sell|s|venta|vender|v|vendita|vendi)$/i;

  // Lines: date, buy/sell, ticker, quantity, price per share, [fee], in euros.
  // Returns { rows, errors } with errors as { line, text }.
  function parseRows(text) {
    var rows = [], errors = [];
    String(text).split(/\r?\n/).forEach(function (raw, i) {
      var line = raw.trim();
      if (!line || line.charAt(0) === "#") return;
      var cols = /[;\t]/.test(line) ? line.split(/\s*[;\t]\s*/) : line.split(/\s+/);
      var date = parseDate(cols[0]);
      if (date === null && !rows.length && !/\d/.test(cols[0])) return; // header
      var side = BUY.test(cols[1] || "") ? "buy" : SELL.test(cols[1] || "") ? "sell" : null;
      var ticker = (cols[2] || "").trim().toUpperCase();
      var qty = parseNumber(cols[3] || "");
      var price = parseNumber(cols[4] || "");
      var fee = cols.length > 5 && cols[5].trim() !== "" ? parseNumber(cols[5]) : 0;
      if (date === null || !side || !ticker || !(qty > 0) || !(price >= 0) || !(fee >= 0)) {
        errors.push({ line: i + 1, text: line });
        return;
      }
      rows.push({ date: date, side: side, ticker: ticker, qty: qty, price: price, fee: fee });
    });
    return { rows: rows, errors: errors };
  }

  function progressiveTax(base, brackets) {
    if (!(base > 0)) return 0;
    var tax = 0, lower = 0;
    for (var i = 0; i < brackets.length; i++) {
      var upper = brackets[i][0] === null ? Infinity : brackets[i][0];
      if (base <= lower) break;
      tax += (Math.min(base, upper) - lower) * brackets[i][1];
      lower = upper;
    }
    return tax;
  }

  // The scale in force in `year`: the latest one at or before it (brackets_for).
  function bracketsFor(scales, year) {
    var years = Object.keys(scales).map(Number).sort(function (a, b) { return a - b; });
    var pick = years[0];
    years.forEach(function (y) { if (y <= year) pick = y; });
    return scales[String(pick)];
  }

  // FIFO over every row, the two-month rule over every loss, the year's totals.
  function compute(rows, year, scales) {
    var errors = [];
    var order = rows.map(function (r, i) {
      return { idx: i, date: r.date, side: r.side, ticker: r.ticker, qty: r.qty, price: r.price, fee: r.fee };
    }).sort(function (a, b) {
      return a.date - b.date || (a.side === "buy" ? 0 : 1) - (b.side === "buy" ? 0 : 1) || a.idx - b.idx;
    });

    var buys = {}, pieces = [];
    order.forEach(function (r) {
      var list = buys[r.ticker] || (buys[r.ticker] = []);
      if (r.side === "buy") {
        list.push({ id: r.idx, date: r.date, qty: r.qty, left: r.qty,
                    unit: (r.qty * r.price + r.fee) / r.qty, sold: [], claimed: 0 });
        return;
      }
      var held = list.reduce(function (n, l) { return n + l.left; }, 0);
      if (held + EPS < r.qty) {
        errors.push({ code: "oversell", ticker: r.ticker, date: r.date, missing: r.qty - held });
        return;
      }
      var need = r.qty, unitIn = r.price - r.fee / r.qty;
      for (var i = 0; i < list.length && need > EPS; i++) {
        var lot = list[i];
        if (lot.left <= EPS) continue;
        var take = Math.min(lot.left, need);
        lot.left -= take; need -= take;
        lot.sold.push({ day: r.date, qty: take });
        pieces.push({ ticker: r.ticker, sale: r.date, lot: lot, lotDate: lot.date, qty: take,
                      cost: take * lot.unit, proceeds: take * unitIn,
                      gain: take * (unitIn - lot.unit), deferred: 0 });
      }
    });

    // A buy of the same security after the sold lot, inside the window, blocks
    // that many shares of the loss until it is itself sold (not modelled here).
    pieces.forEach(function (p) {
      if (!(p.gain < 0)) return;
      var from = shiftMonths(p.sale, -2), to = shiftMonths(p.sale, 2), need = p.qty;
      (buys[p.ticker] || []).forEach(function (b) {
        if (need <= EPS || b.id === p.lot.id || !(b.date > p.lotDate) || b.date < from || b.date > to) return;
        var gone = b.sold.reduce(function (n, s) { return s.day <= p.sale ? n + s.qty : n; }, 0);
        var free = b.qty - gone - b.claimed;
        if (free <= EPS) return;
        var use = Math.min(free, need);
        b.claimed += use; need -= use;
      });
      var blocked = p.qty - need;
      p.deferred = p.gain * (blocked / p.qty);
    });

    var inYear = pieces.filter(function (p) { return ymd(p.sale)[0] === year; });
    var t = { gains: 0, losses: 0, deferred: 0, net: 0 };
    inYear.forEach(function (p) {
      if (p.gain > 0) t.gains += p.gain; else t.losses += p.gain;
      t.deferred += p.deferred;
      t.net += p.gain - p.deferred;
    });
    t.tax = progressiveTax(t.net, bracketsFor(scales, year));
    t.carry = t.net < 0 ? -t.net : 0;
    var years = {};
    pieces.forEach(function (p) { years[ymd(p.sale)[0]] = true; });
    return {
      pieces: inYear.map(function (p) {
        return { ticker: p.ticker, sale: p.sale, lotDate: p.lotDate, qty: p.qty,
                 cost: p.cost, proceeds: p.proceeds, gain: p.gain, deferred: p.deferred };
      }),
      totals: t,
      years: Object.keys(years).map(Number).sort(),
      errors: errors,
    };
  }

  var api = { parseRows: parseRows, parseNumber: parseNumber, parseDate: parseDate,
              compute: compute, progressiveTax: progressiveTax, bracketsFor: bracketsFor, iso: iso };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (typeof document === "undefined") return;

  // ------------------------------------------------------------------ page
  var cfg = JSON.parse(document.getElementById("calc-cfg").textContent);
  var T = cfg.t;
  var $ = function (id) { return document.getElementById(id); };
  var money = new Intl.NumberFormat(cfg.lang, { style: "currency", currency: "EUR" });
  var plain = new Intl.NumberFormat(cfg.lang, { maximumFractionDigits: 6 });
  var pct = new Intl.NumberFormat(cfg.lang, { style: "percent", maximumFractionDigits: 1 });
  function fill(s, o) {
    return s.replace(/\{(\w+)\}/g, function (_, k) { return o[k]; });
  }
  function el(tag, text, cls) {
    var n = document.createElement(tag);
    if (text !== undefined) n.textContent = text;
    if (cls) n.className = cls;
    return n;
  }

  var input = $("calc-input"), yearSel = $("calc-year"), out = $("calc-out");
  var KEY = "mbs-fifo-calc";

  function render() {
    out.textContent = "";
    var parsed = parseRows(input.value);
    var msgs = [];
    parsed.errors.forEach(function (e) {
      msgs.push(fill(T.err_row, { n: e.line, text: e.text.length > 60 ? e.text.slice(0, 60) + "…" : e.text }));
    });
    if (!parsed.rows.length) {
      if (msgs.length) out.appendChild(listOf(msgs, "calc-err"));
      yearSel.textContent = "";
      return;
    }
    var year = Number(yearSel.value) || 0;
    var first = compute(parsed.rows, year, cfg.scales);
    if (!first.years.length) first.years = [new Date().getFullYear()];
    if (first.years.indexOf(year) < 0) {
      year = first.years[first.years.length - 1];
    }
    yearSel.textContent = "";
    first.years.forEach(function (y) {
      var o = el("option", String(y)); o.value = y; if (y === year) o.selected = true;
      yearSel.appendChild(o);
    });
    var res = compute(parsed.rows, year, cfg.scales);
    res.errors.forEach(function (e) {
      msgs.push(fill(T.err_oversell, { ticker: e.ticker, date: iso(e.date), qty: plain.format(e.missing) }));
    });
    if (msgs.length) out.appendChild(listOf(msgs, "calc-err"));
    if (!res.pieces.length) { out.appendChild(el("p", fill(T.no_sales, { year: year }))); return; }

    var t = res.totals;
    var sum = el("dl", undefined, "calc-sum");
    function row(k, v, strong) {
      sum.appendChild(el("dt", k)); sum.appendChild(el("dd", v, strong ? "big" : ""));
    }
    row(T.res_net.replace("{year}", year), money.format(t.net));
    if (t.deferred < -EPS) row(T.res_deferred, money.format(-t.deferred));
    row(T.res_tax, money.format(t.tax), true);
    if (t.net > 0) row(T.res_rate, pct.format(t.tax / t.net));
    if (t.carry > EPS) row(T.res_carry, money.format(t.carry));
    out.appendChild(sum);
    if (t.deferred < -EPS) out.appendChild(el("p", T.note_deferred, "calc-note"));

    var wrap = el("div", undefined, "calc-scroll");
    var tbl = el("table");
    var head = el("tr");
    T.cols.forEach(function (c, i) { var th = el("th", c); if (i > 1) th.className = "n"; head.appendChild(th); });
    var thead = el("thead"); thead.appendChild(head); tbl.appendChild(thead);
    var body = el("tbody");
    res.pieces.forEach(function (p) {
      var tr = el("tr");
      [iso(p.sale), p.ticker, plain.format(p.qty), iso(p.lotDate), money.format(p.cost),
       money.format(p.proceeds), money.format(p.gain)].forEach(function (v, i) {
        var td = el("td", v);
        if (i === 2 || i >= 4) td.className = "n";
        if (i === 6) td.className += p.gain < 0 ? " loss" : " gain";
        tr.appendChild(td);
      });
      var note = el("td", p.deferred < -EPS ? fill(T.deferred_row, { amount: money.format(-p.deferred) }) : "");
      tr.appendChild(note);
      body.appendChild(tr);
    });
    tbl.appendChild(body); wrap.appendChild(tbl); out.appendChild(wrap);
  }

  function listOf(items, cls) {
    var ul = el("ul", undefined, cls);
    items.forEach(function (m) { ul.appendChild(el("li", m)); });
    return ul;
  }

  function save() { try { localStorage.setItem(KEY, input.value); } catch (e) {} }

  input.addEventListener("input", function () { save(); render(); });
  yearSel.addEventListener("change", render);
  $("calc-example").addEventListener("click", function () { input.value = cfg.example; save(); render(); });
  $("calc-clear").addEventListener("click", function () { input.value = ""; save(); render(); input.focus(); });
  try { input.value = localStorage.getItem(KEY) || cfg.example; } catch (e) { input.value = cfg.example; }
  render();
})(typeof window !== "undefined" ? window : globalThis);

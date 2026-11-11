// Finance: från brutto till netto, dag/vecka/månad, per agent, momsgräns, skatt per spår och grundare, transaktioner.
import { NA, esc, money, num, table, emptyView, bar, value } from "../ui.js";
import { lineChart } from "../charts.js";
import { guard, head } from "./common.js";

let period = "day", tab = "overview", query = "", typeFilter = "all";

function waterfall(s) {
  const e = s.economy, cur = s.currency;
  const v = (m) => (m && m.value !== null && m.value !== undefined ? m.value : null);
  const gross = v(e.revenue_gross), fees = v(e.platform_fees), refunds = v(e.refunds), costs = v(e.costs), net = v(e.net_profit_realized), tax = v(e.tax_reserve);
  const after = net === null || tax === null ? null : net - tax;
  const rows = [
    ["Gross revenue", gross, "settled revenue entries"],
    ["Platform fees", fees === null ? null : -fees, "fee entries"],
    ["Refunds", refunds === null ? null : -refunds, "refund entries"],
    ["Costs", costs === null ? null : -costs, "cost entries"],
    ["Failed experiments", null, "not tracked separately; included in costs"],
    ["Net profit (realized, before tax)", net, "compute_result"],
    ["Tax reserve", tax === null ? null : -tax, "TaxEngine.reserved_minor"],
    ["After tax reserve", after, "net profit minus tax reserve"],
  ];
  const max = Math.max(1, ...rows.map((r) => Math.abs(r[1] || 0)));
  return `${e.preliminary && e.preliminary.value && e.preliminary.value.length ? `<p class="pill waiting"><span class="dot"></span>Preliminary: ${esc(e.preliminary.value.join("; "))}</p>` : ""}
    ${table([{ label: "Step", html: (r) => `<b>${esc(r[0])}</b><br><span class="muted mono">${esc(r[2])}</span>` },
      { label: "Amount", right: true, html: (r) => (r[1] === null ? NA : money(r[1], cur, { sign: r[1] > 0 && r[0] !== "Gross revenue" })) },
      { label: "", html: (r) => (r[1] === null ? "" : bar(Math.abs(r[1]) / max, r[1] < 0 ? "bad" : "")) }], rows)}`;
}

function periods(s) {
  const items = s.periods[period].items;
  if (!items.length) return emptyView("No settled transactions yet.");
  return `${lineChart(items.map((i) => i.period), [{ name: "Revenue", cls: "s-revenue", values: items.map((i) => i.revenue), area: true }, { name: "Net profit", cls: "s-profit", values: items.map((i) => i.net) }])}
    ${table([{ key: "period", label: "Period" }, { label: "Revenue", right: true, html: (r) => money(r.revenue, s.currency) }, { label: "Cost", right: true, html: (r) => money(r.cost, s.currency) }, { label: "Net", right: true, html: (r) => money(r.net, s.currency) }], items.slice().reverse().slice(0, 14))}`;
}

function perAgent(s) {
  return table([{ label: "Booked by", html: (r) => `<span class="mono">${esc(r.agent)}</span>` }, { label: "Revenue", right: true, html: (r) => money(r.revenue, s.currency) },
    { label: "Cost", right: true, html: (r) => money(r.cost, s.currency) }, { label: "Profit", right: true, html: (r) => money(r.net, s.currency) }], s.per_agent.items, { empty: "No ledger entries yet." });
}

function tax(s) {
  const vat = s.economy.vat;
  const t = s.tax;
  return `<div class="stack"><div><div class="row between"><span class="label">VAT threshold ${vat ? esc(vat.year) : ""}</span><span class="mono">${vat ? `${money(vat.sales.value, s.currency)} of ${money(vat.threshold.value, s.currency)}` : "N/A"}</span></div>
      ${vat ? bar(vat.sales.value / Math.max(1, vat.threshold.value), vat.level === "ok" ? "" : vat.level === "warning" ? "warn" : "bad") : ""}</div>
    ${table([{ label: "Track", html: (r) => esc(r.track || "untracked") }, { key: "year", label: "Year" }, { label: "Rate", right: true, html: (r) => `${(r.rate_bp / 100).toFixed(1)} %` },
      { label: "Liability", right: true, html: (r) => money(r.liability, s.currency) }, { label: "Paid", right: true, html: (r) => money(r.paid, s.currency) }, { label: "Reserved", right: true, html: (r) => money(r.reserved, s.currency) }], t.items, { empty: "No tax tracks assigned yet." })}
    <div><div class="label">Per founder</div>${t.per_founder ? table([{ key: "founder", label: "Founder" }, { label: "Share", right: true, html: (r) => `${(r.share_bp / 100).toFixed(0)} %` }, { label: "Reserved", right: true, html: (r) => money(r.reserved, s.currency) }], t.per_founder)
      : '<p class="muted">N/A: entries have different owner splits, so a per-founder total is not computed.</p>'}</div></div>`;
}

function transactions(s) {
  const q = query.trim().toLowerCase();
  const rows = s.ledger.items.filter((r) => (typeFilter === "all" || r.type === typeFilter) && (!q || JSON.stringify(r).toLowerCase().includes(q)));
  return `<p class="muted">${num(rows.length)} shown of ${num(s.ledger.total)} entries (latest ${s.ledger.items.length} in the snapshot).</p>
    ${table([{ label: "ID", html: (r) => `<span class="mono">${esc(r.id)}</span>` }, { key: "date", label: "Date" }, { key: "type", label: "Type" }, { key: "status", label: "Status" },
      { label: "Amount", right: true, html: (r) => money(r.amount, r.currency) }, { key: "initiative", label: "Initiative" }, { label: "By", html: (r) => `<span class="mono">${esc(r.by)}</span>` },
      { label: "Key", html: (r) => `<span class="mono muted">${esc(r.key)}</span>` }], rows.slice(0, 200), { empty: "No transactions match." })}`;
}

export function view() {
  const types = ["all", "revenue", "fee", "refund", "cost", "capital_in", "capital_out", "tax_payment"];
  return {
    title: "Finance",
    html: `${head("Money", "Finance.")}
      <div class="tabs" role="tablist"><button role="tab" data-tab="overview" aria-selected="true">Overview</button><button role="tab" data-tab="transactions" aria-selected="false">Transactions</button></div>
      <div data-tabpanel="overview"><div class="grid g-12">
        <div class="span-6"><section class="panel"><div class="panel-head"><h2>From gross to net</h2></div><div data-part="waterfall"></div></section></div>
        <div class="span-6"><section class="panel"><div class="panel-head"><h2>Over time</h2><div class="segmented" data-period>
          <button type="button" data-p="day" aria-pressed="true">Day</button><button type="button" data-p="week" aria-pressed="false">Week</button><button type="button" data-p="month" aria-pressed="false">Month</button></div></div><div data-part="periods"></div></section></div>
        <div class="span-6"><section class="panel"><div class="panel-head"><h2>Per agent</h2></div><div data-part="peragent"></div></section></div>
        <div class="span-6"><section class="panel"><div class="panel-head"><h2>VAT and tax</h2></div><div data-part="tax"></div></section></div></div></div>
      <div data-tabpanel="transactions" hidden><section class="panel"><div class="row" role="search">
        <label class="sr-only" for="tx-q">Search</label><input id="tx-q" type="search" placeholder="Search id, initiative, key">
        <label class="sr-only" for="tx-type">Type</label><select id="tx-type">${types.map((t) => `<option value="${t}">${t === "all" ? "All types" : t}</option>`).join("")}</select></div>
        <div data-part="transactions"></div></section></div>`,
    mount: (root, getCtx) => {
      const redraw = (name, fn) => { const el = root.querySelector(`[data-part="${name}"]`); el.innerHTML = guard(getCtx(), fn); import("../ui.js").then((u) => u.applyWidths(el)); };
      root.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => {
        tab = b.dataset.tab;
        root.querySelectorAll("[data-tab]").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
        root.querySelectorAll("[data-tabpanel]").forEach((p) => { p.hidden = p.dataset.tabpanel !== tab; });
      }));
      root.querySelectorAll("[data-p]").forEach((b) => b.addEventListener("click", () => {
        period = b.dataset.p;
        root.querySelectorAll("[data-p]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
        redraw("periods", periods);
      }));
      root.querySelector("#tx-q").addEventListener("input", (e) => { query = e.target.value; redraw("transactions", transactions); });
      root.querySelector("#tx-type").addEventListener("change", (e) => { typeFilter = e.target.value; redraw("transactions", transactions); });
    },
    parts: {
      waterfall: { select: (c) => c.snapshot && c.snapshot.economy, draw: (c) => guard(c, waterfall, 6) },
      periods: { select: (c) => c.snapshot && [c.snapshot.periods, period], draw: (c) => guard(c, periods, 6) },
      peragent: { select: (c) => c.snapshot && c.snapshot.per_agent, draw: (c) => guard(c, perAgent) },
      tax: { select: (c) => c.snapshot && [c.snapshot.tax, c.snapshot.economy.vat], draw: (c) => guard(c, tax) },
      transactions: { select: (c) => c.snapshot && [c.snapshot.ledger.total, c.snapshot.ledger.items.length && c.snapshot.ledger.items[0].id], draw: (c) => guard(c, transactions, 8) },
    },
  };
}

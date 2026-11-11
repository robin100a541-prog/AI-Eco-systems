// Egna SVG-diagram (D-087). Inga bibliotek. Färger och typsnitt kommer från CSS-klasser.
import { esc } from "./ui.js";

const W = 640;

function scale(min, max, a, b) {
  const span = max - min || 1;
  return (v) => a + ((v - min) / span) * (b - a);
}

function niceMoney(minor) {
  const v = minor / 100;
  if (Math.abs(v) >= 1000) return `${(v / 1000).toFixed(1)}k`;
  return `${Math.round(v)}`;
}

// Linjediagram: series = [{ name, cls, values: [minor...] }], labels = ["2027-01-01", ...]
export function lineChart(labels, series, { height = 220 } = {}) {
  if (!labels.length) return "";
  const H = height, pad = { l: 48, r: 12, t: 12, b: 28 };
  const all = series.flatMap((s) => s.values).concat(0);
  const min = Math.min(...all), max = Math.max(...all);
  const x = scale(0, Math.max(1, labels.length - 1), pad.l, W - pad.r);
  const y = scale(min, max, H - pad.b, pad.t);
  const ticks = [min, (min + max) / 2, max];
  const grid = ticks.map((t) => `<line class="grid-line" x1="${pad.l}" x2="${W - pad.r}" y1="${y(t).toFixed(1)}" y2="${y(t).toFixed(1)}"/>
    <text class="axis" x="${pad.l - 8}" y="${(y(t) + 4).toFixed(1)}" text-anchor="end">${niceMoney(t)}</text>`).join("");
  const step = Math.max(1, Math.ceil(labels.length / 6));
  const xl = labels.map((l, i) => (i % step === 0 || i === labels.length - 1)
    ? `<text class="axis" x="${x(i).toFixed(1)}" y="${H - 8}" text-anchor="middle">${esc(String(l).slice(5) || l)}</text>` : "").join("");
  const lines = series.map((s) => {
    const pts = s.values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
    const area = s.area ? `<polygon class="area" points="${x(0).toFixed(1)},${y(Math.max(min, 0)).toFixed(1)} ${pts} ${x(s.values.length - 1).toFixed(1)},${y(Math.max(min, 0)).toFixed(1)}"/>` : "";
    return `${area}<polyline class="${esc(s.cls)}" points="${pts}"/>`;
  }).join("");
  const title = series.map((s) => s.name).join(" and ");
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(title)} over time">${grid}${lines}${xl}</svg>`;
}

// Liggande staplar per rad: rows = [{ label, a, b }] (t.ex. intäkt och kostnad)
export function barsChart(rows, { a = "Revenue", b = "Cost" } = {}) {
  if (!rows.length) return "";
  const rowH = 34, pad = { l: 150, r: 64 }, H = rows.length * rowH + 8;
  const max = Math.max(1, ...rows.flatMap((r) => [Math.abs(r.a), Math.abs(r.b)]));
  const x = scale(0, max, 0, W - pad.l - pad.r);
  const body = rows.map((r, i) => {
    const y0 = i * rowH + 6;
    return `<text class="axis" x="${pad.l - 10}" y="${y0 + 15}" text-anchor="end">${esc(r.label.slice(0, 20))}</text>
      <rect class="bar-rev" x="${pad.l}" y="${y0}" width="${x(Math.abs(r.a)).toFixed(1)}" height="10" rx="2"/>
      <rect class="bar-cost" x="${pad.l}" y="${y0 + 13}" width="${x(Math.abs(r.b)).toFixed(1)}" height="10" rx="2"/>
      <text class="axis" x="${(pad.l + x(Math.max(Math.abs(r.a), Math.abs(r.b))) + 6).toFixed(1)}" y="${y0 + 15}">${niceMoney(r.a - r.b)}</text>`;
  }).join("");
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(a)} and ${esc(b)} per agent">${body}</svg>`;
}

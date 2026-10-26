// Small dependency-free SVG charts with hover tooltips, click-through and a
// table view. Colours come from CSS custom properties (light/dark aware).
import { h, s, fmt } from './core.js';

function niceTicks(min, max, count = 4) {
  if (min === max) { max = min + 1; }
  const span = max - min;
  const step0 = span / count;
  const mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((st) => span / st <= count) || 10 * mag;
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  const ticks = [];
  for (let v = lo; v <= hi + step / 2; v += step) ticks.push(Math.round(v * 1e6) / 1e6);
  return ticks;
}

function responsive(draw) {
  const box = h('div', { class: 'chart-box' });
  let last = 0;
  const ro = new ResizeObserver((entries) => {
    const w = Math.round(entries[0].contentRect.width);
    if (w && Math.abs(w - last) > 4) { last = w; box.replaceChildren(); draw(box, w); }
  });
  ro.observe(box);
  return box;
}

function tooltip(box) {
  const tip = h('div', { class: 'chart-tip hidden' });
  box.append(tip);
  return {
    show(x, y, title, rows) {
      tip.replaceChildren(h('div', { class: 't' }, title),
        rows.map((r) => h('div', { class: 'r' },
          h('span', null, r.color ? h('i', { style: { background: r.color } }) : null, r.label),
          h('strong', { class: 'num' }, r.value))));
      tip.classList.remove('hidden');
      const bw = box.clientWidth;
      const tw = tip.offsetWidth;
      tip.style.left = `${Math.max(0, Math.min(bw - tw, x + 14))}px`;
      tip.style.top = `${Math.max(0, y - tip.offsetHeight - 10)}px`;
    },
    hide() { tip.classList.add('hidden'); },
  };
}

export function legend(series, kind = 'box') {
  if (series.length < 2) return null;
  return h('div', { class: 'legend' }, series.map((se) => h('span', null,
    h('i', { class: kind === 'line' ? 'line' : '', style: { background: se.color } }), se.label)));
}

const cssVar = (name) => `var(${name})`;

// ------------------------------------------------------------- line chart
export function lineChart({ data, series, xKey = 'period', xFmt = fmt.month, yFmt = fmt.compact, valFmt = fmt.inr, onClick, height = 240 }) {
  if (!data.length) return h('div', { class: 'chart-empty' }, 'No data for this period');
  return responsive((box, W) => {
    const H = height, L = 52, R = 14, T = 12, B = 28;
    const vals = data.flatMap((d) => series.map((se) => d[se.key] || 0));
    const ticks = niceTicks(Math.min(0, ...vals), Math.max(0, ...vals));
    const y0 = ticks[0], y1 = ticks[ticks.length - 1];
    const x = (i) => L + (data.length === 1 ? (W - L - R) / 2 : i * (W - L - R) / (data.length - 1));
    const y = (v) => T + (H - T - B) * (1 - (v - y0) / (y1 - y0 || 1));
    const svg = s('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': series.map((x) => x.label).join(', ') + ' trend' });
    ticks.forEach((t) => {
      svg.append(s('line', { x1: L, x2: W - R, y1: y(t), y2: y(t), stroke: t === 0 ? cssVar('--axis') : cssVar('--grid'), 'stroke-width': 1 }));
      svg.append(s('text', { x: L - 8, y: y(t) + 4, 'text-anchor': 'end', 'font-size': 11, fill: cssVar('--muted') }, yFmt(t)));
    });
    const every = Math.max(1, Math.ceil(data.length / Math.max(2, Math.floor((W - L) / 70))));
    data.forEach((d, i) => {
      if (i % every === 0 || i === data.length - 1) {
        svg.append(s('text', { x: x(i), y: H - 8, 'text-anchor': 'middle', 'font-size': 11, fill: cssVar('--muted') }, xFmt(d[xKey])));
      }
    });
    series.forEach((se) => {
      const pts = data.map((d, i) => `${x(i)},${y(d[se.key] || 0)}`).join(' ');
      if (data.length > 1) svg.append(s('polyline', { points: pts, fill: 'none', stroke: se.color, 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }));
      const li = data.length - 1;
      svg.append(s('circle', { cx: x(li), cy: y(data[li][se.key] || 0), r: 4, fill: se.color, stroke: cssVar('--surface'), 'stroke-width': 2 }));
    });
    const cross = s('line', { y1: T, y2: H - B, stroke: cssVar('--axis'), 'stroke-width': 1, visibility: 'hidden' });
    const dots = series.map((se) => s('circle', { r: 4.5, fill: se.color, stroke: cssVar('--surface'), 'stroke-width': 2, visibility: 'hidden' }));
    svg.append(cross, ...dots);
    const tip = tooltip(box);
    const hit = s('rect', { x: L, y: T, width: W - L - R, height: H - T - B, fill: 'transparent', style: onClick ? 'cursor:pointer' : '' });
    const idxAt = (evt) => {
      const r = svg.getBoundingClientRect();
      const px = (evt.clientX - r.left) * (W / r.width);
      return Math.max(0, Math.min(data.length - 1, Math.round((px - L) / ((W - L - R) / Math.max(1, data.length - 1)))));
    };
    hit.addEventListener('mousemove', (evt) => {
      const i = data.length === 1 ? 0 : idxAt(evt);
      const d = data[i];
      cross.setAttribute('x1', x(i)); cross.setAttribute('x2', x(i)); cross.setAttribute('visibility', 'visible');
      dots.forEach((dot, k) => { dot.setAttribute('cx', x(i)); dot.setAttribute('cy', y(d[series[k].key] || 0)); dot.setAttribute('visibility', 'visible'); });
      const r = svg.getBoundingClientRect();
      tip.show(x(i) * r.width / W, y(Math.max(...series.map((se) => d[se.key] || 0))) * r.height / H, xFmt(d[xKey]),
        series.map((se) => ({ label: se.label, color: se.color, value: valFmt(d[se.key] || 0) })));
    });
    hit.addEventListener('mouseleave', () => { tip.hide(); cross.setAttribute('visibility', 'hidden'); dots.forEach((d) => d.setAttribute('visibility', 'hidden')); });
    if (onClick) hit.addEventListener('click', (evt) => onClick(data[data.length === 1 ? 0 : idxAt(evt)]));
    svg.append(hit);
    box.prepend(svg);
  });
}

// ------------------------------------------------------------- columns
// mode 'stack' or 'group'
export function columnChart({ data, series, xKey = 'period', xFmt = fmt.month, yFmt = fmt.compact, valFmt = fmt.inr, mode = 'stack', onClick, height = 240, totalLabel }) {
  if (!data.length || data.every((d) => series.every((se) => !d[se.key]))) return h('div', { class: 'chart-empty' }, 'No data for this period');
  return responsive((box, W) => {
    const H = height, L = 52, R = 10, T = 12, B = 28;
    const totals = data.map((d) => mode === 'stack' ? series.reduce((a, se) => a + Math.max(0, d[se.key] || 0), 0) : Math.max(...series.map((se) => d[se.key] || 0)));
    const ticks = niceTicks(0, Math.max(...totals, 1));
    const y1 = ticks[ticks.length - 1];
    const band = (W - L - R) / data.length;
    const groupW = Math.min(mode === 'stack' ? 24 : 40, band * 0.7);
    const barW = mode === 'stack' ? groupW : Math.max(2, (groupW - 2 * (series.length - 1)) / series.length);
    const y = (v) => T + (H - T - B) * (1 - v / y1);
    const svg = s('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': series.map((x) => x.label).join(', ') });
    ticks.forEach((t) => {
      svg.append(s('line', { x1: L, x2: W - R, y1: y(t), y2: y(t), stroke: t === 0 ? cssVar('--axis') : cssVar('--grid'), 'stroke-width': 1 }));
      svg.append(s('text', { x: L - 8, y: y(t) + 4, 'text-anchor': 'end', 'font-size': 11, fill: cssVar('--muted') }, yFmt(t)));
    });
    const every = Math.max(1, Math.ceil(data.length / Math.max(2, Math.floor((W - L) / 64))));
    const tip = tooltip(box);
    data.forEach((d, i) => {
      const cx = L + band * i + band / 2;
      if (i % every === 0 || i === data.length - 1) svg.append(s('text', { x: cx, y: H - 8, 'text-anchor': 'middle', 'font-size': 11, fill: cssVar('--muted') }, xFmt(d[xKey])));
      const g = s('g', { style: onClick ? 'cursor:pointer' : '' });
      g.append(s('rect', { x: L + band * i, y: T, width: band, height: H - T - B, fill: 'transparent' }));
      let acc = 0;
      const visible = series.filter((se) => (d[se.key] || 0) > 0);
      series.forEach((se, k) => {
        const v = Math.max(0, d[se.key] || 0);
        if (!v) return;
        let x0, top, bottom;
        if (mode === 'stack') {
          x0 = cx - barW / 2; bottom = y(acc); acc += v; top = y(acc);
          if (acc !== v) bottom -= 2; // 2px surface gap between segments
        } else {
          x0 = cx - groupW / 2 + k * (barW + 2); bottom = y(0); top = y(v);
        }
        const isTop = mode !== 'stack' || se === visible[visible.length - 1];
        g.append(barPath(x0, top, barW, Math.max(0, bottom - top), isTop, se.color));
      });
      g.addEventListener('mousemove', (evt) => {
        const r = svg.getBoundingClientRect();
        const rowsT = series.map((se) => ({ label: se.label, color: se.color, value: valFmt(d[se.key] || 0) }));
        if (mode === 'stack' && series.length > 1) rowsT.push({ label: totalLabel || 'Total', value: valFmt(totals[i]) });
        if (d._extra) rowsT.push(...d._extra);
        tip.show(evt.clientX - r.left, (y(totals[i])) * r.height / H, xFmt(d[xKey]), rowsT);
      });
      g.addEventListener('mouseleave', () => tip.hide());
      if (onClick) g.addEventListener('click', () => onClick(d));
      svg.append(g);
    });
    box.prepend(svg);
  });
}

// vertical bar with 4px rounded data end, square at the baseline
function barPath(x, y, w, hgt, roundTop, color) {
  const r = roundTop ? Math.min(4, w / 2, hgt) : 0;
  const d = `M${x},${y + hgt} L${x},${y + r} Q${x},${y} ${x + r},${y} L${x + w - r},${y} Q${x + w},${y} ${x + w},${y + r} L${x + w},${y + hgt} Z`;
  return s('path', { d, fill: color });
}

// ------------------------------------------------------------- horizontal bars
// data: [{label, values: {key: n}, ...}], series: [{key,label,color}]
export function hbarChart({ data, series, valFmt = fmt.inr, shortFmt = fmt.compact, labelFmt, onClick, max = 10, emptyText }) {
  const rows = data.slice(0, max);
  if (!rows.length || rows.every((d) => series.every((se) => !d[se.key]))) return h('div', { class: 'chart-empty' }, emptyText || 'No data for this period');
  return responsive((box, W) => {
    const labelW = Math.min(150, Math.max(90, W * 0.3));
    const valueW = 86;
    const barH = series.length > 1 ? 9 : 14;
    const rowH = series.length > 1 ? 34 : 30;
    const H = rows.length * rowH + 6;
    const maxV = Math.max(...rows.flatMap((d) => series.map((se) => Math.abs(d[se.key] || 0))), 1);
    const plotW = Math.max(40, W - labelW - valueW - 8);
    const svg = s('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img' });
    const tip = tooltip(box);
    rows.forEach((d, i) => {
      const y0 = i * rowH + 3;
      const g = s('g', { class: onClick ? 'hbar-row' : '' });
      g.append(s('rect', { class: 'hbar-bg', x: 0, y: y0, width: W, height: rowH - 2, rx: 6, fill: 'transparent' }));
      const name = labelFmt ? labelFmt(d) : d.label;
      g.append(s('text', { x: 4, y: y0 + rowH / 2 + 4, 'font-size': 12, fill: cssVar('--ink-2') }, truncate(String(name), Math.floor(labelW / 7))));
      g.append(s('line', { x1: labelW, x2: labelW, y1: y0 + 3, y2: y0 + rowH - 5, stroke: cssVar('--axis') }));
      series.forEach((se, k) => {
        const v = d[se.key] || 0;
        const w = Math.abs(v) / maxV * plotW;
        const by = series.length > 1 ? y0 + rowH / 2 - barH - 1 + k * (barH + 2) : y0 + (rowH - barH) / 2;
        if (w > 0) g.append(hbarPath(labelW, by, w, barH, v < 0 ? cssVar('--bad') : se.color));
      });
      const primary = d[series[0].key] || 0;
      g.append(s('text', { x: W - 4, y: y0 + rowH / 2 + 4, 'text-anchor': 'end', 'font-size': 12, fill: cssVar('--ink'), 'font-weight': 600 }, shortFmt(primary)));
      g.addEventListener('mousemove', (evt) => {
        const r = svg.getBoundingClientRect();
        const rowsT = series.map((se) => ({ label: se.label, color: series.length > 1 ? se.color : null, value: valFmt(d[se.key] || 0) }));
        if (d._extra) rowsT.push(...d._extra);
        tip.show(evt.clientX - r.left, (y0) * r.height / H, String(name), rowsT);
      });
      g.addEventListener('mouseleave', () => tip.hide());
      if (onClick) g.addEventListener('click', () => onClick(d));
      svg.append(g);
    });
    box.prepend(svg);
  });
}

function hbarPath(x, y, w, hgt, color) {
  const r = Math.min(4, hgt / 2, w);
  const d = `M${x},${y} L${x + w - r},${y} Q${x + w},${y} ${x + w},${y + r} L${x + w},${y + hgt - r} Q${x + w},${y + hgt} ${x + w - r},${y + hgt} L${x},${y + hgt} Z`;
  return s('path', { d, fill: color });
}

function truncate(t, n) { return t.length > n ? t.slice(0, n - 1) + '…' : t; }

// ------------------------------------------------------------- chart card with table toggle
export function chartCard({ title, sub, chart, legendEl, tableFn, wide, actions }) {
  const body = h('div', null, legendEl || null, chart);
  let showingTable = false;
  const toggle = tableFn ? h('button', {
    class: 'btn ghost small', 'aria-pressed': 'false', onclick: () => {
      showingTable = !showingTable;
      toggle.textContent = showingTable ? 'Chart' : 'Table';
      toggle.setAttribute('aria-pressed', String(showingTable));
      body.replaceChildren(...(showingTable ? [h('div', { style: { padding: '8px 14px 14px' } }, tableFn())] : [legendEl, chart].filter(Boolean)));
    },
  }, 'Table') : null;
  return h('div', { class: `card chart-card ${wide ? 'wide' : ''}` },
    h('div', { class: 'card-head' }, h('div', null, h('h3', null, title), sub ? h('div', { class: 'sub' }, sub) : null),
      h('span', { class: 'spacer' }), actions || null, toggle),
    body);
}

export const COLORS = {
  s1: 'var(--series-1)', s2: 'var(--series-2)', s3: 'var(--series-3)',
  retail: 'var(--retail)', wholesale: 'var(--wholesale)',
};

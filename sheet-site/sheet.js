// Garment Shop dashboard backed by a Google Sheet (data from /api/sheet).
import { h, state, fmt, icon, card, field, datePresets, toast } from './core.js';
import { columnChart, hbarChart, chartCard, legend, COLORS } from './charts.js';

const app = document.getElementById('app');
const FILTER_KEYS = ['from', 'to', 'category', 'type', 'seller', 'q'];
let sortKey = 'date';
let sortDesc = true;

function readFilters() {
  const p = new URLSearchParams(location.search);
  return Object.fromEntries(FILTER_KEYS.filter((k) => p.get(k)).map((k) => [k, p.get(k)]));
}

function writeFilters(f) {
  const p = new URLSearchParams();
  for (const k of FILTER_KEYS) if (f[k]) p.set(k, f[k]);
  history.replaceState(null, '', location.pathname + (p.toString() ? `?${p}` : ''));
}

async function load(fresh = false) {
  const f = readFilters();
  const p = new URLSearchParams(f);
  if (fresh) { p.set('fresh', '1'); p.set('t', Date.now()); }
  let data;
  try {
    const res = await fetch(`/api/sheet?${p}`);
    data = await res.json().catch(() => ({ error: 'The server sent an unreadable reply.' }));
    if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  } catch (e) {
    app.replaceChildren(errorView(e.message));
    return;
  }
  state.today = data.today;
  render(data, f);
  if (fresh) toast('Updated from Google Sheet');
}

function errorView(message) {
  return h('div', { class: 'stack', style: { maxWidth: '640px', margin: '40px auto' } },
    h('h1', null, 'Cannot load the Google Sheet'),
    h('div', { class: 'notice bad' }, message),
    h('ol', { class: 'small' },
      h('li', null, 'In Google Sheets, click Share → General access → "Anyone with the link" → Viewer.'),
      h('li', null, 'In Vercel, set GOOGLE_SHEET_ID to the sheet\'s link or ID, then redeploy.'),
      h('li', null, 'Make sure row 1 of the first tab has the column headers.')),
    h('button', { class: 'btn primary', onclick: () => load(true) }, 'Try again'));
}

function kpi(label, value, sub) {
  return h('div', { class: 'kpi' }, h('span', { class: 'kpi-label' }, label),
    h('span', { class: 'kpi-value num' }, value), sub ? h('span', { class: 'kpi-sub' }, sub) : null);
}

function filterBar(data, f) {
  const apply = (patch) => { writeFilters(Object.assign({}, f, patch)); load(); };
  const opt = (name, label, plural, values) => {
    const sel = h('select', { onchange: (e) => apply({ [name]: e.target.value }) },
      h('option', { value: '' }, `All ${plural}`), values.map((v) => h('option', { value: v }, v)));
    sel.value = f[name] || '';
    return field(label, sel);
  };
  const presets = datePresets().filter((p) => p.key !== 'today' && p.key !== '7d');
  const search = h('input', { type: 'search', placeholder: 'Product ID, type, size, seller…', value: f.q || '' });
  search.addEventListener('change', () => apply({ q: search.value }));
  const bar = h('div', { class: 'filters' },
    h('div', { class: 'stack period', style: { gap: '5px' } }, h('span', { class: 'small muted' }, 'Date of entry'),
      h('div', { class: 'presets' }, presets.map((p) => h('button', {
        class: `btn small ${(f.from || '') === p.from && (f.to || '') === p.to ? 'primary' : ''}`,
        onclick: () => apply({ from: p.from, to: p.to }),
      }, p.label)))),
    field('From', h('input', { type: 'date', value: f.from || '', onchange: (e) => apply({ from: e.target.value }) })),
    field('To', h('input', { type: 'date', value: f.to || '', onchange: (e) => apply({ to: e.target.value }) })),
    opt('category', 'Category', 'categories', data.options.category),
    opt('type', 'Product type', 'types', data.options.type),
    opt('seller', 'Seller', 'sellers', data.options.seller),
    field('Search', search));
  if (FILTER_KEYS.some((k) => f[k])) {
    bar.append(h('button', { class: 'btn ghost small', onclick: () => { writeFilters({}); load(); } }, 'Clear filters'));
  }
  return bar;
}

const money = (key, label) => ({ label, num: true, key, render: (r) => fmt.inr(r[key]) });
const qty = (key, label) => ({ label, num: true, key, render: (r) => fmt.num(r[key]) });

function stockBadge(r) {
  if (r.out_of_stock) return h('span', { class: 'badge bad' }, 'Out of stock');
  if (r.low_stock) return h('span', { class: 'badge warn' }, 'Low stock');
  return h('span', { class: 'badge good' }, 'In stock');
}

function sortableTable(columns, rows, onSort) {
  const sorted = rows.slice().sort((a, b) => {
    const x = a[sortKey], y = b[sortKey];
    const c = (x === null || x === undefined) ? -1 : (y === null || y === undefined) ? 1
      : (typeof x === 'number' ? x - y : String(x).localeCompare(String(y)));
    return sortDesc ? -c : c;
  });
  const head = h('tr', null, columns.map((c) => h('th', {
    class: `sort ${c.num ? 'num' : ''} ${sortKey === c.key ? 'on' : ''}`,
    onclick: () => { if (sortKey === c.key) sortDesc = !sortDesc; else { sortKey = c.key; sortDesc = !!c.num; } onSort(); },
  }, c.label, sortKey === c.key ? (sortDesc ? ' ↓' : ' ↑') : '')));
  const body = sorted.map((r) => h('tr', null, columns.map((c) => h('td', { class: c.num ? 'num' : '' }, c.render ? c.render(r) : r[c.key]))));
  return h('div', { class: 'table-wrap' }, h('table', null, h('thead', null, head), h('tbody', null, body)));
}

function render(data, f) {
  const k = data.kpis;
  const head = h('div', { class: 'page-head sheet-head' },
    h('div', { class: 'row', style: { gap: '12px', flexWrap: 'nowrap' } },
      h('div', { class: 'brand-mark' }, icon('product')),
      h('div', null, h('h1', null, 'Garment Shop Dashboard'),
        h('div', { class: 'updated' }, `Live from Google Sheet · ${k.entries} entries · loaded ${new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}`))),
    h('div', { class: 'actions' },
      data.sheet_url ? h('a', { class: 'btn', href: data.sheet_url, target: '_blank', rel: 'noopener' }, 'Open Google Sheet') : null,
      h('button', { class: 'btn primary', onclick: (e) => { e.target.disabled = true; load(true); } }, 'Refresh')));

  const parts = [head, filterBar(data, f)];
  if (data.issues.length) {
    parts.push(h('details', { class: 'notice warn issues', style: { marginBottom: '16px' } },
      h('summary', null, `${data.issues.length} row(s) in the sheet need attention`),
      h('ul', null, data.issues.map((m) => h('li', null, m)))));
  }
  if (!k.entries) {
    parts.push(h('div', { class: 'empty card' }, FILTER_KEYS.some((x) => f[x]) ? 'No entries match these filters.' : 'The sheet has no entries yet. Add rows in Google Sheets, then press Refresh.'));
    app.replaceChildren(...parts);
    return;
  }

  parts.push(h('div', { class: 'kpis' },
    kpi('Revenue', fmt.inr(k.revenue), 'Units sold × selling price'),
    kpi('Profit', fmt.inr(k.profit), 'Revenue − cost of units sold'),
    kpi('Profit margin', fmt.pct(k.margin), 'Profit ÷ revenue'),
    kpi('Units sold', fmt.num(k.units_sold), `${fmt.pct(k.sell_through)} of stock sold`),
    kpi('Units available', fmt.num(k.units_available), `of ${fmt.num(k.total_units)} units stocked`),
    kpi('Stock purchased (cost)', fmt.inr(k.stock_cost), 'Total units × cost'),
    kpi('Cost of units sold', fmt.inr(k.cogs), 'Units sold × cost'),
    kpi('Unsold stock at cost', fmt.inr(k.unsold_cost), `Worth ${fmt.inr0(k.unsold_retail)} at selling price`),
    kpi('Products', fmt.num(k.products), `${k.entries} entries`),
    kpi('Low / out of stock', `${k.low_stock} / ${k.out_of_stock}`, 'Entries needing restock')));

  const rp = [{ key: 'revenue', label: 'Revenue', color: COLORS.s1 }, { key: 'profit', label: 'Profit', color: COLORS.s3 }];
  const tbl = (cols, rows) => () => sortableTableStatic(cols, rows);
  const groupCols = (label) => [{ label, key: 'name' }, qty('units_sold', 'Sold'), qty('units_available', 'Available'),
    money('stock_cost', 'Stock cost'), money('revenue', 'Revenue'), money('profit', 'Profit'), { label: 'Margin', num: true, render: (r) => fmt.pct(r.margin) }];
  const months = data.by_month.map((m) => Object.assign({ period: m.name }, m));
  const pick = (key) => (r) => { writeFilters(Object.assign({}, f, { [key]: r.name })); load(); };

  parts.push(h('h2', { class: 'section-title' }, 'Charts'), h('div', { class: 'charts' },
    chartCard({
      title: 'Revenue and profit by month', sub: 'Grouped by Date of Entry', wide: true, legendEl: legend(rp),
      chart: columnChart({ data: months, series: rp, mode: 'group' }),
      tableFn: tbl(groupCols('Month').map((c) => c.key === 'name' ? Object.assign({}, c, { render: (r) => fmt.month(r.name) }) : c), data.by_month),
    }),
    chartCard({
      title: 'By product category', sub: 'Click a bar to filter', legendEl: legend(rp),
      chart: hbarChart({ data: data.by_category.map((g) => Object.assign({ label: g.name }, g)), series: rp, onClick: pick('category') }),
      tableFn: tbl(groupCols('Category'), data.by_category),
    }),
    chartCard({
      title: 'Top products by profit', sub: 'Per Product ID',
      chart: hbarChart({
        data: data.top_profit.map((g) => Object.assign({ label: `${g.name} · ${g.type}`, _extra: [{ label: 'Revenue', value: fmt.inr(g.revenue) }, { label: 'Units sold', value: fmt.num(g.units_sold) }] }, g)),
        series: [{ key: 'profit', label: 'Profit', color: COLORS.s3 }],
      }),
      tableFn: tbl([{ label: 'Product ID', key: 'name' }, { label: 'Type', key: 'type' }, { label: 'Category', key: 'category' },
        qty('units_sold', 'Sold'), money('revenue', 'Revenue'), money('profit', 'Profit')], data.top_profit),
    }),
    chartCard({
      title: 'Units sold vs available by product type', sub: 'Click a bar to filter',
      legendEl: legend([{ label: 'Sold', color: COLORS.s1 }, { label: 'Available', color: COLORS.s2 }]),
      chart: hbarChart({
        data: data.by_type.map((g) => Object.assign({ label: g.name }, g)),
        series: [{ key: 'units_sold', label: 'Sold', color: COLORS.s1 }, { key: 'units_available', label: 'Available', color: COLORS.s2 }],
        valFmt: fmt.num, shortFmt: fmt.compactNum, onClick: pick('type'),
      }),
      tableFn: tbl(groupCols('Product type'), data.by_type),
    }),
    chartCard({
      title: 'Stock purchased by seller', sub: 'Total units × cost · click to filter',
      chart: hbarChart({
        data: data.by_seller.map((g) => Object.assign({ label: g.name, _extra: [{ label: 'Revenue', value: fmt.inr(g.revenue) }, { label: 'Profit', value: fmt.inr(g.profit) }] }, g)),
        series: [{ key: 'stock_cost', label: 'Stock cost', color: COLORS.s1 }], onClick: pick('seller'),
      }),
      tableFn: tbl(groupCols('Seller'), data.by_seller),
    })));

  if (data.attention.length) {
    parts.push(h('div', { style: { height: '16px' } }), card(`Needs restocking (${data.attention.length})`, sortableTableStatic([
      { label: 'Product ID', key: 'product_id' }, { label: 'Type', key: 'type' }, { label: 'Sizes', key: 'sizes' },
      { label: 'Seller', key: 'seller' }, qty('units_available', 'Available'), qty('total_units', 'Stocked'),
      { label: 'Status', render: stockBadge }], data.attention), { sub: 'Out of stock, or 10% or less left' }));
  }

  const entryCols = [
    { label: 'Date of Entry', key: 'date', render: (r) => fmt.date(r.date) },
    { label: 'Product ID', key: 'product_id' }, { label: 'Category', key: 'category' }, { label: 'Type', key: 'type' },
    { label: 'Sizes', key: 'sizes' }, { label: 'Seller', key: 'seller' },
    money('cost', 'Cost'), qty('total_units', 'Total Units'), money('price', 'Selling Price'), qty('units_sold', 'Units Sold'),
    qty('units_available', 'Units available'), money('revenue', 'Revenue'), money('profit', 'Profit'),
    { label: 'Stock', key: 'units_available', render: stockBadge },
  ];
  const tableHost = h('div');
  const drawTable = () => tableHost.replaceChildren(sortableTable(entryCols, data.rows, drawTable));
  drawTable();
  parts.push(h('div', { style: { height: '16px' } }), card(`All entries (${data.rows.length})`, tableHost, { sub: 'Click a column to sort' }));
  app.replaceChildren(...parts);
}

function sortableTableStatic(columns, rows) {
  return h('div', { class: 'table-wrap' }, h('table', null,
    h('thead', null, h('tr', null, columns.map((c) => h('th', { class: c.num ? 'num' : '' }, c.label)))),
    h('tbody', null, rows.map((r) => h('tr', null, columns.map((c) => h('td', { class: c.num ? 'num' : '' }, c.render ? c.render(r) : r[c.key])))))));
}

load();

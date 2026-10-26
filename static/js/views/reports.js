import { h, api, state, fmt, pageHead, card, table, hashQuery, setHashQuery, datePresets, icon, qs } from '../core.js';
import { filterBar } from './dashboard.js';
import { lineChart, chartCard, legend, COLORS } from '../charts.js';

const cleanF = (f) => ({ from: f.from, to: f.to, channel: f.channel, category_id: f.category_id, product_id: f.product_id, supplier_id: f.supplier_id });

function cellFmt(type, v) {
  if (v === null || v === undefined || v === '') return '';
  if (type === 'money') return fmt.inr(v);
  if (type === 'qty') return fmt.num(v);
  if (type === 'pct') return fmt.pct(v);
  if (type === 'date') return fmt.date(v);
  if (type === 'month') return fmt.month(v);
  return String(v);
}

function reportTable(r) {
  const cols = r.columns.map((c) => ({ label: c.label, num: ['money', 'qty', 'pct', 'int'].includes(c.type), key: c.key, render: (row) => cellFmt(c.type, row[c.key]) }));
  const totals = {};
  for (const c of r.columns) if (r.totals && r.totals[c.key] !== undefined) totals[c.key] = cellFmt(c.type, r.totals[c.key]);
  return table(cols, r.rows, { totals: r.rows.length && Object.keys(totals).length ? totals : null, empty: 'No records for these filters.' });
}

// ---------------------------------------------------------------- profit
export async function profitView() {
  const f = hashQuery();
  if (!('from' in f)) { const p = datePresets().find((x) => x.key === 'fy'); f.from = p.from; f.to = p.to; }
  const d = await api.get('/api/profit', cleanF(f));
  const s = d.summary;
  const root = h('div');
  root.append(pageHead('Revenue & profit', `Cost of goods sold uses ${d.costing_method === 'FIFO' ? 'FIFO' : 'weighted-average'} cost of the units actually sold`));
  root.append(filterBar(f, (nf) => { setHashQuery(nf); state.rerender(); }));

  const line = (label, value, cls = '', note) => h('tr', { class: cls }, h('td', null, label, note ? h('span', { class: 'muted small' }, `  ${note}`) : null), h('td', { class: 'num' }, fmt.inr(value)));
  const ch = (k) => d.channels[k] || { net_sales: 0, cogs: 0, gross_profit: 0, margin: null, units_sold: 0, invoices: 0, discount: 0, returns: 0, gross: 0 };
  root.append(h('div', { class: 'grid-2' },
    card('Profit statement', h('table', { class: 'statement' }, h('tbody', null,
      line('Gross sales (excl. GST)', s.gross), line('− Discounts', -s.discount, 'sub'), line('− Sales returns', -s.returns, 'sub'),
      line('Net sales revenue', s.net_sales, 'total'),
      line('− Cost of goods sold', -s.cogs, 'sub', 'inventory cost of units sold'),
      line('Gross profit', s.gross_profit, 'total', fmt.pct(s.margin)),
      line('− Operating expenses', -s.expenses, 'sub'), line('− Stock write-offs', -s.writeoffs, 'sub', 'damaged / lost'),
      line('Net operating profit', s.net_profit, 'total', fmt.pct(s.net_margin)))),
    { sub: 'Unsold purchases stay in inventory value; they are not expensed.' }),
    card('Retail vs wholesale profitability', table([
      { label: '', render: (r) => fmt.channel(r.k) }, { label: 'Invoices', num: true, render: (r) => r.invoices },
      { label: 'Units', num: true, render: (r) => fmt.num(r.units_sold - r.units_returned) },
      { label: 'Net sales', num: true, render: (r) => fmt.inr(r.net_sales) }, { label: 'COGS', num: true, render: (r) => fmt.inr(r.cogs) },
      { label: 'Gross profit', num: true, render: (r) => fmt.inr(r.gross_profit) }, { label: 'Margin', num: true, render: (r) => fmt.pct(r.margin) },
    ], ['retail', 'wholesale'].map((k) => Object.assign({ k }, ch(k))), { onRow: (r) => { location.hash = '#/sales' + qs(Object.assign(cleanF(f), { channel: r.k })); } }))));

  const series = [{ key: 'net_sales', label: 'Net sales', color: COLORS.s1 }, { key: 'gross_profit', label: 'Gross profit', color: COLORS.s3 }, { key: 'net_profit', label: 'Net operating profit', color: COLORS.s2 }];
  const monthly = d.monthly.map((m) => Object.assign({ period: m.month }, m));
  root.append(h('div', { style: { height: '16px' } }), chartCard({
    title: 'Monthly profit trend', wide: true, legendEl: legend(series, 'line'),
    chart: lineChart({ data: monthly, series }),
    tableFn: () => reportTable({ columns: [{ key: 'month', label: 'Month', type: 'month' }, { key: 'net_sales', label: 'Net sales', type: 'money' }, { key: 'cogs', label: 'COGS', type: 'money' },
      { key: 'gross_profit', label: 'Gross profit', type: 'money' }, { key: 'expenses', label: 'Expenses', type: 'money' }, { key: 'writeoffs', label: 'Write-offs', type: 'money' },
      { key: 'net_profit', label: 'Net profit', type: 'money' }, { key: 'net_margin', label: 'Net margin', type: 'pct' }], rows: monthly }),
  }));
  root.append(h('div', { style: { height: '16px' } }), card('Profit by category', reportTable(d.categories)));
  root.append(h('div', { style: { height: '16px' } }), card('Profit by product', reportTable(d.products), {
    actions: h('a', { class: 'btn small', href: `#/reports/product-profit${qs(cleanF(f))}` }, 'Open report') }));
  return root;
}

// ---------------------------------------------------------------- reports
const DESCRIPTIONS = {
  'purchase-register': 'Every purchase line by supplier, with landed cost per unit.',
  inventory: 'Current stock, average cost, value at cost and at retail.',
  'daily-sales': 'Invoice-wise sales with GST, receipts and balance due.',
  'channel-sales': 'Retail and wholesale side by side, month by month.',
  'category-profit': 'Net sales, COGS and gross profit per category.',
  'product-profit': 'Net sales, COGS and gross profit per product.',
  'monthly-pl': 'Month-wise profit and loss including expenses.',
  capital: 'Capital contributed, withdrawals and loans.',
  'supplier-balances': 'What you owe each supplier.',
  'customer-balances': 'What each credit customer owes you.',
  expenses: 'Every operating expense in the period.',
  'stock-movement': 'Opening, purchased, sold, returned, adjusted and closing stock.',
};

export async function reportsView() {
  const f = hashQuery();
  if (!('from' in f)) { const p = datePresets().find((x) => x.key === 'fy'); f.from = p.from; f.to = p.to; }
  const list = await api.get('/api/reports');
  const go = (patch) => { setHashQuery(Object.assign({}, f, patch)); state.rerender(); };
  const range = { from: f.from, to: f.to };
  const root = h('div');
  root.append(pageHead('Reports', 'Download as Excel (.xlsx) or CSV. Amounts in ₹, dates in DD-MM-YYYY.', [
    h('button', { class: 'btn primary', onclick: () => api.download('/api/reports/all', range) }, icon('download'), 'All reports (one Excel file)')]));
  root.append(h('div', { class: 'filters' },
    h('div', { class: 'presets' }, datePresets().map((p) => h('button', { class: `btn small ${(f.from || '') === p.from && (f.to || '') === p.to ? 'primary' : ''}`, onclick: () => go({ from: p.from, to: p.to }) }, p.label))),
    h('span', { class: 'muted small' }, `Period: ${f.from || f.to ? `${fmt.date(f.from) || 'start'} – ${fmt.date(f.to) || 'today'}` : 'All time'} (date-based reports)`)));
  root.append(h('div', { class: 'grid-3' }, list.map((r) => h('div', { class: 'card card-pad stack', style: { gap: '8px' } },
    h('h3', null, h('a', { href: `#/reports/${r.key}${qs(range)}` }, r.title)),
    h('div', { class: 'small muted', style: { flex: 1 } }, DESCRIPTIONS[r.key] || ''),
    h('div', { class: 'row' },
      h('a', { class: 'btn small', href: `#/reports/${r.key}${qs(range)}` }, 'View'),
      h('button', { class: 'btn small', onclick: () => api.download(`/api/reports/${r.key}`, Object.assign({ format: 'xlsx' }, range)) }, icon('download'), 'Excel'),
      h('button', { class: 'btn small', onclick: () => api.download(`/api/reports/${r.key}`, Object.assign({ format: 'csv' }, range)) }, icon('download'), 'CSV'))))));
  return root;
}

export async function reportView(key) {
  const f = hashQuery();
  const list = await api.get('/api/reports');
  const meta = list.find((r) => r.key === key);
  if (!meta) return h('div', { class: 'empty' }, 'Unknown report');
  const r = await api.get(`/api/reports/${key}`, cleanF(f));
  const fl = meta.filters;
  const params = cleanF(f);
  const root = h('div');
  root.append(pageHead(r.title, `${r.rows.length} row(s) · ${state.shopName}`, [
    h('a', { class: 'btn', href: '#/reports' }, icon('back'), 'All reports'),
    h('button', { class: 'btn', onclick: () => api.download(`/api/reports/${key}`, Object.assign({ format: 'csv' }, params)) }, icon('download'), 'CSV'),
    h('button', { class: 'btn primary', onclick: () => api.download(`/api/reports/${key}`, Object.assign({ format: 'xlsx' }, params)) }, icon('download'), 'Excel')]));
  if (fl.length) {
    const bar = filterBar(f, (nf) => { setHashQuery(nf); state.rerender(); }, {
      date: fl.includes('date'), channel: fl.includes('channel'), category: fl.includes('category'), supplier: fl.includes('supplier'), product: fl.includes('product'),
    });
    root.append(bar);
  }
  root.append(card(null, reportTable(r)));
  return root;
}

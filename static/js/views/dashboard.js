import { h, api, state, fmt, can, pageHead, linkBtn, card, table, hashQuery, setHashQuery, datePresets, field, select, combobox, qs } from '../core.js';
import { lineChart, columnChart, hbarChart, chartCard, legend, COLORS } from '../charts.js';

// Dashboard filters: date range, supplier, category, product, channel.
export function filterBar(f, onChange, opts = {}) {
  const presets = datePresets();
  const from = h('input', { type: 'date', value: f.from || '', max: state.today });
  const to = h('input', { type: 'date', value: f.to || '', max: state.today });
  const apply = (patch) => onChange(Object.assign({}, f, patch));
  from.addEventListener('change', () => apply({ from: from.value }));
  to.addEventListener('change', () => apply({ to: to.value }));
  const bar = h('div', { class: 'filters' });
  if (opts.date !== false) {
    bar.append(h('div', { class: 'stack period', style: { gap: '5px' } }, h('span', { class: 'small muted' }, 'Period'),
      h('div', { class: 'presets' }, presets.map((p) => h('button', {
        class: `btn small ${(f.from || '') === p.from && (f.to || '') === p.to ? 'primary' : ''}`,
        onclick: () => apply({ from: p.from, to: p.to }),
      }, p.label)))),
    field('From', from), field('To', to));
  }
  if (opts.channel !== false) {
    bar.append(field('Channel', select('channel', [{ value: '', label: 'All channels' }, { value: 'retail', label: 'Retail' }, { value: 'wholesale', label: 'Wholesale' }],
      f.channel || '', { onchange: (e) => apply({ channel: e.target.value }) })));
  }
  if (opts.category !== false) {
    bar.append(field('Category', select('category_id', [{ value: '', label: 'All categories' }].concat(state.categories.map((c) => ({ value: c.id, label: c.name }))),
      f.category_id || '', { onchange: (e) => apply({ category_id: e.target.value, product_id: '' }) })));
  }
  if (opts.supplier !== false && can('purchases.view')) {
    const sup = combobox({
      name: 'supplier_id', placeholder: 'All suppliers', label: f.supplier_name || '',
      source: async (q) => [{ value: '', label: 'All suppliers' }].concat((await api.get('/api/suppliers', { q })).map((x) => ({ value: x.id, label: x.name, sub: x.code }))),
      onPick: (it) => apply({ supplier_id: it.value, supplier_name: it.value ? it.label : '' }),
    });
    bar.append(field('Supplier', sup));
  }
  if (opts.product !== false) {
    const prod = combobox({
      name: 'product_id', placeholder: 'All products', label: f.product_name || '',
      source: async (q) => [{ value: '', label: 'All products' }].concat((await api.get('/api/products', { q, category_id: f.category_id })).map((x) => ({ value: x.id, label: x.name, sub: x.category }))),
      onPick: (it) => apply({ product_id: it.value, product_name: it.value ? it.label : '' }),
    });
    bar.append(field('Product', prod));
  }
  if (Object.keys(f).some((k) => f[k] && !['from', 'to'].includes(k))) {
    bar.append(h('button', { class: 'btn ghost small', onclick: () => onChange({ from: f.from, to: f.to }) }, 'Clear filters'));
  }
  return bar;
}

function kpi(label, value, sub, href, cls) {
  const tag = href ? 'a' : 'div';
  return h(tag, { class: `kpi ${cls || ''}`, href: href || null },
    h('span', { class: 'kpi-label' }, label), h('span', { class: 'kpi-value num' }, value), sub ? h('span', { class: 'kpi-sub' }, sub) : null);
}

const recordFilters = (f, extra = {}) => qs(Object.assign({ from: f.from, to: f.to, channel: f.channel, category_id: f.category_id, product_id: f.product_id, supplier_id: f.supplier_id }, extra));

export async function dashboardView() {
  const q = hashQuery();
  if (!('from' in q)) {
    const m = datePresets().find((p) => p.key === 'month');
    q.from = m.from; q.to = m.to;
  }
  const f = q;
  const apiF = { from: f.from, to: f.to, channel: f.channel, category_id: f.category_id, product_id: f.product_id, supplier_id: f.supplier_id };
  const d = await api.get('/api/dashboard', apiF);
  const k = d.kpis;
  const root = h('div');
  const rerender = (nf) => { setHashQuery(nf); state.rerender(); };
  const rf = (extra) => recordFilters(f, extra);
  const periodLabel = f.from || f.to ? `${fmt.date(f.from) || 'start'} – ${fmt.date(f.to) || 'today'}` : 'All time';

  root.append(
    pageHead('Dashboard', `${state.shopName} · ${periodLabel}`, [
      linkBtn('#/purchases/new', 'New purchase', '', 'plus'),
      linkBtn('#/sales/new', 'New sale', 'primary', 'plus')]),
    filterBar(f, rerender));

  if (d.expenses_filtered_note) {
    root.append(h('div', { class: 'notice', style: { marginBottom: '14px' } },
      'Product / category / channel / supplier filters apply to sales, COGS and stock. Operating expenses are business-wide and are not split by those filters, so net profit here subtracts all expenses for the period.'));
  }

  root.append(h('div', { class: 'kpis' },
    kpi("Today's sales", fmt.inr(k.todays_sales), `${k.todays_invoices} invoice(s) · billed incl. GST`, `#/sales${qs({ from: state.today, to: state.today, channel: f.channel })}`),
    kpi('This month revenue', fmt.inr(k.monthly_revenue), 'Net sales, excl. GST', `#/sales${qs({ from: state.today.slice(0, 8) + '01', to: state.today, channel: f.channel })}`),
    kpi('Net sales (period)', fmt.inr(k.net_sales), 'Gross − discounts − returns', `#/sales${rf()}`),
    kpi('Retail revenue', fmt.inr(k.retail_revenue), 'Selected period', `#/sales${rf({ channel: 'retail' })}`),
    kpi('Wholesale revenue', fmt.inr(k.wholesale_revenue), 'Selected period', `#/sales${rf({ channel: 'wholesale' })}`),
    kpi('Gross profit', fmt.inr(k.gross_profit), `Net sales − COGS (${fmt.inr0(k.cogs)}) · ${fmt.pct(k.gross_margin)}`, `#/profit${rf()}`),
    kpi('Net operating profit', fmt.inr(k.net_operating_profit), `After expenses${k.writeoffs ? ' & write-offs' : ''}`, `#/profit${rf()}`, k.net_operating_profit < 0 ? 'neg' : ''),
    kpi('Profit margin', fmt.pct(k.profit_margin), `Net profit ÷ net sales · gross ${fmt.pct(k.gross_margin)}`, `#/profit${rf()}`),
    kpi('Operating expenses', fmt.inr(k.total_operating_expenses), 'Selected period', `#/expenses${qs({ from: f.from, to: f.to })}`),
    kpi('Total purchase value', fmt.inr(k.total_purchase_value), 'Landed cost, selected period', `#/purchases${rf()}`),
    kpi('Current inventory value', fmt.inr(k.current_inventory_value), 'At cost, right now', `#/inventory${qs({ category_id: f.category_id, supplier_id: f.supplier_id })}`),
    kpi('Units in stock', fmt.num(k.total_units_in_stock), 'Right now', `#/inventory${qs({ category_id: f.category_id, supplier_id: f.supplier_id })}`),
    kpi('Supplier outstanding', fmt.inr(k.supplier_outstanding), 'You owe suppliers', '#/suppliers'),
    kpi('Customer outstanding', fmt.inr(k.customer_outstanding), 'Customers owe you', '#/customers'),
    can('owner') ? kpi('Total capital invested', fmt.inr(k.total_capital_invested), 'Owner & partner contributions', '#/capital', 'group-cap') : null,
    can('owner') ? kpi('Cash & bank', fmt.inr(k.cash_and_bank), 'Recorded balances', '#/capital', 'group-cap') : null,
  ));

  // ---- charts
  const periodClick = (row) => {
    const p = row.period;
    const range = p.length === 7 ? { from: `${p}-01`, to: lastDay(p) } : { from: p, to: p };
    location.hash = '#/sales' + recordFilters(Object.assign({}, f, range));
  };
  const xFmt = fmt.month;
  const trendSeries = [
    { key: 'net_sales', label: 'Net sales', color: COLORS.s1 },
    { key: 'gross_profit', label: 'Gross profit', color: COLORS.s3 },
    { key: 'net_profit', label: 'Net operating profit', color: COLORS.s2 },
  ];
  const chSeries = [{ key: 'retail', label: 'Retail', color: COLORS.retail }, { key: 'wholesale', label: 'Wholesale', color: COLORS.wholesale }];
  const catSeries = [{ key: 'net_sales', label: 'Net sales', color: COLORS.s1 }, { key: 'gross_profit', label: 'Gross profit', color: COLORS.s3 }];
  const cash = d.cashflow.map((m) => Object.assign({}, m, {
    period: m.month,
    inflow: m.capital_in + m.receipts + Math.max(0, m.loans_net),
    outflow: m.supplier_payments + m.expenses + m.withdrawals + m.refunds + m.tax_paid + Math.max(0, -m.loans_net),
    _extra: [{ label: 'Net cash flow', value: fmt.inr(m.net_cash_flow) }],
  }));
  const cashSeries = [{ key: 'inflow', label: 'Money in', color: COLORS.s1 }, { key: 'outflow', label: 'Money out', color: COLORS.s2 }];
  const unit = d.granularity === 'day' ? 'Daily' : 'Monthly';

  const tbl = (cols, rows) => () => table(cols, rows);
  const money = (key, label) => ({ key, label, num: true, render: (r) => fmt.inr(r[key]) });

  root.append(h('h2', { class: 'section-title' }, 'Trends'), h('div', { class: 'charts' },
    chartCard({
      title: 'Revenue and profit', sub: `${unit} · click a point to see its sales`, wide: true,
      legendEl: legend(trendSeries, 'line'),
      chart: lineChart({ data: d.trend, series: trendSeries, xFmt, onClick: periodClick }),
      tableFn: tbl([{ key: 'period', label: 'Period', render: (r) => xFmt(r.period) }, money('net_sales', 'Net sales'), money('gross_profit', 'Gross profit'), money('expenses', 'Expenses'), money('net_profit', 'Net profit')], d.trend),
    }),
    chartCard({
      title: 'Retail vs wholesale', sub: `${unit} net sales · Retail ${fmt.inr0(d.channels.retail.net_sales)} · Wholesale ${fmt.inr0(d.channels.wholesale.net_sales)}`,
      legendEl: legend(chSeries),
      chart: columnChart({ data: d.trend, series: chSeries, xFmt, onClick: periodClick }),
      tableFn: () => table([{ key: 'label', label: 'Channel', render: (r) => fmt.channel(r.label) }, { key: 'invoices', label: 'Invoices', num: true },
        { key: 'units_sold', label: 'Units', num: true, render: (r) => fmt.num(r.units_sold) }, money('net_sales', 'Net sales'), money('gross_profit', 'Gross profit'),
        { key: 'margin', label: 'Margin', num: true, render: (r) => fmt.pct(r.margin) }], ['retail', 'wholesale'].map((c) => d.channels[c]),
      { onRow: (r) => { location.hash = '#/sales' + rf({ channel: r.label }); } }),
    }),
    chartCard({
      title: 'Category-wise revenue and profit', sub: 'Click a category to see its sales',
      legendEl: legend(catSeries),
      chart: hbarChart({ data: d.by_category, series: catSeries, onClick: (r) => { location.hash = '#/sales' + rf({ category_id: r.id }); } }),
      tableFn: tbl([{ key: 'label', label: 'Category' }, money('net_sales', 'Net sales'), money('cogs', 'COGS'), money('gross_profit', 'Gross profit'), { key: 'margin', label: 'Margin', num: true, render: (r) => fmt.pct(r.margin) }], d.by_category),
    }),
    chartCard({
      title: 'Top-selling products', sub: 'By units sold (net of returns)',
      chart: hbarChart({
        data: d.top_products.map((p) => Object.assign({}, p, { units: p.units_sold - p.units_returned, _extra: [{ label: 'Net sales', value: fmt.inr(p.net_sales) }, { label: 'Gross profit', value: fmt.inr(p.gross_profit) }] })),
        series: [{ key: 'units', label: 'Units sold', color: COLORS.s1 }], valFmt: fmt.num, shortFmt: fmt.compactNum,
        onClick: (r) => { location.hash = '#/sales' + rf({ product_id: r.id }); },
      }),
      tableFn: tbl([{ key: 'label', label: 'Product' }, { key: 'units_sold', label: 'Units', num: true, render: (r) => fmt.num(r.units_sold - r.units_returned) }, money('net_sales', 'Net sales'), money('gross_profit', 'Gross profit')], d.top_products),
    }),
    chartCard({
      title: 'Supplier-wise purchase value', sub: 'Landed cost in period · click to see bills',
      chart: hbarChart({
        data: d.by_supplier.map((x) => Object.assign({}, x, { label: x.name, _extra: [{ label: 'Units', value: fmt.num(x.units) }, { label: 'Bills', value: x.bills }] })),
        series: [{ key: 'value', label: 'Purchase value', color: COLORS.s1 }],
        onClick: (r) => { location.hash = '#/purchases' + qs({ from: f.from, to: f.to, supplier_id: r.id }); },
        emptyText: 'No purchases in this period',
      }),
      tableFn: tbl([{ key: 'name', label: 'Supplier' }, { key: 'bills', label: 'Bills', num: true }, { key: 'units', label: 'Units', num: true, render: (r) => fmt.num(r.units) }, money('value', 'Value')], d.by_supplier),
    }),
    chartCard({
      title: 'Inventory value by category', sub: 'At cost, right now · click to open stock',
      chart: hbarChart({
        data: d.inventory_by_category.map((x) => Object.assign({}, x, { label: x.name, _extra: [{ label: 'Units', value: fmt.num(x.qty) }] })),
        series: [{ key: 'value', label: 'Value at cost', color: COLORS.s1 }],
        onClick: (r) => { location.hash = '#/inventory' + qs({ category_id: r.id }); },
        emptyText: 'No stock recorded yet',
      }),
      tableFn: tbl([{ key: 'name', label: 'Category' }, { key: 'qty', label: 'Units', num: true, render: (r) => fmt.num(r.qty) }, money('value', 'Value at cost')], d.inventory_by_category),
    }),
    chartCard({
      title: 'Monthly investment and cash flow', sub: 'In: capital, receipts, loans · Out: suppliers, expenses, withdrawals, refunds, GST', wide: true,
      legendEl: legend(cashSeries),
      chart: columnChart({ data: cash, series: cashSeries, mode: 'group', onClick: can('owner') ? () => { location.hash = '#/capital'; } : null }),
      tableFn: tbl([{ key: 'month', label: 'Month', render: (r) => fmt.month(r.month) }, money('capital_in', 'Capital in'), money('loans_net', 'Loans (net)'), money('receipts', 'Customer receipts'),
        money('supplier_payments', 'Paid suppliers'), money('expenses', 'Expenses'), money('withdrawals', 'Withdrawals'), money('refunds', 'Refunds'), money('net_cash_flow', 'Net cash flow')], cash),
    }),
  ));
  return root;
}

function lastDay(month) {
  const [y, m] = month.split('-').map(Number);
  const d = new Date(y, m, 0).getDate();
  return `${month}-${String(d).padStart(2, '0')}`;
}

export async function homeView() {
  const d = await api.get('/api/home');
  const root = h('div');
  root.append(pageHead(`Hello, ${state.user.full_name}`, state.shopName, [
    can('purchases.create') ? linkBtn('#/purchases/new', 'New purchase', '', 'plus') : null,
    can('sales.create') ? linkBtn('#/sales/new', 'New sale', 'primary', 'plus') : null].filter(Boolean)));
  root.append(h('div', { class: 'kpis' },
    kpi('My sales today', fmt.inr(d.my_sales_today.amount), `${d.my_sales_today.count} invoice(s)`, '#/sales'),
    d.stock ? kpi('Units in stock', fmt.num(d.stock.units), null, '#/inventory') : null,
    d.stock ? kpi('Low stock items', String(d.stock.low), 'At or below reorder level', '#/inventory?tab=low') : null,
    d.stock ? kpi('Out of stock items', String(d.stock.out), null, '#/inventory?tab=low') : null));
  root.append(h('div', { class: 'notice', style: { marginTop: '18px' } },
    'Your account has staff access. Financial figures such as profit, capital and cost prices are visible to the owner only unless the owner grants access.'));
  return root;
}

import {
  h, api, state, fmt, can, pageHead, card, table, hashQuery, setHashQuery, field, input, numInput, dateInput, select,
  combobox, variantSource, showError, toast, modal, busy, clientRef, confirmVoid, dl, datePresets,
} from '../core.js';

const TABS = [
  ['overview', 'Overview'], ['stock', 'Stock list'], ['low', 'Low / out of stock'], ['movement', 'Stock movement'], ['adjustments', 'Damage & corrections'],
];

function statusBadge(st) {
  if (st === 'out') return h('span', { class: 'badge bad' }, 'Out of stock');
  if (st === 'low') return h('span', { class: 'badge warn' }, 'Low stock');
  return h('span', { class: 'badge good' }, 'In stock');
}

export async function inventoryView() {
  const f = hashQuery();
  const tab = f.tab || 'overview';
  const showCost = can('inventory.cost');
  const apiF = { category_id: f.category_id, supplier_id: f.supplier_id, q: f.q, from: f.from, to: f.to, days: f.days };
  const d = await api.get('/api/inventory', apiF);
  const t = d.totals;
  const go = (patch) => { setHashQuery(Object.assign({}, f, patch)); state.rerender(); };
  const root = h('div');
  root.append(pageHead('Inventory', 'Live stock from purchases, sales, returns and adjustments', [
    can('inventory.adjust') ? h('button', { class: 'btn', onclick: () => adjustmentModal() }, 'Record damage / correction') : null,
    can('owner') ? h('a', { class: 'btn', href: '#/setup?step=stock' }, 'Opening stock') : null].filter(Boolean)));

  root.append(h('div', { class: 'kpis', style: { marginBottom: '16px' } },
    kpi('Units in stock', fmt.num(t.units)),
    showCost ? kpi('Inventory value at cost', fmt.inr(t.value)) : null,
    kpi('Products · variants', `${t.products} · ${t.variants}`),
    kpi('Low stock', String(t.low), null, () => go({ tab: 'low' })),
    kpi('Out of stock', String(t.out), null, () => go({ tab: 'low' })),
    kpi('Purchased', fmt.num(t.purchased), periodText(f)), kpi('Sold', fmt.num(t.sold), periodText(f)),
    kpi('Returned', fmt.num(t.returned), periodText(f))));

  const cat = select('category_id', [{ value: '', label: 'All categories' }].concat(state.categories.map((c) => ({ value: c.id, label: c.name }))), f.category_id || '', { onchange: (e) => go({ category_id: e.target.value }) });
  const search = input('q', { placeholder: 'Search product or SKU', value: f.q || '' });
  search.addEventListener('change', () => go({ q: search.value }));
  root.append(h('div', { class: 'tabs' }, TABS.map(([k, label]) => h('button', { class: tab === k ? 'on' : '', onclick: () => go({ tab: k }) }, label))));
  root.append(h('div', { class: 'filters' }, h('div', { style: { minWidth: '180px' } }, cat), h('div', { style: { flex: '1 1 220px', maxWidth: '340px' } }, search),
    f.supplier_id ? h('button', { class: 'btn small', onclick: () => go({ supplier_id: '' }) }, 'Clear supplier filter') : null));

  const ledger = (r) => { location.hash = `#/inventory/ledger/${r.id}`; };
  const variantCols = [
    { label: 'Product', render: (r) => h('div', null, r.label, h('div', { class: 'muted small' }, r.sku)) },
    { label: 'Category', key: 'category' },
    { label: 'In stock', num: true, render: (r) => `${fmt.num(r.stock_qty)} ${r.unit}` },
    showCost ? { label: 'Avg cost', num: true, render: (r) => fmt.inr(r.avg_cost) } : null,
    showCost ? { label: 'Value', num: true, render: (r) => fmt.inr(r.stock_value) } : null,
    { label: 'Retail', num: true, render: (r) => fmt.inr(r.retail_price) },
    { label: `Sold (${d.days}d)`, num: true, render: (r) => fmt.num(r.sold_recent) },
    { label: 'Last sale', render: (r) => fmt.date(r.last_sale) },
    { label: 'Status', render: (r) => statusBadge(r.status) },
  ].filter(Boolean);

  if (tab === 'overview') {
    const productCols = [
      { label: 'Product', key: 'product_name' }, { label: 'Category', key: 'category' },
      { label: 'In stock', num: true, render: (r) => fmt.num(r.stock_qty) },
      { label: `Sold (${d.days}d)`, num: true, render: (r) => fmt.num(r.sold_recent) },
      { label: 'Sell-through', num: true, render: (r) => fmt.pct(r.sell_through) },
      { label: 'Days of cover', num: true, render: (r) => r.days_of_cover === null ? '—' : fmt.num(r.days_of_cover) },
      { label: 'Last sold', render: (r) => r.days_since_sale === null ? 'Never' : `${r.days_since_sale}d ago` },
    ];
    const days = select('days', [7, 30, 60, 90, 180].map((n) => ({ value: n, label: `Last ${n} days` })), d.days, { onchange: (e) => go({ days: e.target.value }) });
    root.append(h('div', { class: 'stack' },
      card('Category-wise inventory', table([
        { label: 'Category', key: 'category' }, { label: 'Products', num: true, key: 'products' },
        { label: 'Units', num: true, render: (r) => fmt.num(r.stock_qty) },
        showCost ? { label: 'Value at cost', num: true, render: (r) => fmt.inr(r.stock_value) } : null,
      ].filter(Boolean), d.categories, { onRow: (r) => go({ category_id: r.category_id, tab: 'stock' }) })),
      h('div', { class: 'row' }, h('span', { class: 'small muted' }, 'Fast / slow movers based on'), h('div', { style: { width: '170px' } }, days)),
      h('div', { class: 'grid-2' },
        card('Fast-selling products', table(productCols, d.fast, { empty: 'No sales in this window.', onRow: (r) => { location.hash = `#/products/${r.product_id}`; } })),
        card('Slow-moving products', table(productCols, d.slow, { empty: 'No stock on hand.', onRow: (r) => { location.hash = `#/products/${r.product_id}`; } }),
          { sub: 'In stock, fewest recent sales' })),
      card('Supplier-wise inventory purchases', table([
        { label: 'Supplier', key: 'name' }, { label: 'Bills', num: true, key: 'bills' }, { label: 'SKUs', num: true, key: 'skus' },
        { label: 'Units purchased', num: true, render: (r) => fmt.num(r.units) },
        showCost ? { label: 'Purchase value', num: true, render: (r) => fmt.inr(r.value) } : null,
      ].filter(Boolean), d.by_supplier, { onRow: (r) => go({ supplier_id: r.id, tab: 'stock' }), empty: 'No purchases recorded.' }), { sub: 'Click to see the stock bought from a supplier' })));
  } else if (tab === 'stock') {
    root.append(card(null, table(variantCols, d.variants, { onRow: ledger, empty: 'No products match.' })));
  } else if (tab === 'low') {
    const low = d.variants.filter((v) => v.status !== 'ok').sort((a, b) => a.stock_qty - b.stock_qty);
    root.append(card(null, table(variantCols, low, { onRow: ledger, empty: 'Nothing is low or out of stock.' })));
  } else if (tab === 'movement') {
    const presets = datePresets();
    root.append(h('div', { class: 'filters' }, h('div', { class: 'presets' }, presets.map((p) => h('button', {
      class: `btn small ${(f.from || '') === p.from && (f.to || '') === p.to ? 'primary' : ''}`, onclick: () => go({ from: p.from, to: p.to }),
    }, p.label)))));
    root.append(card(`Units purchased, sold, returned and closing stock · ${periodText(f)}`, table([
      { label: 'Product', key: 'label' }, { label: 'Category', key: 'category' },
      { label: 'Opening', num: true, render: (r) => fmt.num(r.opening) }, { label: 'Purchased', num: true, render: (r) => fmt.num(r.purchased) },
      { label: 'Sold', num: true, render: (r) => fmt.num(r.sold) }, { label: 'Returned', num: true, render: (r) => fmt.num(r.returned) },
      { label: 'Adjusted', num: true, render: (r) => fmt.num(r.adjusted) }, { label: 'Closing', num: true, render: (r) => fmt.num(r.closing) },
      showCost ? { label: 'Closing value', num: true, render: (r) => fmt.inr(r.closing_value) } : null,
    ].filter(Boolean), d.movement, { onRow: (r) => { location.hash = `#/products/${r.product_id}`; } })));
  } else if (tab === 'adjustments') {
    const adj = can('inventory.adjust') || can('inventory.cost') ? await api.get('/api/adjustments', { from: f.from, to: f.to }) : [];
    root.append(card(null, table([
      { label: 'Date', render: (r) => fmt.date(r.adj_date) }, { label: 'Product', key: 'label' },
      { label: 'Reason', render: (r) => r.reason }, { label: 'Qty', num: true, render: (r) => fmt.num(r.qty) },
      showCost ? { label: 'Value', num: true, render: (r) => fmt.inr(r.value) } : null,
      { label: 'Notes', key: 'notes' }, { label: 'By', key: 'created_by_name' },
      { label: '', cls: 'keep', render: (r) => r.status === 'void' ? fmt.status('void') : (can('transactions.void') ? h('button', { class: 'btn small danger', onclick: (e) => { e.stopPropagation(); confirmVoid('stock_adjustments', r.id, 'adjustment', state.rerender); } }, 'Void') : '') },
    ].filter(Boolean), adj, { empty: 'No damage or stock corrections recorded.' })));
  }
  return root;
}

function periodText(f) {
  return f.from || f.to ? `${fmt.date(f.from) || 'start'} – ${fmt.date(f.to) || 'today'}` : 'All time';
}

function kpi(label, value, sub, onclick) {
  return h(onclick ? 'button' : 'div', { class: 'kpi', onclick, style: onclick ? { cursor: 'pointer', textAlign: 'left', font: 'inherit' } : null },
    h('span', { class: 'kpi-label' }, label), h('span', { class: 'kpi-value num' }, value), sub ? h('span', { class: 'kpi-sub' }, sub) : null);
}

export function adjustmentModal(variant) {
  let v = variant || null;
  const info = h('div', { class: 'hint' });
  const combo = combobox({ name: 'variant_id', placeholder: 'Search product / SKU', source: variantSource(), onPick: (it) => { v = it.data; info.textContent = `${fmt.num(it.data.stock_qty)} ${it.data.unit} in stock`; } });
  if (variant) combo.pick({ value: variant.id, label: variant.label, data: variant });
  const reason = select('reason', [{ value: 'damaged', label: 'Damaged' }, { value: 'lost', label: 'Lost / theft' }, { value: 'correction', label: 'Stock count correction' }, { value: 'other', label: 'Other' }], 'damaged');
  const direction = select('direction', [{ value: 'out', label: 'Reduce stock' }, { value: 'in', label: 'Increase stock (found / recount)' }], 'out');
  reason.addEventListener('change', () => { if (['damaged', 'lost'].includes(reason.value)) direction.value = 'out'; });
  const qty = numInput('qty');
  const date = dateInput('adj_date');
  const notes = input('notes');
  const ref = clientRef();
  const body = h('div', { class: 'form-grid' }, h('div', { class: 'span-2' }, field('Product', combo, { required: true }), info),
    field('Reason', reason), field('Direction', direction), field('Quantity', qty, { required: true }), field('Date', date), field('Notes', notes, { class: 'span-2' }),
    h('div', { class: 'hint span-all' }, 'Reductions are valued at current cost and shown as stock write-offs in profit. Increases enter at current average cost.'));
  modal({ title: 'Damage / stock correction', body, wide: true, actions: [
    (m) => h('button', { class: 'btn', onclick: m.close }, 'Cancel'),
    (m) => h('button', { class: 'btn primary', onclick: async (e) => busy(e.target, async () => {
      try {
        await api.post('/api/adjustments', { client_ref: ref, variant_id: v && v.id, reason: reason.value, direction: direction.value, qty: qty.value, adj_date: date.value, notes: notes.value });
        m.close(); toast('Stock adjusted'); state.rerender();
      } catch (ex) { showError(body, ex); }
    }) }, 'Save'),
  ] });
}

export async function ledgerView(id) {
  const d = await api.get(`/api/inventory/ledger/${id}`);
  const v = d.variant;
  const showCost = 'stock_value' in v;
  const kindLabel = { opening: 'Opening stock', purchase: 'Purchase', sale: 'Sale', return_in: 'Customer return', adjust: 'Adjustment' };
  const link = (m) => ({ purchases: `#/purchases/${m.ref_id}`, sales: `#/sales/${m.ref_id}` })[m.ref_table];
  return h('div', null,
    pageHead(`Stock ledger — ${v.label}`, `${v.sku} · ${v.category} · ${fmt.num(v.stock_qty)} ${v.unit} in stock${showCost ? ` · value ${fmt.inr(v.stock_value)}` : ''}`, [
      h('a', { class: 'btn', href: `#/products/${v.product_id}` }, 'Product'),
      can('inventory.adjust') ? h('button', { class: 'btn', onclick: () => adjustmentModal({ id: v.id, label: v.label, stock_qty: v.stock_qty, unit: v.unit }) }, 'Adjust') : null].filter(Boolean)),
    card(null, table([
      { label: 'Date', render: (m) => fmt.date(m.move_date) },
      { label: 'Type', render: (m) => kindLabel[m.kind] || m.kind },
      { label: 'Reference', render: (m) => link(m) ? h('a', { href: link(m) }, m.reference || '') : (m.reference || '') },
      { label: 'In', num: true, render: (m) => m.qty > 0 ? fmt.num(m.qty) : '' },
      { label: 'Out', num: true, render: (m) => m.qty < 0 ? fmt.num(-m.qty) : '' },
      showCost ? { label: 'Unit cost', num: true, render: (m) => fmt.inr(m.unit_cost) } : null,
      showCost ? { label: 'Value', num: true, render: (m) => fmt.inr(m.value) } : null,
      { label: 'Balance qty', num: true, render: (m) => fmt.num(m.balance_qty) },
      showCost ? { label: 'Balance value', num: true, render: (m) => fmt.inr(m.balance_value) } : null,
    ].filter(Boolean), d.moves, { empty: 'No stock movements yet.' })),
    h('p', { class: 'hint', style: { marginTop: '10px' } }, `Cost of sales is calculated with the ${state.settings.costing_method === 'FIFO' ? 'FIFO' : 'weighted-average'} method from the actual landed cost of purchases.`));
}

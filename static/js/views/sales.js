import {
  h, api, state, fmt, can, isOwner, pageHead, linkBtn, card, table, hashQuery, setHashQuery, field, input, numInput,
  dateInput, select, methodSelect, combobox, variantSource, showError, clearErrors, toast, modal, confirmVoid, busy,
  clientRef, round2, dl, icon,
} from '../core.js';
import { filterBar } from './dashboard.js';

// ---------------------------------------------------------------- list
export async function salesList() {
  const f = hashQuery();
  const rows = await api.get('/api/sales', f);
  const final = rows.filter((r) => r.status === 'final');
  const sum = (k) => round2(final.reduce((a, r) => a + (r[k] || 0), 0));
  const due = round2(final.reduce((a, r) => a + r.total_amount - r.amount_received, 0));
  const root = h('div');
  root.append(pageHead('Sales', 'Every invoice, retail and wholesale, with its channel as entered', [
    can('sales.create') ? linkBtn('#/sales/new', 'New sale', 'primary', 'plus') : null].filter(Boolean)));
  root.append(filterBar(f, (nf) => { setHashQuery(nf); state.rerender(); }, { supplier: can('purchases.view') }));
  const search = input('q', { placeholder: 'Search invoice no. or customer', value: f.q || '' });
  search.addEventListener('change', () => { setHashQuery(Object.assign({}, f, { q: search.value })); state.rerender(); });
  const unpaid = h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: !!f.unpaid, onchange: (e) => { setHashQuery(Object.assign({}, f, { unpaid: e.target.checked ? '1' : '' })); state.rerender(); } }), 'Only with balance due');
  root.append(h('div', { class: 'row', style: { marginBottom: '12px' } }, h('div', { style: { flex: '1 1 260px', maxWidth: '360px' } }, search), unpaid));
  root.append(card(null, table([
    { label: 'Date', render: (r) => fmt.date(r.sale_date), cls: 'nowrap' },
    { label: 'Invoice', render: (r) => h('span', null, r.invoice_no, ' ', fmt.status(r.status)), cls: 'keep' },
    { label: 'Channel', render: (r) => fmt.channel(r.channel), cls: 'keep' },
    { label: 'Customer', render: (r) => r.customer_name || h('span', { class: 'muted' }, 'Walk-in') },
    { label: 'Units', num: true, render: (r) => fmt.num(r.units) },
    { label: 'Total', num: true, render: (r) => fmt.inr(r.total_amount) },
    { label: 'Received', num: true, render: (r) => fmt.inr(r.amount_received) },
    { label: 'Due', num: true, render: (r) => { const d = round2(r.total_amount - r.amount_received); return d > 0 && r.status === 'final' ? h('span', { class: 'neg' }, fmt.inr(d)) : '—'; } },
    { label: 'Returns', num: true, render: (r) => r.refunded ? fmt.inr(r.refunded) : '—' },
    { label: 'Staff', render: (r) => r.staff_name || '' },
  ], rows, {
    onRow: (r) => { location.hash = `#/sales/${r.id}`; },
    empty: 'No sales match these filters.',
    emptyAction: can('sales.create') ? h('div', null, linkBtn('#/sales/new', 'Record a sale', 'primary')) : null,
  })));
  if (final.length) {
    root.append(h('div', { class: 'row muted small', style: { marginTop: '10px' } },
      `${final.length} invoice(s) · Billed ${fmt.inr(sum('total_amount'))} · Received ${fmt.inr(sum('amount_received'))} · Due ${fmt.inr(due)} · Net of GST ${fmt.inr(sum('net_amount'))}`));
  }
  return root;
}

// ---------------------------------------------------------------- form
export function saleLine(qty, price, discount, rate, inclusive) {
  // Mirrors shop/services.py sale_line()
  const lineValue = qty * price - discount;
  const r = rate / 100;
  let gross, net, tax;
  if (inclusive) {
    gross = round2(qty * price / (1 + r)); net = round2(lineValue / (1 + r)); tax = round2(lineValue - net);
  } else {
    gross = round2(qty * price); net = round2(lineValue); tax = round2(net * r);
  }
  return { gross, discount: round2(gross - net), net, tax, total: round2(net + tax) };
}

const LAST_CHANNEL = 'gs.lastChannel';
function lastChannel() { try { return localStorage.getItem(LAST_CHANNEL); } catch (e) { return null; } }
function rememberChannel(c) { try { localStorage.setItem(LAST_CHANNEL, c); } catch (e) { /* ignore */ } }

export async function saleForm() {
  const [{ invoice_no }, staff] = await Promise.all([api.get('/api/sales/next-invoice'), isOwner() ? api.get('/api/staff') : Promise.resolve([])]);
  const st = state.settings;
  const ref = clientRef();
  let channel = lastChannel();
  if (channel !== 'retail' && channel !== 'wholesale') channel = null;
  let receivedTouched = false;
  let customer = null;
  const lines = [];

  const root = h('div');
  const form = h('div', { class: 'stack' });
  const dateEl = dateInput('sale_date');
  const invEl = input('invoice_no', { value: invoice_no });
  const inclusiveEl = h('input', { type: 'checkbox', checked: st.prices_include_tax === '1' });

  // channel picker — explicit, never derived from the date
  const pick = h('div', { class: 'channel-pick', 'data-field': 'channel', role: 'radiogroup', 'aria-label': 'Sales channel' });
  const chanBtn = (c, title, sub) => h('button', { type: 'button', class: c, role: 'radio', onclick: () => setChannel(c) },
    h('span', { class: 'dot' }), h('span', null, h('strong', null, title), h('span', { class: 'small muted' }, sub)));
  const btnRetail = chanBtn('retail', 'Retail', 'Walk-in customers, retail price');
  const btnWhole = chanBtn('wholesale', 'Wholesale', 'Bulk buyers, wholesale price');
  pick.append(btnRetail, btnWhole);
  const chanNote = h('div', { class: 'hint' });

  const custBox = combobox({
    name: 'customer_id', placeholder: 'Walk-in customer (optional) — search name or phone',
    source: async (q) => (await api.get('/api/customers', { q })).map((c) => ({ value: c.id, label: c.name, sub: [c.phone, c.outstanding > 0 ? `due ${fmt.inr0(c.outstanding)}` : ''].filter(Boolean).join(' · '), data: c })),
    onPick: (it) => { customer = it.data; custClear.classList.remove('hidden'); updateTotals(); },
    action: { label: 'Add new customer', run: (text, pickFn) => newCustomerModal(text, channel, pickFn) },
  });
  const custClear = h('button', { class: 'btn ghost small hidden', type: 'button', onclick: () => { custBox.clear(); customer = null; custClear.classList.add('hidden'); updateTotals(); } }, 'Clear');

  const staffEl = isOwner() ? select('staff_user_id', staff.map((u) => ({ value: u.id, label: u.full_name })), state.user.id) : null;

  const tbody = h('tbody');
  const linesTable = h('table', { class: 'lines' }, h('thead', null, h('tr', null,
    h('th', null, 'Product / SKU'), h('th', null, 'Category'), h('th', { class: 'num' }, 'Qty'), h('th', { class: 'num' }, 'Price / unit'),
    h('th', { class: 'num' }, 'Discount ₹'), h('th', { class: 'num' }, 'GST %'), h('th', { class: 'num' }, 'Line total'), h('th', null, ''))), tbody);

  const tot = { gross: h('span'), discount: h('span'), net: h('span'), tax: h('span'), total: h('span'), due: h('span') };
  const receivedEl = numInput('amount_received');
  receivedEl.addEventListener('input', () => { receivedTouched = true; updateTotals(); });
  const methodEl = methodSelect('payment_method');
  const notesEl = h('textarea', { name: 'notes', 'data-field': 'notes', placeholder: 'Optional notes' });
  const saveBtn = h('button', { class: 'btn primary', type: 'button', onclick: () => save() });
  const dueNote = h('div', { class: 'hint' });

  function setChannel(c) {
    channel = c;
    rememberChannel(c);
    btnRetail.classList.toggle('on', c === 'retail'); btnRetail.setAttribute('aria-checked', String(c === 'retail'));
    btnWhole.classList.toggle('on', c === 'wholesale'); btnWhole.setAttribute('aria-checked', String(c === 'wholesale'));
    pick.classList.remove('invalid-pick');
    pick.querySelectorAll('.field-error').forEach((e) => e.remove());
    chanNote.textContent = c ? `This invoice will be saved as ${c === 'retail' ? 'RETAIL' : 'WHOLESALE'}. Change it above if needed.` : 'Choose Retail or Wholesale for this invoice.';
    for (const l of lines) if (l.variant && !l.priceTouched) { l.price.value = priceFor(l.variant); }
    updateTotals();
  }
  const priceFor = (v) => (channel === 'wholesale' ? v.wholesale_price : v.retail_price) || '';

  function addLine() {
    const l = { variant: null, priceTouched: false };
    const i = lines.length;
    l.stock = h('div', { class: 'stock-hint' });
    l.cat = h('span', { class: 'muted small' });
    l.combo = combobox({
      name: `items.${i}.variant_id`, placeholder: 'Search product, SKU, size, colour…', source: variantSource({ in_stock: 1 }),
      onPick: (it) => {
        l.variant = it.data;
        l.cat.textContent = it.data.category;
        l.stock.textContent = `${fmt.num(it.data.stock_qty)} ${it.data.unit} in stock · ${it.data.sku}`;
        if (!l.priceTouched) l.price.value = priceFor(it.data);
        if (!l.qty.value) l.qty.value = 1;
        updateTotals();
        if (lines[lines.length - 1] === l) addLine();
        l.qty.focus(); l.qty.select();
      },
    });
    l.qty = numInput(`items.${i}.qty`, { placeholder: '0' });
    l.price = numInput(`items.${i}.unit_price`, { placeholder: '0.00' });
    l.price.addEventListener('input', () => { l.priceTouched = true; });
    l.discount = numInput(`items.${i}.discount`, { placeholder: '0' });
    l.tax = numInput(`items.${i}.tax_rate`, { value: st.default_tax_rate || '0', max: '28' });
    l.total = h('strong', { class: 'num' }, '—');
    [l.qty, l.price, l.discount, l.tax].forEach((el) => el.addEventListener('input', updateTotals));
    l.row = h('tr', null,
      h('td', { class: 'col-product', 'data-label': 'Product' }, l.combo, l.stock),
      h('td', { 'data-label': 'Category' }, l.cat),
      h('td', { class: 'col-num', 'data-label': 'Qty' }, l.qty),
      h('td', { class: 'col-num', 'data-label': 'Price / unit' }, l.price),
      h('td', { class: 'col-num', 'data-label': 'Discount ₹' }, l.discount),
      h('td', { class: 'col-num', 'data-label': 'GST %' }, l.tax),
      h('td', { class: 'num', 'data-label': 'Line total' }, l.total),
      h('td', null, h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Remove line', onclick: () => removeLine(l) }, icon('trash'))));
    lines.push(l);
    tbody.append(l.row);
  }
  function removeLine(l) {
    if (lines.length === 1) { l.combo.clear(); l.variant = null; l.qty.value = ''; l.price.value = ''; l.discount.value = ''; l.stock.textContent = ''; l.cat.textContent = ''; updateTotals(); return; }
    lines.splice(lines.indexOf(l), 1);
    l.row.remove();
    renumber();
    updateTotals();
  }
  function renumber() {
    lines.forEach((l, i) => {
      l.combo.querySelector('input').dataset.field = `items.${i}.variant_id`;
      l.qty.dataset.field = `items.${i}.qty`; l.price.dataset.field = `items.${i}.unit_price`;
      l.discount.dataset.field = `items.${i}.discount`; l.tax.dataset.field = `items.${i}.tax_rate`;
    });
  }

  function totals() {
    const t = { gross: 0, discount: 0, net: 0, tax: 0, total: 0 };
    for (const l of lines) {
      if (!l.variant) continue;
      const r = saleLine(+l.qty.value || 0, +l.price.value || 0, +l.discount.value || 0, +l.tax.value || 0, inclusiveEl.checked);
      l.total.textContent = fmt.inr(r.total);
      for (const k of Object.keys(t)) t[k] += r[k];
    }
    for (const k of Object.keys(t)) t[k] = round2(t[k]);
    return t;
  }
  function updateTotals() {
    const t = totals();
    tot.gross.textContent = fmt.inr(t.gross); tot.discount.textContent = `− ${fmt.inr(t.discount)}`;
    tot.net.textContent = fmt.inr(t.net); tot.tax.textContent = fmt.inr(t.tax); tot.total.textContent = fmt.inr(t.total);
    if (!receivedTouched) receivedEl.value = t.total ? t.total.toFixed(2) : '';
    const due = round2(t.total - (+receivedEl.value || 0));
    tot.due.textContent = fmt.inr(Math.max(0, due));
    dueNote.textContent = due > 0.004 ? (customer ? `₹ ${due.toFixed(2)} will be added to ${customer.name}'s outstanding balance.` : 'A balance due needs a customer — select or add one above.') : '';
    dueNote.className = due > 0.004 && !customer ? 'field-error' : 'hint';
    saveBtn.textContent = channel ? `Save ${channel === 'retail' ? 'retail' : 'wholesale'} sale · ${fmt.inr(t.total)}` : 'Choose Retail or Wholesale to save';
    saveBtn.disabled = !channel;
  }

  async function save() {
    clearErrors(form);
    if (!channel) { pick.classList.add('invalid-pick'); return toast('Select the sales channel: Retail or Wholesale', 'bad'); }
    const items = lines.filter((l) => l.variant).map((l) => ({
      variant_id: l.variant.id, qty: l.qty.value, unit_price: l.price.value, discount: l.discount.value || 0, tax_rate: l.tax.value || 0,
    }));
    const body = {
      client_ref: ref, sale_date: dateEl.value, invoice_no: invEl.value, channel, tax_inclusive: inclusiveEl.checked,
      customer_id: customer ? customer.id : null, items, amount_received: receivedEl.value === '' ? 0 : receivedEl.value,
      payment_method: methodEl.value, notes: notesEl.value, staff_user_id: staffEl ? staffEl.value : null,
    };
    await busy(saveBtn, async () => {
      try {
        const r = await api.post('/api/sales', body);
        toast(`Sale ${invEl.value} saved (${channel})`);
        location.hash = `#/sales/${r.id}`;
      } catch (ex) {
        if (ex.field && ex.field.startsWith('duplicate:')) { location.hash = `#/sales/${ex.field.split(':')[1]}`; return; }
        if (ex.field === 'channel') pick.classList.add('invalid-pick');
        if (ex.field && /^items\.\d+/.test(ex.field)) {
          // server indexes only filled lines; map back to visible rows
          const idx = +ex.field.split('.')[1];
          const filled = lines.filter((l) => l.variant);
          const vis = lines.indexOf(filled[idx]);
          ex.field = ex.field.replace(/^items\.\d+/, `items.${vis}`);
        }
        showError(form, ex);
      }
    });
  }

  inclusiveEl.addEventListener('change', updateTotals);
  addLine();
  form.append(
    card('Invoice', h('div', { class: 'stack' },
      h('div', null, h('div', { class: 'small', style: { fontWeight: 600, marginBottom: '6px' } }, 'Sales channel ', h('span', { class: 'req', style: { color: 'var(--bad)' } }, '*')), pick, chanNote),
      h('div', { class: 'form-grid' },
        field('Sale date', dateEl, { required: true }),
        field('Invoice number', invEl, { hint: 'Auto-numbered; edit if you use printed bill books' }),
        h('div', { class: 'field span-2' }, h('label', { class: 'field' }, h('span', { class: 'lbl' }, 'Customer'), custBox), custClear),
        staffEl ? field('Recorded by (staff)', staffEl) : field('Recorded by', h('input', { value: state.user.full_name, disabled: true }))))),
    card('Items', h('div', null,
      h('div', { class: 'table-wrap' }, linesTable),
      h('div', { class: 'row', style: { marginTop: '10px' } },
        h('button', { class: 'btn small', type: 'button', onclick: addLine }, icon('plus'), 'Add line'),
        h('span', { class: 'spacer' }),
        h('label', { class: 'check' }, inclusiveEl, 'Prices include GST'))), { sub: 'Search by name, SKU, size or colour. Price fills from the retail or wholesale rate.' }),
    card('Payment', h('div', { class: 'grid-2' },
      h('div', { class: 'form-grid' },
        field('Amount received now', receivedEl, { hint: 'Leave the full amount for a paid sale; reduce it for credit' }),
        field('Payment method', methodEl),
        h('div', { class: 'span-all' }, dueNote),
        field('Notes', notesEl, { class: 'span-all' })),
      h('div', { class: 'totals' },
        h('span', null, 'Gross sales (excl. GST)'), h('span', { class: 'num' }, tot.gross),
        h('span', null, 'Discounts'), h('span', { class: 'num' }, tot.discount),
        h('span', null, 'Net sales'), h('span', { class: 'num' }, tot.net),
        h('span', null, 'GST'), h('span', { class: 'num' }, tot.tax),
        h('span', { class: 'grand' }, 'Invoice total'), h('span', { class: 'grand num' }, tot.total),
        h('span', null, 'Balance due'), h('span', { class: 'num' }, tot.due)))),
    h('div', { class: 'form-actions' }, h('a', { class: 'btn', href: '#/sales' }, 'Cancel'), saveBtn));
  root.append(pageHead('New sale', 'Stock is deducted automatically when you save'), form);
  setChannel(channel);
  if (!channel) chanNote.textContent = 'Choose Retail or Wholesale for this invoice — it is never set from the day of the week.';
  if (window.innerWidth > 860) setTimeout(() => lines[0].combo.focus(), 50);
  return root;
}

export function newCustomerModal(text, channel, pickFn) {
  const name = input('name', { value: /\d{5,}/.test(text) ? '' : text });
  const phone = input('phone', { value: /\d{5,}/.test(text) ? text : '', inputmode: 'tel' });
  const kind = select('kind', [{ value: 'retail', label: 'Retail' }, { value: 'wholesale', label: 'Wholesale' }], channel || 'retail');
  const address = input('address');
  const body = h('div', { class: 'form-grid' }, field('Name', name, { required: true }), field('Phone', phone), field('Type', kind), field('Address', address));
  modal({ title: 'New customer', body, actions: [
    (m) => h('button', { class: 'btn', onclick: m.close }, 'Cancel'),
    (m) => h('button', { class: 'btn primary', onclick: async (e) => busy(e.target, async () => {
      try {
        const r = await api.post('/api/customers', { name: name.value, phone: phone.value, kind: kind.value, address: address.value });
        m.close();
        const c = { id: r.id, name: name.value, phone: phone.value, outstanding: 0 };
        pickFn({ value: r.id, label: c.name, data: c });
      } catch (ex) { showError(body, ex); }
    }) }, 'Add customer'),
  ] });
}

// ---------------------------------------------------------------- detail
export async function saleDetail(id) {
  const s = await api.get(`/api/sales/${id}`);
  const root = h('div');
  const due = round2(s.total_amount - s.payments.filter((p) => p.status === 'final').reduce((a, p) => a + p.amount, 0)
    - s.returns.filter((r) => r.status === 'final' && r.refund_mode === 'credit').reduce((a, r) => a + r.total_refund, 0));
  const showCost = 'cogs' in s;
  const actions = [h('button', { class: 'btn', onclick: () => window.print() }, icon('print'), 'Print')];
  if (s.status === 'final' && can('returns.create')) actions.push(h('button', { class: 'btn', onclick: () => returnModal(s) }, 'Record return'));
  if (s.status === 'final' && can('payments.record') && s.customer_id && due > 0.004) actions.push(h('button', { class: 'btn', onclick: () => receiveModal(s.customer_id, s.customer_name, due, s.id) }, 'Receive payment'));
  if (s.status === 'final' && can('transactions.void')) actions.push(h('button', { class: 'btn danger', onclick: () => confirmVoid('sales', s.id, `sale ${s.invoice_no}`, state.rerender) }, 'Void'));
  if (can('sales.create')) actions.push(linkBtn('#/sales/new', 'New sale', 'primary', 'plus'));

  root.append(pageHead(`Invoice ${s.invoice_no}`, h('span', null, fmt.channel(s.channel), ' ', fmt.status(s.status), ' ', fmt.date(s.sale_date)), actions));
  if (s.status === 'void') root.append(h('div', { class: 'notice bad', style: { marginBottom: '14px' } }, `Voided on ${fmt.datetime(s.voided_at)}: ${s.void_reason}`));

  root.append(h('div', { class: 'grid-2' },
    card('Details', dl([
      ['Shop', s.shop_name], ['Date', fmt.date(s.sale_date)], ['Channel', fmt.channel(s.channel)],
      ['Customer', s.customer_id ? h('a', { href: `#/customers/${s.customer_id}` }, s.customer_name) : (s.customer_name || 'Walk-in')],
      s.customer_phone ? ['Phone', s.customer_phone] : null,
      ['Payment', `${s.payment_method || '—'}`], ['Staff', s.staff_name || '—'],
      ['Entered by', `${s.created_by_name || '—'} · ${fmt.datetime(s.created_at)}`],
      s.notes ? ['Notes', s.notes] : null,
    ])),
    card('Amounts', h('div', { class: 'totals', style: { maxWidth: 'none' } },
      h('span', null, 'Gross sales (excl. GST)'), h('span', { class: 'num' }, fmt.inr(s.gross_amount)),
      h('span', null, 'Discounts'), h('span', { class: 'num' }, `− ${fmt.inr(s.discount_amount)}`),
      h('span', null, 'Net sales'), h('span', { class: 'num' }, fmt.inr(s.net_amount)),
      h('span', null, s.tax_inclusive ? 'GST (included in prices)' : 'GST'), h('span', { class: 'num' }, fmt.inr(s.tax_amount)),
      h('span', { class: 'grand' }, 'Invoice total'), h('span', { class: 'grand num' }, fmt.inr(s.total_amount)),
      h('span', null, 'Received'), h('span', { class: 'num' }, fmt.inr(s.payments.filter((p) => p.status === 'final').reduce((a, p) => a + p.amount, 0))),
      h('span', null, 'Balance due'), h('span', { class: `num ${due > 0.004 ? 'neg' : ''}` }, fmt.inr(Math.max(0, due))),
      showCost ? [h('span', { class: 'muted' }, 'Cost of goods sold'), h('span', { class: 'num muted' }, fmt.inr(s.cogs)),
        h('span', { class: 'muted' }, 'Gross profit on invoice'), h('span', { class: 'num muted' }, fmt.inr(s.gross_profit))] : null))));

  root.append(h('div', { style: { height: '16px' } }), card('Items', table([
    { label: 'Product', render: (r) => h('div', { style: { minWidth: '170px' } }, r.label, h('div', { class: 'muted small' }, `${r.sku} · ${r.category}`)) },
    { label: 'Qty', num: true, render: (r) => `${fmt.num(r.qty)} ${r.unit}` },
    { label: 'Price', num: true, render: (r) => fmt.inr(r.unit_price) },
    { label: 'Discount', num: true, render: (r) => r.discount ? fmt.inr(r.discount) : '—' },
    { label: 'GST', num: true, render: (r) => `${fmt.num(r.tax_rate)}% · ${fmt.inr(r.tax_amount)}` },
    { label: 'Line total', num: true, render: (r) => fmt.inr(r.line_total) },
    showCost ? { label: 'COGS', num: true, render: (r) => fmt.inr(r.cogs) } : null,
    showCost ? { label: 'Profit', num: true, render: (r) => fmt.inr(r.gross_profit) } : null,
    { label: 'Returned', num: true, render: (r) => r.returned_qty ? fmt.num(r.returned_qty) : '—' },
  ].filter(Boolean), s.items)));

  if (s.payments.length) {
    root.append(h('div', { style: { height: '16px' } }), card('Payments received', table([
      { label: 'Date', render: (r) => fmt.date(r.payment_date) }, { label: 'Method', key: 'method' },
      { label: 'Note', render: (r) => r.notes || r.reference }, { label: 'Amount', num: true, render: (r) => fmt.inr(r.amount) },
      { label: '', render: (r) => r.status === 'void' ? fmt.status('void') : (!r.with_document && can('transactions.void') ? h('button', { class: 'btn small danger', onclick: () => confirmVoid('customer_payments', r.id, 'receipt', state.rerender) }, 'Void') : '') , cls: 'keep' },
    ], s.payments)));
  }
  if (s.returns.length) {
    root.append(h('div', { style: { height: '16px' } }), card('Returns', table([
      { label: 'Date', render: (r) => fmt.date(r.return_date) },
      { label: 'Units', num: true, render: (r) => fmt.num(r.items.reduce((a, i) => a + i.qty, 0)) },
      { label: 'Restocked', render: (r) => r.items.every((i) => i.restock) ? 'Yes' : (r.items.some((i) => i.restock) ? 'Partly' : 'No — damaged') },
      { label: 'Refund', render: (r) => ({ cash: 'Cash', bank: 'Bank / UPI', credit: 'Credit to account' })[r.refund_mode] },
      { label: 'Amount', num: true, render: (r) => fmt.inr(r.total_refund) },
      { label: 'Notes', key: 'notes' },
      { label: '', cls: 'keep', render: (r) => r.status === 'void' ? fmt.status('void') : (can('transactions.void') ? h('button', { class: 'btn small danger', onclick: () => confirmVoid('sale_returns', r.id, 'return', state.rerender) }, 'Void') : '') },
    ], s.returns)));
  }
  return root;
}

function returnModal(s) {
  const rows = s.items.map((it, i) => {
    const left = round2(it.qty - it.returned_qty);
    const qty = numInput(`items.${i}.qty`, { max: String(left), placeholder: '0', disabled: left <= 0 });
    const restock = h('input', { type: 'checkbox', checked: true });
    return { it, qty, restock, left };
  });
  const date = dateInput('return_date');
  const mode = select('refund_mode', [{ value: 'cash', label: 'Refund in cash' }, { value: 'bank', label: 'Refund by UPI / bank' }]
    .concat(s.customer_id ? [{ value: 'credit', label: 'Credit to customer account' }] : []), s.customer_id && s.amount_received < s.total_amount ? 'credit' : 'cash');
  const notes = input('notes', { placeholder: 'Reason for return' });
  const body = h('div', { class: 'stack' },
    h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, h('th', null, 'Item'), h('th', { class: 'num' }, 'Sold'), h('th', { class: 'num' }, 'Return qty'), h('th', null, 'Back to stock?'))),
      h('tbody', null, rows.map((r) => h('tr', null, h('td', null, r.it.label), h('td', { class: 'num' }, `${fmt.num(r.it.qty)}${r.it.returned_qty ? ` (${fmt.num(r.it.returned_qty)} returned)` : ''}`),
        h('td', { style: { width: '110px' } }, r.qty), h('td', null, h('label', { class: 'check' }, r.restock, 'Resaleable'))))))),
    h('p', { class: 'hint' }, 'Untick “Resaleable” for damaged goods: they will not go back into stock and their cost is shown as a write-off.'),
    h('div', { class: 'form-grid' }, field('Return date', date), field('Refund', mode), field('Notes', notes, { class: 'span-2' })));
  modal({ title: `Return on ${s.invoice_no}`, body, wide: true, actions: [
    (m) => h('button', { class: 'btn', onclick: m.close }, 'Cancel'),
    (m) => h('button', { class: 'btn primary', onclick: async (e) => busy(e.target, async () => {
      try {
        await api.post(`/api/sales/${s.id}/returns`, {
          return_date: date.value, refund_mode: mode.value, notes: notes.value,
          items: rows.map((r) => ({ sale_item_id: r.it.id, qty: r.qty.value || 0, restock: r.restock.checked })),
        });
        m.close(); toast('Return recorded'); state.rerender();
      } catch (ex) { showError(body, ex); }
    }) }, 'Save return'),
  ] });
}

export function receiveModal(customerId, name, due, saleId) {
  const amount = numInput('amount', { value: due ? due.toFixed(2) : '' });
  const date = dateInput('payment_date');
  const method = methodSelect('method');
  const refEl = input('reference', { placeholder: 'UPI ref / cheque no.' });
  const body = h('div', { class: 'form-grid' }, field('Amount', amount, { required: true }), field('Date', date), field('Method', method), field('Reference', refEl));
  modal({ title: `Receive payment — ${name}`, body, actions: [
    (m) => h('button', { class: 'btn', onclick: m.close }, 'Cancel'),
    (m) => h('button', { class: 'btn primary', onclick: async (e) => busy(e.target, async () => {
      try {
        await api.post('/api/customer-payments', { customer_id: customerId, sale_id: saleId || null, amount: amount.value, payment_date: date.value, method: method.value, reference: refEl.value, client_ref: clientRef() });
        m.close(); toast('Payment recorded'); state.rerender();
      } catch (ex) { showError(body, ex); }
    }) }, 'Save payment'),
  ] });
}

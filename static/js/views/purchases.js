import {
  h, api, state, fmt, can, pageHead, linkBtn, card, table, hashQuery, setHashQuery, field, input, numInput, dateInput,
  methodSelect, combobox, variantSource, showError, clearErrors, toast, modal, confirmVoid, busy, clientRef, round2, dl, icon,
} from '../core.js';
import { filterBar } from './dashboard.js';
import { productModal } from './products.js';

export async function purchaseList() {
  const f = hashQuery();
  const rows = await api.get('/api/purchases', f);
  const final = rows.filter((r) => r.status === 'final');
  const root = h('div');
  root.append(pageHead('Purchases', 'Every batch received from suppliers', [
    can('payments.record') ? h('button', { class: 'btn', onclick: () => supplierPaymentModal() }, 'Pay supplier') : null,
    can('purchases.create') ? linkBtn('#/purchases/new', 'New purchase', 'primary', 'plus') : null].filter(Boolean)));
  root.append(filterBar(f, (nf) => { setHashQuery(nf); state.rerender(); }, { channel: false, supplier: can('purchases.view') }));
  root.append(card(null, table([
    { label: 'Date', render: (r) => fmt.date(r.purchase_date), cls: 'nowrap' },
    { label: 'Supplier', render: (r) => r.supplier_name },
    { label: 'Invoice / Ref', render: (r) => h('span', null, r.invoice_no, ' ', fmt.status(r.status)), cls: 'keep' },
    { label: 'Lines', num: true, key: 'lines' },
    { label: 'Units', num: true, render: (r) => fmt.num(r.units) },
    { label: 'Total cost', num: true, render: (r) => fmt.inr(r.total_cost) },
    { label: 'Paid with bill', num: true, render: (r) => fmt.inr(r.amount_paid) },
    { label: 'Notes', render: (r) => r.notes },
  ], rows, {
    onRow: (r) => { location.hash = `#/purchases/${r.id}`; },
    empty: 'No purchases match these filters.',
    emptyAction: can('purchases.create') ? h('div', null, linkBtn('#/purchases/new', 'Record a purchase', 'primary')) : null,
  })));
  if (final.length) {
    root.append(h('div', { class: 'muted small', style: { marginTop: '10px' } },
      `${final.length} bill(s) · Units ${fmt.num(final.reduce((a, r) => a + r.units, 0))} · Total ${fmt.inr(final.reduce((a, r) => a + r.total_cost, 0))}`));
  }
  return root;
}

export function supplierCombo(onPick, opts = {}) {
  return combobox({
    name: opts.name || 'supplier_id', placeholder: 'Search supplier name, ID or phone',
    label: opts.label,
    source: async (q) => (await api.get('/api/suppliers', { q })).filter((x) => x.active).map((x) => ({
      value: x.id, label: x.name, data: x, sub: [x.code, x.outstanding > 0 ? `owe ${fmt.inr0(x.outstanding)}` : ''].filter(Boolean).join(' · '),
    })),
    onPick,
    action: can('suppliers.manage') ? { label: 'Add new supplier', run: (text, pick) => supplierModal({ name: text }, (s) => pick({ value: s.id, label: s.name, data: s })) } : null,
  });
}

export function supplierModal(initial, onSaved) {
  const v = initial || {};
  const name = input('name', { value: v.name || '' });
  const phone = input('phone', { value: v.phone || '', inputmode: 'tel' });
  const address = h('textarea', { name: 'address', 'data-field': 'address' }, v.address || '');
  const gstin = input('gstin', { value: v.gstin || '' });
  const cats = input('categories', { value: v.categories || '', placeholder: 'e.g. Sarees, Kurtis' });
  const notes = input('notes', { value: v.notes || '' });
  const opening = numInput('opening_balance', { value: v.opening_balance || '' });
  const body = h('div', { class: 'form-grid' },
    field('Supplier name', name, { required: true }), field('Contact number', phone), field('GSTIN', gstin),
    field('Categories supplied', cats, { hint: 'Comma separated' }),
    field('Address', address, { class: 'span-all' }), field('Notes', notes, { class: 'span-2' }),
    can('owner') ? field('Opening balance payable (₹)', opening, { hint: 'Amount you already owed before using this app' }) : null);
  modal({ title: v.id ? 'Edit supplier' : 'New supplier', body, wide: true, actions: [
    (m) => h('button', { class: 'btn', onclick: m.close }, 'Cancel'),
    (m) => h('button', { class: 'btn primary', onclick: async (e) => busy(e.target, async () => {
      const data = { name: name.value, phone: phone.value, address: address.value, gstin: gstin.value, categories: cats.value, notes: notes.value };
      if (can('owner')) data.opening_balance = opening.value || 0;
      try {
        const r = v.id ? await api.put(`/api/suppliers/${v.id}`, data) : await api.post('/api/suppliers', data);
        m.close();
        toast('Supplier saved');
        onSaved && onSaved(Object.assign({ id: r.id, outstanding: 0 }, data));
      } catch (ex) { showError(body, ex); }
    }) }, 'Save supplier'),
  ] });
}

export async function purchaseForm() {
  const ref = clientRef();
  let supplier = null;
  const lines = [];
  const form = h('div', { class: 'stack' });
  const dateEl = dateInput('purchase_date');
  const invEl = input('invoice_no', { placeholder: 'Supplier bill / challan no.' });
  const supInfo = h('div', { class: 'hint' });
  const supBox = supplierCombo((it) => {
    supplier = it.data;
    supInfo.textContent = `${it.data.code || ''}${it.data.outstanding !== undefined ? ` · currently owed ${fmt.inr(it.data.outstanding)}` : ''}`;
    update();
  });
  const tbody = h('tbody');
  const linesTable = h('table', { class: 'lines' }, h('thead', null, h('tr', null,
    h('th', null, 'Product / design'), h('th', null, 'Category · unit'), h('th', { class: 'num' }, 'Qty received'),
    h('th', { class: 'num' }, 'Purchase price / unit'), h('th', { class: 'num' }, 'Amount'), h('th', null, ''))), tbody);
  const addCost = numInput('additional_cost', { placeholder: '0' });
  const addNote = input('additional_note', { placeholder: 'e.g. transport, loading' });
  const discount = numInput('discount', { placeholder: '0' });
  const paid = numInput('amount_paid', { placeholder: '0' });
  const method = methodSelect('payment_method');
  const notes = h('textarea', { name: 'notes', 'data-field': 'notes', placeholder: 'Optional notes' });
  const t = { sub: h('span'), add: h('span'), disc: h('span'), total: h('span'), out: h('span'), after: h('span') };
  const saveBtn = h('button', { class: 'btn primary', type: 'button', onclick: () => save() }, 'Save purchase');

  function addLine(variant) {
    const l = { variant: null };
    const i = lines.length;
    l.info = h('span', { class: 'muted small' });
    l.combo = combobox({
      name: `items.${i}.variant_id`, placeholder: 'Search product, SKU, size, colour…', source: variantSource(),
      onPick: (it) => setVariant(l, it.data),
      action: can('products.manage') ? { label: 'Create new product', run: (text) => productModal({ name: text }, async (pid) => {
        const mine = await api.get('/api/variants', { product_id: pid, limit: 200 });
        mine.forEach((v, k) => { if (k === 0) { l.combo.pick({ value: v.id, label: v.label, data: v }); } else addLine(v); });
      }) } : null,
    });
    l.qty = numInput(`items.${i}.qty`, { placeholder: '0' });
    l.price = numInput(`items.${i}.unit_price`, { placeholder: '0.00' });
    l.amount = h('strong', { class: 'num' }, '—');
    [l.qty, l.price].forEach((el) => el.addEventListener('input', update));
    l.row = h('tr', null,
      h('td', { class: 'col-product', 'data-label': 'Product' }, l.combo),
      h('td', { 'data-label': 'Category · unit' }, l.info),
      h('td', { class: 'col-num', 'data-label': 'Qty' }, l.qty),
      h('td', { class: 'col-num', 'data-label': 'Price / unit' }, l.price),
      h('td', { class: 'num', 'data-label': 'Amount' }, l.amount),
      h('td', null, h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Remove line', onclick: () => removeLine(l) }, icon('trash'))));
    lines.push(l);
    tbody.append(l.row);
    if (variant) l.combo.pick({ value: variant.id, label: variant.label, data: variant });
    return l;
  }
  function setVariant(l, v) {
    l.variant = v;
    l.info.textContent = `${v.category} · ${v.unit}${v.avg_cost ? ` · avg cost ${fmt.inr(v.avg_cost)}` : ''}`;
    update();
    if (lines[lines.length - 1] === l) addLine();
    l.qty.focus();
  }
  function removeLine(l) {
    if (lines.length === 1) { l.combo.clear(); l.variant = null; l.qty.value = ''; l.price.value = ''; l.info.textContent = ''; update(); return; }
    lines.splice(lines.indexOf(l), 1);
    l.row.remove();
    lines.forEach((x, i) => {
      x.combo.querySelector('input').dataset.field = `items.${i}.variant_id`;
      x.qty.dataset.field = `items.${i}.qty`; x.price.dataset.field = `items.${i}.unit_price`;
    });
    update();
  }
  function update() {
    let sub = 0;
    for (const l of lines) {
      if (!l.variant) { l.amount.textContent = '—'; continue; }
      const a = round2((+l.qty.value || 0) * (+l.price.value || 0));
      l.amount.textContent = fmt.inr(a);
      sub += a;
    }
    sub = round2(sub);
    const total = round2(sub + (+addCost.value || 0) - (+discount.value || 0));
    const out = round2(total - (+paid.value || 0));
    t.sub.textContent = fmt.inr(sub); t.add.textContent = `+ ${fmt.inr(+addCost.value || 0)}`;
    t.disc.textContent = `− ${fmt.inr(+discount.value || 0)}`; t.total.textContent = fmt.inr(total);
    t.out.textContent = fmt.inr(out);
    t.after.textContent = supplier && supplier.outstanding !== undefined ? fmt.inr(round2(supplier.outstanding + out)) : '—';
  }
  [addCost, discount, paid].forEach((el) => el.addEventListener('input', update));

  async function save() {
    clearErrors(form);
    const filled = lines.filter((l) => l.variant);
    const body = {
      client_ref: ref, purchase_date: dateEl.value, supplier_id: supBox.value, invoice_no: invEl.value,
      additional_cost: addCost.value || 0, additional_note: addNote.value, discount: discount.value || 0,
      amount_paid: paid.value || 0, payment_method: method.value, notes: notes.value,
      items: filled.map((l) => ({ variant_id: l.variant.id, qty: l.qty.value, unit_price: l.price.value })),
    };
    await busy(saveBtn, async () => {
      try {
        const r = await api.post('/api/purchases', body);
        toast('Purchase saved — stock updated');
        location.hash = `#/purchases/${r.id}`;
      } catch (ex) {
        if (ex.field && ex.field.startsWith('duplicate:')) { location.hash = `#/purchases/${ex.field.split(':')[1]}`; return; }
        if (ex.field && /^items\.\d+/.test(ex.field)) {
          const idx = +ex.field.split('.')[1];
          ex.field = ex.field.replace(/^items\.\d+/, `items.${lines.indexOf(filled[idx])}`);
        }
        showError(form, ex);
      }
    });
  }

  addLine();
  form.append(
    card('Bill details', h('div', { class: 'form-grid' },
      field('Purchase date', dateEl, { required: true }),
      h('div', { class: 'span-2' }, field('Supplier', supBox, { required: true }), supInfo),
      field('Invoice / reference no.', invEl, { required: true, hint: 'Duplicate bills from the same supplier are blocked' }))),
    card('Garments received', h('div', null, h('div', { class: 'table-wrap' }, linesTable),
      h('div', { class: 'row', style: { marginTop: '10px' } }, h('button', { class: 'btn small', type: 'button', onclick: () => addLine() }, icon('plus'), 'Add line'))),
    { sub: 'Pick a design or a size/colour variant. Each line adds to stock.' }),
    card('Costs and payment', h('div', { class: 'grid-2' },
      h('div', { class: 'form-grid' },
        field('Additional costs (₹)', addCost, { hint: 'Transport, packing, loading…' }), field('What for', addNote),
        field('Purchase discount (₹)', discount),
        field('Amount paid now (₹)', paid), field('Payment method', method),
        field('Notes', notes, { class: 'span-all' })),
      h('div', { class: 'totals' },
        h('span', null, 'Qty × price'), h('span', { class: 'num' }, t.sub),
        h('span', null, 'Additional costs'), h('span', { class: 'num' }, t.add),
        h('span', null, 'Discount'), h('span', { class: 'num' }, t.disc),
        h('span', { class: 'grand' }, 'Total purchase cost'), h('span', { class: 'grand num' }, t.total),
        h('span', null, 'Outstanding on this bill'), h('span', { class: 'num' }, t.out),
        h('span', { class: 'muted' }, 'Supplier balance after'), h('span', { class: 'num muted' }, t.after),
        h('span', { class: 'hint', style: { gridColumn: '1 / -1' } }, 'Additional costs and discount are spread over the lines by value, so each unit’s landed cost is used for stock value and profit.')))),
    h('div', { class: 'form-actions' }, h('a', { class: 'btn', href: '#/purchases' }, 'Cancel'), saveBtn));
  update();
  if (window.innerWidth > 860) setTimeout(() => supBox.focus(), 50);
  return h('div', null, pageHead('New purchase', 'Total = Qty × price + additional costs − discount'), form);
}

export async function purchaseDetail(id) {
  const p = await api.get(`/api/purchases/${id}`);
  const paid = p.payments.filter((x) => x.status === 'final').reduce((a, x) => a + x.amount, 0);
  const actions = [];
  if (p.status === 'final' && can('payments.record')) actions.push(h('button', { class: 'btn', onclick: () => supplierPaymentModal({ id: p.supplier_id, name: p.supplier_name }, p.id, round2(p.total_cost - paid)) }, 'Record payment'));
  if (p.status === 'final' && can('transactions.void')) actions.push(h('button', { class: 'btn danger', onclick: () => confirmVoid('purchases', p.id, `purchase ${p.invoice_no}`, state.rerender) }, 'Void'));
  if (can('purchases.create')) actions.push(linkBtn('#/purchases/new', 'New purchase', 'primary', 'plus'));
  const root = h('div', null, pageHead(`Purchase ${p.invoice_no}`, h('span', null, p.supplier_name, ' · ', fmt.date(p.purchase_date), ' ', fmt.status(p.status)), actions));
  if (p.status === 'void') root.append(h('div', { class: 'notice bad', style: { marginBottom: '14px' } }, `Voided on ${fmt.datetime(p.voided_at)}: ${p.void_reason}`));
  root.append(h('div', { class: 'grid-2' },
    card('Details', dl([
      ['Supplier', h('a', { href: `#/suppliers/${p.supplier_id}` }, `${p.supplier_name} (${p.supplier_code})`)],
      ['Invoice / ref', p.invoice_no], ['Date', fmt.date(p.purchase_date)],
      ['Entered by', `${p.created_by_name || '—'} · ${fmt.datetime(p.created_at)}`],
      p.additional_note ? ['Additional cost for', p.additional_note] : null, p.notes ? ['Notes', p.notes] : null])),
    card('Amounts', h('div', { class: 'totals', style: { maxWidth: 'none' } },
      h('span', null, 'Qty × price'), h('span', { class: 'num' }, fmt.inr(p.subtotal)),
      h('span', null, 'Additional costs'), h('span', { class: 'num' }, `+ ${fmt.inr(p.additional_cost)}`),
      h('span', null, 'Discount'), h('span', { class: 'num' }, `− ${fmt.inr(p.discount)}`),
      h('span', { class: 'grand' }, 'Total purchase cost'), h('span', { class: 'grand num' }, fmt.inr(p.total_cost)),
      h('span', null, 'Paid against this bill'), h('span', { class: 'num' }, fmt.inr(paid)),
      h('span', null, 'Outstanding on this bill'), h('span', { class: 'num' }, fmt.inr(round2(p.total_cost - paid)))))));
  root.append(h('div', { style: { height: '16px' } }), card('Items received', table([
    { label: 'Product', render: (r) => h('a', { href: `#/inventory/ledger/${r.variant_id}` }, r.label) },
    { label: 'SKU', key: 'sku' }, { label: 'Category', key: 'category' },
    { label: 'Qty', num: true, render: (r) => `${fmt.num(r.qty)} ${r.unit}` },
    { label: 'Price / unit', num: true, render: (r) => fmt.inr(r.unit_price) },
    { label: 'Amount', num: true, render: (r) => fmt.inr(r.line_amount) },
    { label: 'Addl − disc', num: true, render: (r) => fmt.inr(r.allocated_cost) },
    { label: 'Landed cost', num: true, render: (r) => fmt.inr(r.landed_value) },
    { label: 'Landed / unit', num: true, render: (r) => fmt.inr(r.landed_unit_cost) },
  ], p.items)));
  if (p.payments.length) {
    root.append(h('div', { style: { height: '16px' } }), card('Payments against this bill', table([
      { label: 'Date', render: (r) => fmt.date(r.payment_date) }, { label: 'Method', key: 'method' },
      { label: 'Reference', render: (r) => r.reference || r.notes }, { label: 'Amount', num: true, render: (r) => fmt.inr(r.amount) },
      { label: '', cls: 'keep', render: (r) => r.status === 'void' ? fmt.status('void') : (!r.with_document && can('transactions.void') ? h('button', { class: 'btn small danger', onclick: () => confirmVoid('supplier_payments', r.id, 'payment', state.rerender) }, 'Void') : '') },
    ], p.payments)));
  }
  return root;
}

export function supplierPaymentModal(supplier, purchaseId, amountDue) {
  let sup = supplier || null;
  const supBox = supplier ? h('input', { value: supplier.name, disabled: true }) : supplierCombo((it) => { sup = it.data; if (!amount.value && it.data.outstanding > 0) amount.value = it.data.outstanding.toFixed(2); });
  const amount = numInput('amount', { value: amountDue > 0 ? amountDue.toFixed(2) : '' });
  const date = dateInput('payment_date');
  const method = methodSelect('method', 'Bank Transfer');
  const refEl = input('reference', { placeholder: 'UTR / cheque no.' });
  const notes = input('notes');
  const body = h('div', { class: 'form-grid' }, field('Supplier', supBox, { required: true, class: 'span-2' }), field('Amount', amount, { required: true }),
    field('Date', date), field('Method', method), field('Reference', refEl), field('Notes', notes, { class: 'span-2' }));
  const ref = clientRef();
  modal({ title: 'Pay supplier', body, wide: true, actions: [
    (m) => h('button', { class: 'btn', onclick: m.close }, 'Cancel'),
    (m) => h('button', { class: 'btn primary', onclick: async (e) => busy(e.target, async () => {
      try {
        await api.post('/api/supplier-payments', { client_ref: ref, supplier_id: sup && sup.id, purchase_id: purchaseId || null, amount: amount.value, payment_date: date.value, method: method.value, reference: refEl.value, notes: notes.value });
        m.close(); toast('Payment recorded'); state.rerender();
      } catch (ex) { showError(body, ex); }
    }) }, 'Save payment'),
  ] });
}

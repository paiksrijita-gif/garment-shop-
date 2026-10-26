import {
  h, api, state, fmt, pageHead, card, table, hashQuery, setHashQuery, field, input, numInput, dateInput, select,
  combobox, variantSource, showError, clearErrors, toast, modal, busy, clientRef, confirmVoid, icon,
} from '../core.js';
import { loadRefs } from '../app.js';
import { supplierModal, supplierCombo } from './purchases.js';
import { productModal } from './products.js';

// ---------------------------------------------------------------- settings
export async function settingsView() {
  const f = hashQuery();
  const tab = f.tab || 'general';
  const go = (t) => { setHashQuery({ tab: t }); state.rerender(); };
  const root = h('div', null, pageHead('Settings', 'Owner only', [h('a', { class: 'btn', href: '#/setup' }, 'Opening balances & setup')]),
    h('div', { class: 'tabs' }, [['general', 'Shop & accounting'], ['users', 'Staff & permissions'], ['audit', 'Audit log']].map(([k, l]) =>
      h('button', { class: tab === k ? 'on' : '', onclick: () => go(k) }, l))));
  if (tab === 'general') root.append(await generalTab());
  if (tab === 'users') root.append(await usersTab());
  if (tab === 'audit') root.append(await auditTab());
  return root;
}

function settingsForm(st) {
  const shop = input('shop_name', { value: st.shop_name });
  const method = select('costing_method', [{ value: 'WAC', label: 'Weighted average cost (recommended)' }, { value: 'FIFO', label: 'FIFO — first in, first out' }], st.costing_method);
  const tax = numInput('default_tax_rate', { value: st.default_tax_rate, max: '28' });
  const incl = h('input', { type: 'checkbox', checked: st.prices_include_tax === '1' });
  const low = numInput('low_stock_default', { value: st.low_stock_default });
  const prefix = input('invoice_prefix', { value: st.invoice_prefix });
  const el = h('div', { class: 'form-grid' },
    field('Shop name', shop, { required: true }),
    field('Inventory costing method', method, { hint: 'Changing this recalculates the cost of every past sale' }),
    field('Default GST rate on sales (%)', tax, { hint: 'Garments: 5% up to ₹1,000 per piece; 12% above (check current rates)' }),
    field('Invoice prefix', prefix),
    field('Default low-stock alert level', low),
    h('label', { class: 'check' }, incl, 'Selling prices include GST (MRP style)'));
  return { el, data: () => ({ shop_name: shop.value, costing_method: method.value, default_tax_rate: tax.value, prices_include_tax: incl.checked, low_stock_default: low.value, invoice_prefix: prefix.value }) };
}

async function generalTab() {
  const st = await api.get('/api/settings');
  const sf = settingsForm(st);
  const save = h('button', { class: 'btn primary', onclick: (e) => busy(e.target, async () => {
    const d = sf.data();
    if (d.costing_method !== st.costing_method && !confirm(`Switch to ${d.costing_method}? Cost of goods sold and stock value for all past sales will be recalculated.`)) return;
    try { await api.put('/api/settings', d); await loadRefs(); toast('Settings saved'); state.rerender(); }
    catch (ex) { showError(sf.el, ex); }
  }) }, 'Save settings');
  return h('div', { class: 'stack' }, card(null, h('div', null, sf.el, h('div', { class: 'form-actions' }, save))),
    card('Backup', h('div', { class: 'row' },
      h('span', { class: 'muted small', style: { flex: '1 1 300px' } }, 'Download a complete copy of all shop data. Keep it on a pen drive or cloud storage. To restore, stop the app and replace data/shop.db with the backup file.'),
      h('button', { class: 'btn', onclick: () => api.download('/api/backup') }, icon('download'), 'Download backup'))));
}

async function usersTab() {
  const d = await api.get('/api/users');
  const wrap = h('div', { class: 'stack' });
  wrap.append(h('div', { class: 'row' }, h('span', { class: 'muted small' }, 'Staff can only do what you allow. Without "View cost prices" they never see purchase cost or profit.'),
    h('span', { class: 'spacer' }), h('button', { class: 'btn primary', onclick: () => userModal(d) }, icon('plus'), 'Add staff')));
  wrap.append(card(null, table([
    { label: 'Name', key: 'full_name' }, { label: 'Username', render: (u) => '@' + u.username },
    { label: 'Role', render: (u) => u.role === 'owner' ? h('span', { class: 'badge good' }, 'Owner') : h('span', { class: 'badge plain' }, 'Staff') },
    { label: 'Permissions', render: (u) => u.role === 'owner' ? 'Everything' : (u.permissions.map((p) => d.permissions[p]).join(', ') || 'None') },
    { label: 'Status', render: (u) => u.active ? 'Active' : h('span', { class: 'badge bad' }, 'Disabled') },
  ], d.users, { onRow: (u) => userModal(d, u) })));
  return wrap;
}

function userModal(d, u) {
  const isNew = !u;
  const name = input('full_name', { value: u ? u.full_name : '' });
  const username = input('username', { value: u ? u.username : '', disabled: !isNew, autocapitalize: 'none' });
  const pw = input('password', { type: 'password', autocomplete: 'new-password', placeholder: isNew ? 'At least 8 characters' : 'Leave blank to keep' });
  const active = h('input', { type: 'checkbox', checked: u ? u.active : true });
  const perms = u ? u.permissions : d.default_staff_permissions;
  const boxes = Object.entries(d.permissions).map(([k, label]) => ({ k, el: h('input', { type: 'checkbox', checked: perms.includes(k), disabled: u && u.role === 'owner' }), label }));
  const body = h('div', { class: 'stack' },
    h('div', { class: 'form-grid' }, field('Full name', name, { required: true }), field('Username', username, { required: true }), field(isNew ? 'Password' : 'Reset password', pw, { required: isNew })),
    u && u.role === 'owner' ? h('div', { class: 'notice' }, 'The owner always has full access.') : h('div', null,
      h('div', { class: 'small', style: { fontWeight: 600, marginBottom: '6px' } }, 'Permissions'),
      h('div', { class: 'grid-2', style: { gap: '6px' } }, boxes.map((b) => h('label', { class: 'check' }, b.el, b.label))),
      h('label', { class: 'check', style: { marginTop: '10px' } }, active, 'Account active')));
  modal({ title: isNew ? 'Add staff member' : `Edit ${u.full_name}`, body, wide: true, actions: [
    (m) => h('button', { class: 'btn', onclick: m.close }, 'Cancel'),
    (m) => h('button', { class: 'btn primary', onclick: async (e) => busy(e.target, async () => {
      const data = { full_name: name.value, permissions: boxes.filter((b) => b.el.checked).map((b) => b.k), active: active.checked };
      if (pw.value) data.password = pw.value;
      try {
        if (isNew) await api.post('/api/users', Object.assign({ username: username.value, role: 'staff' }, data));
        else await api.put(`/api/users/${u.id}`, data);
        m.close(); toast('Saved'); state.rerender();
      } catch (ex) { showError(body, ex); }
    }) }, 'Save'),
  ] });
}

async function auditTab() {
  const rows = await api.get('/api/audit');
  const link = (r) => ({ sales: `#/sales/${r.entity_id}`, purchases: `#/purchases/${r.entity_id}`, suppliers: `#/suppliers/${r.entity_id}`, customers: `#/customers/${r.entity_id}`, products: `#/products/${r.entity_id}` })[r.entity];
  return card('Latest 500 actions', table([
    { label: 'When (UTC)', render: (r) => fmt.datetime(r.ts) }, { label: 'User', key: 'user_name' }, { label: 'Action', key: 'action' },
    { label: 'Record', render: (r) => r.entity ? (link(r) ? h('a', { href: link(r) }, `${r.entity} #${r.entity_id}`) : `${r.entity}${r.entity_id ? ' #' + r.entity_id : ''}`) : '' },
    { label: 'Details', render: (r) => h('code', { class: 'small', style: { wordBreak: 'break-all' } }, r.details || '') },
  ], rows));
}

// ---------------------------------------------------------------- setup wizard
const STEPS = [['shop', 'Shop'], ['money', 'Cash, bank & capital'], ['suppliers', 'Supplier balances'], ['stock', 'Opening stock'], ['customers', 'Customer balances'], ['done', 'Finish']];

export async function setupWizard() {
  const f = hashQuery();
  const step = STEPS.some(([k]) => k === f.step) ? f.step : 'shop';
  const idx = STEPS.findIndex(([k]) => k === step);
  const go = (k) => { setHashQuery({ step: k }); state.rerender(); };
  const next = () => go(STEPS[idx + 1][0]);
  const root = h('div', null, pageHead('Set up your shop', 'Enter what the business has today. Every figure here comes from you — nothing is pre-filled.'),
    h('div', { class: 'steps' }, STEPS.map(([k, l], i) => h('span', { class: i === idx ? 'on' : (i < idx ? 'done' : ''), style: { cursor: 'pointer' }, onclick: () => go(k) }, `${i + 1}. ${l}`))));
  const nav = (content, nextLabel = 'Next') => h('div', { class: 'stack' }, content, h('div', { class: 'form-actions' },
    idx > 0 ? h('button', { class: 'btn', onclick: () => go(STEPS[idx - 1][0]) }, 'Back') : null,
    idx < STEPS.length - 1 ? h('button', { class: 'btn primary', onclick: next }, nextLabel) : null));

  if (step === 'shop') {
    const st = await api.get('/api/settings');
    const sf = settingsForm(st);
    const od = dateInput('opening_date', st.opening_date || state.today);
    const btn = h('button', { class: 'btn primary', onclick: (e) => busy(e.target, async () => {
      try { await api.put('/api/settings', Object.assign(sf.data(), { opening_date: od.value })); await loadRefs(); next(); }
      catch (ex) { showError(sf.el, ex); }
    }) }, 'Save & continue');
    root.append(card('Shop & accounting', h('div', { class: 'stack' }, sf.el,
      h('div', { class: 'form-grid' }, field('Start date (opening balances are as of)', od, { hint: 'Usually today, or the first day of the month / financial year' })),
      h('div', { class: 'form-actions' }, btn))));
    return root;
  }

  if (step === 'money') {
    const d = await api.get('/api/cash');
    const openings = d.rows.filter((r) => r.kind === 'opening_balance' && r.status === 'final');
    const caps = d.rows.filter((r) => ['initial_investment', 'partner_contribution', 'additional_capital', 'loan_received'].includes(r.kind) && r.status === 'final');
    const od = state.settings.opening_date || state.today;
    const has = (acc) => openings.find((r) => r.account === acc);
    const cash = numInput('cash', { placeholder: '0.00', disabled: !!has('cash') });
    const bank = numInput('bank', { placeholder: '0.00', disabled: !!has('bank') });
    const histCap = numInput('opening_capital', { value: state.settings.opening_capital && state.settings.opening_capital !== '0' ? state.settings.opening_capital : '' });
    const form = h('div', { class: 'stack' });
    const saveBal = h('button', { class: 'btn primary', onclick: (e) => busy(e.target, async () => {
      clearErrors(form);
      try {
        if (cash.value && !has('cash')) await api.post('/api/cash', { kind: 'opening_balance', account: 'cash', amount: cash.value, txn_date: od, notes: 'Opening cash in hand', client_ref: clientRef() });
        if (bank.value && !has('bank')) await api.post('/api/cash', { kind: 'opening_balance', account: 'bank', amount: bank.value, txn_date: od, notes: 'Opening bank balance', client_ref: clientRef() });
        await api.put('/api/settings', { opening_capital: histCap.value || 0 });
        await loadRefs();
        toast('Saved'); state.rerender();
      } catch (ex) { showError(form, ex); }
    }) }, 'Save balances');
    form.append(
      h('div', { class: 'notice' }, 'Already running shop? Enter the cash and bank balance you have today, and the capital you invested so far (for reference only — it does not add cash). New shop? Leave these blank and record your initial investment below; it is added to cash or bank.'),
      h('div', { class: 'form-grid' },
        field(`Opening cash in hand (${fmt.date(od)})`, cash, { hint: has('cash') ? `Recorded: ${fmt.inr(has('cash').amount)}` : '' }),
        field(`Opening bank balance (${fmt.date(od)})`, bank, { hint: has('bank') ? `Recorded: ${fmt.inr(has('bank').amount)}` : '' }),
        field('Capital invested before this app (₹)', histCap, { hint: 'Shown in "Total capital invested"; no cash effect' })),
      h('div', { class: 'form-actions' }, saveBal));
    const kind = select('kind', [{ value: 'initial_investment', label: 'Initial investment by owner' }, { value: 'partner_contribution', label: 'Partner contribution' }, { value: 'additional_capital', label: 'Additional capital' }, { value: 'loan_received', label: 'Business loan received' }], 'initial_investment');
    const amt = numInput('amount'); const acc = select('account', [{ value: 'bank', label: 'Bank' }, { value: 'cash', label: 'Cash' }], 'bank');
    const party = input('party', { placeholder: 'Name' });
    const purpose = select('purpose', [{ value: 'general', label: 'General' }, { value: 'inventory', label: 'Inventory purchases' }, { value: 'expenses', label: 'Operating expenses' }]);
    const date = dateInput('txn_date', od);
    const capForm = h('div');
    const addCap = h('button', { class: 'btn', onclick: (e) => busy(e.target, async () => {
      clearErrors(capForm);
      try { await api.post('/api/cash', { kind: kind.value, amount: amt.value, account: acc.value, party: party.value, purpose: purpose.value, txn_date: date.value, client_ref: clientRef() }); toast('Recorded'); state.rerender(); }
      catch (ex) { showError(capForm, ex); }
    }) }, 'Add');
    capForm.append(h('div', { class: 'form-grid' }, field('Type', kind), field('Amount (₹)', amt), field('Into', acc), field('Name', party), field('Allocated to', purpose), field('Date', date)), h('div', { class: 'form-actions' }, addCap));
    root.append(nav(h('div', { class: 'stack' }, card('Opening cash & bank', form),
      card('Investment & loans', h('div', { class: 'stack' }, capForm, table([
        { label: 'Date', render: (r) => fmt.date(r.txn_date) }, { label: 'Type', key: 'kind_label' }, { label: 'Name', key: 'party' },
        { label: 'Account', key: 'account' }, { label: 'Amount', num: true, render: (r) => fmt.inr(r.amount) },
        { label: '', render: (r) => h('button', { class: 'btn small danger', onclick: () => confirmVoid('cash_transactions', r.id, 'entry', state.rerender) }, 'Void') },
      ], openings.concat(caps), { empty: 'Nothing recorded yet.' }))))));
    return root;
  }

  if (step === 'suppliers') {
    const sups = await api.get('/api/suppliers');
    root.append(nav(card('Suppliers and what you already owe them', h('div', { class: 'stack' },
      h('div', { class: 'row' }, h('span', { class: 'muted small' }, 'Add each supplier. "Opening balance" is the amount unpaid before you started using this app.'), h('span', { class: 'spacer' }),
        h('button', { class: 'btn primary', onclick: () => supplierModal({}, () => state.rerender()) }, icon('plus'), 'Add supplier')),
      table([{ label: 'ID', key: 'code' }, { label: 'Supplier', key: 'name' }, { label: 'Phone', key: 'phone' },
        { label: 'Opening balance', num: true, render: (r) => fmt.inr(r.opening_balance) }, { label: 'Outstanding now', num: true, render: (r) => fmt.inr(r.outstanding) }],
      sups, { onRow: (r) => supplierModal(r, () => state.rerender()), empty: 'No suppliers yet.' })))));
    return root;
  }

  if (step === 'stock') {
    const existing = await api.get('/api/opening-stock');
    const od = state.settings.opening_date || state.today;
    const lines = [];
    const tbody = h('tbody');
    const form = h('div', { class: 'stack' });
    const addLine = (variant) => {
      const l = { variant: null };
      const i = lines.length;
      l.combo = combobox({ name: `items.${i}.variant_id`, placeholder: 'Search product / SKU', source: variantSource(),
        onPick: (it) => { l.variant = it.data; if (lines[lines.length - 1] === l) addLine(); l.qty.focus(); },
        action: { label: 'Create new product', run: (text) => productModal({ name: text }, async (pid) => {
          const vs = await api.get('/api/variants', { product_id: pid, limit: 200 });
          vs.forEach((v, k) => { if (k === 0) l.combo.pick({ value: v.id, label: v.label, data: v }); else addLine(v); });
        }) } });
      l.qty = numInput(`items.${i}.qty`, { placeholder: '0' });
      l.cost = numInput(`items.${i}.unit_cost`, { placeholder: '0.00' });
      l.sup = supplierCombo((it) => { l.supplier = it.data; }, { name: `items.${i}.supplier_id` });
      tbody.append(h('tr', null, h('td', { class: 'col-product', 'data-label': 'Product' }, l.combo), h('td', { class: 'col-num', 'data-label': 'Qty' }, l.qty),
        h('td', { class: 'col-num', 'data-label': 'Cost / unit' }, l.cost), h('td', { class: 'full', 'data-label': 'Bought from (optional)' }, l.sup)));
      lines.push(l);
      if (variant) l.combo.pick({ value: variant.id, label: variant.label, data: variant });
    };
    addLine();
    const date = dateInput('entry_date', od);
    const save = h('button', { class: 'btn primary', onclick: (e) => busy(e.target, async () => {
      clearErrors(form);
      const filled = lines.filter((l) => l.variant);
      try {
        await api.post('/api/opening-stock', { entry_date: date.value, client_ref: clientRef(),
          items: filled.map((l) => ({ variant_id: l.variant.id, qty: l.qty.value, unit_cost: l.cost.value, supplier_id: l.supplier ? l.supplier.id : null })) });
        toast('Opening stock saved'); state.rerender();
      } catch (ex) {
        if (ex.field && /^items\.\d+/.test(ex.field)) ex.field = ex.field.replace(/^items\.\d+/, `items.${lines.indexOf(filled[+ex.field.split('.')[1]])}`);
        showError(form, ex);
      }
    }) }, 'Save opening stock');
    form.append(h('div', { class: 'notice' }, 'Enter the stock you have on the start date and what each unit actually cost you (historical cost). This becomes your opening inventory value. Opening stock is not a purchase and does not create a supplier balance.'),
      h('div', { class: 'form-grid' }, field('As of date', date)),
      h('div', { class: 'table-wrap' }, h('table', { class: 'lines' }, h('thead', null, h('tr', null, h('th', null, 'Product'), h('th', { class: 'num' }, 'Qty'), h('th', { class: 'num' }, 'Cost / unit (₹)'), h('th', null, 'Bought from (optional)'))), tbody)),
      h('div', { class: 'row' }, h('button', { class: 'btn small', onclick: () => addLine() }, icon('plus'), 'Add line'), h('span', { class: 'spacer' }), save));
    const total = existing.filter((r) => r.status === 'final').reduce((a, r) => a + r.value, 0);
    root.append(nav(h('div', { class: 'stack' }, card('Opening stock', form),
      card(`Recorded opening stock · ${fmt.inr(total)}`, table([
        { label: 'Date', render: (r) => fmt.date(r.entry_date) }, { label: 'Product', render: (r) => h('span', null, r.label, ' ', fmt.status(r.status)), cls: 'keep' }, { label: 'SKU', key: 'sku' },
        { label: 'Qty', num: true, render: (r) => fmt.num(r.qty) }, { label: 'Cost / unit', num: true, render: (r) => fmt.inr(r.unit_cost) },
        { label: 'Value', num: true, render: (r) => fmt.inr(r.value) }, { label: 'Supplier', key: 'supplier_name' },
        { label: '', cls: 'keep', render: (r) => r.status === 'void' ? '' : h('button', { class: 'btn small danger', onclick: () => confirmVoid('opening_stock', r.id, 'opening stock line', state.rerender) }, 'Void') },
      ], existing, { empty: 'No opening stock yet.' })))));
    return root;
  }

  if (step === 'customers') {
    const custs = await api.get('/api/customers');
    const name = input('name'); const phone = input('phone', { inputmode: 'tel' });
    const kind = select('kind', [{ value: 'wholesale', label: 'Wholesale' }, { value: 'retail', label: 'Retail' }]);
    const ob = numInput('opening_balance');
    const form = h('div');
    const add = h('button', { class: 'btn primary', onclick: (e) => busy(e.target, async () => {
      clearErrors(form);
      try { await api.post('/api/customers', { name: name.value, phone: phone.value, kind: kind.value, opening_balance: ob.value || 0 }); toast('Customer added'); state.rerender(); }
      catch (ex) { showError(form, ex); }
    }) }, 'Add customer');
    form.append(h('div', { class: 'form-grid' }, field('Customer name', name, { required: true }), field('Phone', phone), field('Type', kind), field('Amount they owe you (₹)', ob)), h('div', { class: 'form-actions' }, add));
    root.append(nav(h('div', { class: 'stack' }, card('Credit customers with an unpaid balance', h('div', { class: 'stack' },
      h('p', { class: 'muted small' }, 'Optional. Add customers who already owe you money (usually wholesale buyers on credit).'), form)),
    card('Customers', table([{ label: 'Name', key: 'name' }, { label: 'Phone', key: 'phone' }, { label: 'Opening balance', num: true, render: (r) => fmt.inr(r.opening_balance) },
      { label: 'Outstanding', num: true, render: (r) => fmt.inr(r.outstanding) }], custs, { empty: 'None yet.' })))));
    return root;
  }

  // done
  const cap = (await api.get('/api/cash')).summary;
  const finish = h('button', { class: 'btn primary', onclick: (e) => busy(e.target, async () => {
    await api.put('/api/settings', { setup_complete: true }); await loadRefs(); toast('Setup complete'); location.hash = '#/';
  }) }, 'Finish setup & open dashboard');
  root.append(card('Opening position', h('div', { class: 'stack' },
    h('table', { class: 'statement' }, h('tbody', null,
      [['Cash in hand', cap.cash], ['Bank balance', cap.bank], ['Inventory at cost', cap.inventory_value], ['Customers owe you', cap.customer_outstanding],
        ['You owe suppliers', -cap.supplier_outstanding], ['Loans outstanding', -cap.loans_outstanding]].map(([l, v]) => h('tr', { class: 'sub' }, h('td', null, l), h('td', { class: 'num' }, fmt.inr(v)))),
      h('tr', { class: 'total' }, h('td', null, 'Net position'), h('td', { class: 'num' }, fmt.inr(cap.capital_deployed))))),
    h('p', { class: 'muted small' }, 'You can change any of this later from Settings → Opening balances & setup. Add staff accounts under Settings → Staff & permissions.'),
    h('div', { class: 'form-actions' }, h('a', { class: 'btn', href: '#/settings?tab=users' }, 'Add staff accounts'), finish))));
  return root;
}

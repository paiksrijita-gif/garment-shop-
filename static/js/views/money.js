import {
  h, api, state, fmt, can, pageHead, card, table, hashQuery, setHashQuery, field, input, numInput, dateInput, select,
  methodSelect, showError, clearErrors, toast, busy, clientRef, confirmVoid, datePresets,
} from '../core.js';
import { hbarChart, columnChart, chartCard, COLORS } from '../charts.js';
import { loadRefs } from '../app.js';

function presetBar(f, go) {
  return h('div', { class: 'filters' },
    h('div', { class: 'presets' }, datePresets().map((p) => h('button', {
      class: `btn small ${(f.from || '') === p.from && (f.to || '') === p.to ? 'primary' : ''}`, onclick: () => go({ from: p.from, to: p.to }),
    }, p.label))),
    field('From', h('input', { type: 'date', value: f.from || '', onchange: (e) => go({ from: e.target.value }) })),
    field('To', h('input', { type: 'date', value: f.to || '', onchange: (e) => go({ to: e.target.value }) })));
}

// ---------------------------------------------------------------- expenses
export async function expensesView() {
  const f = hashQuery();
  if (!('from' in f)) { const m = datePresets().find((p) => p.key === 'month'); f.from = m.from; f.to = m.to; }
  const go = (patch) => { setHashQuery(Object.assign({}, f, patch)); state.rerender(); };
  const d = await api.get('/api/expenses', { from: f.from, to: f.to, category_id: f.category_id });
  const root = h('div');
  root.append(pageHead('Expenses', 'Operating expenses reduce net operating profit. Stock purchases and capital are not expenses.'));

  if (can('expenses.create')) {
    const form = h('div');
    const date = dateInput('expense_date');
    const cat = select('category_id', state.expenseCategories.map((c) => ({ value: c.id, label: c.name })), (state.expenseCategories[0] || {}).id);
    const addCat = h('button', { class: 'btn small ghost', type: 'button', onclick: async () => {
      const n = prompt('New expense category');
      if (!n) return;
      try { const c = await api.post('/api/expense-categories', { name: n }); await loadRefs(); cat.append(h('option', { value: c.id }, c.name)); cat.value = c.id; }
      catch (ex) { toast(ex.message, 'bad'); }
    } }, '+ New category');
    const amount = numInput('amount', { placeholder: '0.00' });
    const method = methodSelect('method');
    const desc = input('description', { placeholder: 'e.g. October rent' });
    const rec = input('recipient', { placeholder: 'Paid to' });
    let ref = clientRef();
    const save = h('button', { class: 'btn primary', onclick: (e) => busy(e.target, async () => {
      clearErrors(form);
      try {
        await api.post('/api/expenses', { client_ref: ref, expense_date: date.value, category_id: cat.value, amount: amount.value, method: method.value, description: desc.value, recipient: rec.value });
        ref = clientRef();
        toast('Expense saved'); state.rerender();
      } catch (ex) { showError(form, ex); }
    }) }, 'Save expense');
    form.append(h('div', { class: 'form-grid' }, field('Date', date, { required: true }), h('div', null, field('Category', cat, { required: true }), addCat),
      field('Amount (₹)', amount, { required: true }), field('Payment method', method), field('Description', desc), field('Paid to', rec)),
    h('div', { class: 'form-actions' }, save));
    root.append(card('Record an expense', form), h('div', { style: { height: '18px' } }));
  }

  root.append(presetBar(f, go));
  const total = d.rows.filter((r) => r.status === 'final').reduce((a, r) => a + r.amount, 0);
  if (d.summary) {
    root.append(h('div', { class: 'charts', style: { marginBottom: '16px' } },
      chartCard({
        title: 'By category', sub: `Total ${fmt.inr(total)}`,
        chart: hbarChart({ data: d.summary.by_category.map((r) => Object.assign({ label: r.category }, r)), series: [{ key: 'amount', label: 'Amount', color: COLORS.s2 }], emptyText: 'No expenses in this period' }),
        tableFn: () => table([{ key: 'category', label: 'Category' }, { label: 'Amount', num: true, render: (r) => fmt.inr(r.amount) }], d.summary.by_category),
      }),
      chartCard({
        title: 'Monthly totals',
        chart: columnChart({ data: d.summary.by_month.map((r) => Object.assign({ period: r.month }, r)), series: [{ key: 'amount', label: 'Expenses', color: COLORS.s2 }] }),
        tableFn: () => table([{ label: 'Month', render: (r) => fmt.month(r.month) }, { label: 'Amount', num: true, render: (r) => fmt.inr(r.amount) }], d.summary.by_month),
      })));
  }
  root.append(card(`Expense entries · ${fmt.inr(total)}`, table([
    { label: 'Date', render: (r) => fmt.date(r.expense_date) }, { label: 'Category', render: (r) => h('span', null, r.category, ' ', fmt.status(r.status)), cls: 'keep' },
    { label: 'Description', key: 'description' }, { label: 'Paid to', key: 'recipient' }, { label: 'Method', key: 'method' },
    { label: 'Amount', num: true, render: (r) => fmt.inr(r.amount) }, { label: 'By', key: 'created_by_name' },
    { label: '', cls: 'keep', render: (r) => r.status === 'void' ? '' : (can('transactions.void') ? h('button', { class: 'btn small danger', onclick: () => confirmVoid('expenses', r.id, 'expense', state.rerender) }, 'Void') : '') },
  ], d.rows, { empty: 'No expenses in this period.' })));
  return root;
}

// ---------------------------------------------------------------- capital & cash
export async function capitalView() {
  const d = await api.get('/api/cash');
  const s = d.summary;
  const root = h('div');
  root.append(pageHead('Capital & cash', 'Money put in or taken out by owners and lenders — kept separate from revenue and profit'));

  const tile = (label, value, sub) => h('div', { class: 'kpi' }, h('span', { class: 'kpi-label' }, label), h('span', { class: 'kpi-value num' }, value), sub ? h('span', { class: 'kpi-sub' }, sub) : null);
  root.append(h('div', { class: 'kpis' },
    tile('Total capital invested', fmt.inr(s.total_capital_invested), s.opening_capital ? `incl. ${fmt.inr0(s.opening_capital)} before this app` : 'Initial + additional + partners'),
    tile('Owner withdrawals', fmt.inr(s.total_withdrawals)),
    tile('Net capital invested', fmt.inr(s.net_capital)),
    tile('Loans outstanding', fmt.inr(s.loans_outstanding)),
    tile('Cash in hand', fmt.inr(s.cash)), tile('Bank balance', fmt.inr(s.bank)),
    tile('Inventory value (cost)', fmt.inr(s.inventory_value), `${fmt.num(s.inventory_units)} units`),
    tile('Net operating profit to date', fmt.inr(s.net_profit_to_date), 'Accounting profit, all time')));

  const line = (label, value, cls = '') => h('tr', { class: cls }, h('td', null, label), h('td', { class: 'num' }, fmt.inr(value)));
  const head = (label) => h('tr', { class: 'head' }, h('td', { colspan: 2 }, label));
  const ok = Math.abs(s.unreconciled) < 0.05;
  root.append(h('div', { class: 'grid-2', style: { marginTop: '18px' } },
    card('Where the money is now', h('table', { class: 'statement' }, h('tbody', null,
      head('What the business owns'), line('Cash in hand', s.cash, 'sub'), line('Bank balance', s.bank, 'sub'),
      line('Inventory at cost', s.inventory_value, 'sub'), line('Customers owe you', s.customer_outstanding, 'sub'),
      line('Total assets', s.total_assets, 'total'),
      head('What the business owes'), line('Supplier outstanding', s.supplier_outstanding, 'sub'), line('Loans outstanding', s.loans_outstanding, 'sub'),
      line('GST collected not yet paid', s.gst_payable, 'sub'), line('Total liabilities', s.total_liabilities, 'total'),
      line('Capital currently deployed (assets − liabilities)', s.capital_deployed, 'total')))),
    card('How it got there', h('div', null, h('table', { class: 'statement' }, h('tbody', null,
      line('Opening balances when you started', s.opening_equity), line('+ Capital contributed', s.total_contributed),
      line('− Owner withdrawals', -s.total_withdrawals), line('+ Net operating profit to date', s.net_profit_to_date),
      line('= Should equal capital deployed', s.expected_equity, 'total'))),
      h('div', { class: `notice ${ok ? 'good' : 'warn'}`, style: { marginTop: '12px' } }, ok
        ? 'Books reconcile: everything recorded balances to the rupee.'
        : `Difference of ${fmt.inr(s.unreconciled)}. This usually means an opening balance (cash, bank, stock, supplier or customer) has not been recorded yet.`),
      h('p', { class: 'hint', style: { marginTop: '10px' } }, 'Buying stock moves money from cash into inventory — it is not an expense. Its cost reaches profit only when the goods are sold (as COGS).')))));

  const a = s.allocation;
  root.append(h('div', { style: { height: '16px' } }), card('Capital allocation', h('table', { class: 'statement' }, h('tbody', null,
    head('Capital earmarked when contributed'), line('For inventory purchases', a.capital_for_inventory, 'sub'), line('For operating expenses', a.capital_for_expenses, 'sub'), line('General', a.capital_general, 'sub'),
    head('Money actually spent (from all sources)'), line('Paid to suppliers for stock', a.paid_to_suppliers, 'sub'), line('Paid for operating expenses', a.paid_for_expenses, 'sub')))));

  // entry form
  const form = h('div');
  const kinds = Object.entries(d.kinds).map(([value, label]) => ({ value, label }));
  const kind = select('kind', kinds, 'additional_capital');
  const date = dateInput('txn_date');
  const amount = numInput('amount');
  const account = select('account', [{ value: 'bank', label: 'Bank' }, { value: 'cash', label: 'Cash' }], 'bank');
  const party = input('party', { placeholder: 'Owner / partner / lender name' });
  const purpose = select('purpose', [{ value: 'general', label: 'General' }, { value: 'inventory', label: 'Inventory purchases' }, { value: 'expenses', label: 'Operating expenses' }], 'general');
  const notes = input('notes');
  const purposeField = field('Allocated to', purpose);
  const accountField = field('Account', account);
  const syncKind = () => {
    purposeField.classList.toggle('hidden', !['initial_investment', 'additional_capital', 'partner_contribution', 'loan_received'].includes(kind.value));
    accountField.classList.toggle('hidden', ['cash_to_bank', 'bank_to_cash'].includes(kind.value));
  };
  kind.addEventListener('change', syncKind);
  let ref = clientRef();
  const save = h('button', { class: 'btn primary', onclick: (e) => busy(e.target, async () => {
    clearErrors(form);
    try {
      await api.post('/api/cash', { client_ref: ref, kind: kind.value, txn_date: date.value, amount: amount.value, account: account.value, party: party.value, purpose: purpose.value, notes: notes.value });
      ref = clientRef();
      toast('Saved'); state.rerender();
    } catch (ex) { showError(form, ex); }
  }) }, 'Save entry');
  form.append(h('div', { class: 'form-grid' }, field('Type', kind, { class: 'span-2' }), field('Date', date), field('Amount (₹)', amount, { required: true }), accountField,
    field('Name', party), purposeField, field('Notes', notes)), h('div', { class: 'form-actions' }, save));
  syncKind();
  root.append(h('div', { style: { height: '16px' } }), card('Record capital, loan, withdrawal or transfer', form));

  root.append(h('div', { style: { height: '16px' } }), card('All capital & cash entries', table([
    { label: 'Date', render: (r) => fmt.date(r.txn_date) }, { label: 'Type', render: (r) => h('span', null, r.kind_label, ' ', fmt.status(r.status)), cls: 'keep' },
    { label: 'Name', key: 'party' }, { label: 'Account', render: (r) => r.account }, { label: 'Allocated to', render: (r) => r.purpose },
    { label: 'Amount', num: true, render: (r) => fmt.inr(r.amount) }, { label: 'Notes', key: 'notes' },
    { label: '', cls: 'keep', render: (r) => r.status === 'void' ? '' : h('button', { class: 'btn small danger', onclick: () => confirmVoid('cash_transactions', r.id, 'entry', state.rerender) }, 'Void') },
  ], d.rows, { empty: 'Nothing recorded yet. Start with your opening cash and bank balances and the initial investment.' })));
  return root;
}

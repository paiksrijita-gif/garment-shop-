import { h, api, state, fmt, can, pageHead, linkBtn, card, table, hashQuery, setHashQuery, input, dl, confirmVoid } from '../core.js';
import { supplierModal, supplierPaymentModal } from './purchases.js';
import { receiveModal, newCustomerModal } from './sales.js';

export async function supplierList() {
  const f = hashQuery();
  const rows = await api.get('/api/suppliers', { q: f.q });
  const money = can('purchases.view');
  const search = input('q', { placeholder: 'Search name, ID, phone or category', value: f.q || '' });
  search.addEventListener('change', () => { setHashQuery({ q: search.value }); state.rerender(); });
  const totalOut = rows.reduce((a, r) => a + (r.outstanding || 0), 0);
  return h('div', null,
    pageHead('Suppliers', money ? `${rows.length} supplier(s) · total outstanding ${fmt.inr(totalOut)}` : `${rows.length} supplier(s)`, [
      money && can('payments.record') ? h('button', { class: 'btn', onclick: () => supplierPaymentModal() }, 'Pay supplier') : null,
      can('suppliers.manage') ? h('button', { class: 'btn primary', onclick: () => supplierModal({}, () => state.rerender()) }, 'New supplier') : null].filter(Boolean)),
    h('div', { class: 'filters' }, h('div', { style: { flex: '1 1 260px', maxWidth: '380px' } }, search)),
    card(null, table([
      { label: 'ID', key: 'code' }, { label: 'Supplier', render: (r) => h('span', null, r.name, r.active ? '' : h('span', { class: 'badge plain', style: { marginLeft: '6px' } }, 'Inactive')) },
      { label: 'Contact', key: 'phone' }, { label: 'Categories', key: 'categories' },
      money ? { label: 'Units supplied', num: true, render: (r) => fmt.num(r.total_units) } : null,
      money ? { label: 'Purchase value', num: true, render: (r) => fmt.inr(r.total_purchases) } : null,
      money ? { label: 'Paid', num: true, render: (r) => fmt.inr(r.total_paid) } : null,
      money ? { label: 'Outstanding', num: true, render: (r) => h('span', { class: r.outstanding > 0 ? 'neg' : '' }, fmt.inr(r.outstanding)) } : null,
      money ? { label: 'Last purchase', render: (r) => fmt.date(r.last_purchase) } : null,
    ].filter(Boolean), rows, { onRow: money || can('suppliers.manage') ? (r) => { location.hash = `#/suppliers/${r.id}`; } : null, empty: 'No suppliers yet.' })));
}

export async function supplierDetail(id) {
  const s = await api.get(`/api/suppliers/${id}`);
  const money = 'outstanding' in s;
  const root = h('div', null, pageHead(`${s.name}`, `${s.code}${s.phone ? ' · ' + s.phone : ''}`, [
    money && can('payments.record') ? h('button', { class: 'btn', onclick: () => supplierPaymentModal({ id: s.id, name: s.name }, null, s.outstanding) }, 'Record payment') : null,
    can('suppliers.manage') ? h('button', { class: 'btn', onclick: () => supplierModal(s, () => state.rerender()) }, 'Edit') : null,
    can('purchases.create') ? linkBtn('#/purchases/new', 'New purchase', 'primary', 'plus') : null].filter(Boolean)));
  root.append(h('div', { class: 'grid-2' },
    card('Supplier', dl([['Supplier ID', s.code], ['Contact', s.phone || '—'], ['Address', s.address || '—'], s.gstin ? ['GSTIN', s.gstin] : null,
      ['Categories (stated)', s.categories || '—'], ['Categories (from purchases)', (s.supplied_categories || []).join(', ') || '—'], s.notes ? ['Notes', s.notes] : null])),
    money ? card('Balance', h('div', { class: 'totals', style: { maxWidth: 'none' } },
      h('span', null, 'Opening balance'), h('span', { class: 'num' }, fmt.inr(s.opening_balance)),
      h('span', null, `Purchases (${s.purchase_count} bills, ${fmt.num(s.total_units)} units)`), h('span', { class: 'num' }, fmt.inr(s.total_purchases)),
      h('span', null, 'Paid'), h('span', { class: 'num' }, `− ${fmt.inr(s.total_paid)}`),
      h('span', { class: 'grand' }, 'Outstanding payable'), h('span', { class: 'grand num' }, fmt.inr(s.outstanding)))) : null));
  if (money) {
    root.append(h('div', { style: { height: '16px' } }), card('Purchase history', table([
      { label: 'Date', render: (r) => fmt.date(r.purchase_date) }, { label: 'Invoice', render: (r) => h('span', null, r.invoice_no, ' ', fmt.status(r.status)), cls: 'keep' },
      { label: 'Units', num: true, render: (r) => fmt.num(r.units) }, { label: 'Total cost', num: true, render: (r) => fmt.inr(r.total_cost) },
      { label: 'Paid with bill', num: true, render: (r) => fmt.inr(r.amount_paid) },
    ], s.purchases, { onRow: (r) => { location.hash = `#/purchases/${r.id}`; } })));
    root.append(h('div', { style: { height: '16px' } }), card('Products supplied', table([
      { label: 'Product', key: 'product_name' }, { label: 'Category', key: 'category' },
      { label: 'Units', num: true, render: (r) => `${fmt.num(r.units)} ${r.unit}` }, { label: 'Value', num: true, render: (r) => fmt.inr(r.value) },
      { label: 'Last bought', render: (r) => fmt.date(r.last_date) },
    ], s.products, { onRow: (r) => { location.hash = `#/products/${r.product_id}`; } })));
    root.append(h('div', { style: { height: '16px' } }), card('Payments', table([
      { label: 'Date', render: (r) => fmt.date(r.payment_date) }, { label: 'Against bill', render: (r) => r.invoice_no || 'On account' },
      { label: 'Method', key: 'method' }, { label: 'Reference', render: (r) => r.reference || r.notes },
      { label: 'Amount', num: true, render: (r) => fmt.inr(r.amount) },
      { label: '', cls: 'keep', render: (r) => r.status === 'void' ? fmt.status('void') : (!r.with_document && can('transactions.void') ? h('button', { class: 'btn small danger', onclick: () => confirmVoid('supplier_payments', r.id, 'payment', state.rerender) }, 'Void') : '') },
    ], s.payments)));
  }
  return root;
}

export async function customerList() {
  const f = hashQuery();
  const rows = await api.get('/api/customers', { q: f.q });
  const search = input('q', { placeholder: 'Search name or phone', value: f.q || '' });
  search.addEventListener('change', () => { setHashQuery({ q: search.value }); state.rerender(); });
  const out = rows.reduce((a, r) => a + r.outstanding, 0);
  return h('div', null,
    pageHead('Customers', `${rows.length} customer(s) · outstanding credit ${fmt.inr(out)}`, [
      can('customers.manage') ? h('button', { class: 'btn primary', onclick: () => newCustomerModal('', 'retail', () => state.rerender()) }, 'New customer') : null].filter(Boolean)),
    h('div', { class: 'filters' }, h('div', { style: { flex: '1 1 260px', maxWidth: '380px' } }, search)),
    card(null, table([
      { label: 'Customer', key: 'name' }, { label: 'Phone', key: 'phone' }, { label: 'Type', render: (r) => fmt.channel(r.kind) },
      { label: 'Total billed', num: true, render: (r) => fmt.inr(r.total_sales) }, { label: 'Received', num: true, render: (r) => fmt.inr(r.total_received) },
      { label: 'Outstanding', num: true, render: (r) => h('span', { class: r.outstanding > 0 ? 'neg' : '' }, fmt.inr(r.outstanding)) },
      { label: 'Last sale', render: (r) => fmt.date(r.last_sale) },
    ], rows, { onRow: (r) => { location.hash = `#/customers/${r.id}`; }, empty: 'No customers yet. Walk-in sales do not need a customer.' })));
}

export async function customerDetail(id) {
  const c = await api.get(`/api/customers/${id}`);
  const root = h('div', null, pageHead(c.name, `${c.phone || 'No phone'} · ${c.kind}`, [
    can('payments.record') ? h('button', { class: 'btn primary', onclick: () => receiveModal(c.id, c.name, c.outstanding) }, 'Receive payment') : null].filter(Boolean)));
  root.append(h('div', { class: 'grid-2' },
    card('Customer', dl([['Phone', c.phone || '—'], ['Address', c.address || '—'], ['Type', c.kind], c.notes ? ['Notes', c.notes] : null])),
    card('Balance', h('div', { class: 'totals', style: { maxWidth: 'none' } },
      h('span', null, 'Opening balance'), h('span', { class: 'num' }, fmt.inr(c.opening_balance)),
      h('span', null, 'Total billed'), h('span', { class: 'num' }, fmt.inr(c.total_sales)),
      h('span', null, 'Received'), h('span', { class: 'num' }, `− ${fmt.inr(c.total_received)}`),
      h('span', null, 'Return credits'), h('span', { class: 'num' }, `− ${fmt.inr(c.return_credits)}`),
      h('span', { class: 'grand' }, 'Outstanding'), h('span', { class: 'grand num' }, fmt.inr(c.outstanding))))));
  root.append(h('div', { style: { height: '16px' } }), card('Sales', table([
    { label: 'Date', render: (r) => fmt.date(r.sale_date) }, { label: 'Invoice', render: (r) => h('span', null, r.invoice_no, ' ', fmt.status(r.status)), cls: 'keep' },
    { label: 'Channel', render: (r) => fmt.channel(r.channel), cls: 'keep' }, { label: 'Total', num: true, render: (r) => fmt.inr(r.total_amount) },
    { label: 'Paid at sale', num: true, render: (r) => fmt.inr(r.amount_received) },
  ], c.sales, { onRow: (r) => { location.hash = `#/sales/${r.id}`; } })));
  root.append(h('div', { style: { height: '16px' } }), card('Payments', table([
    { label: 'Date', render: (r) => fmt.date(r.payment_date) }, { label: 'Invoice', render: (r) => r.invoice_no || 'On account' },
    { label: 'Method', key: 'method' }, { label: 'Note', render: (r) => r.reference || r.notes }, { label: 'Amount', num: true, render: (r) => fmt.inr(r.amount) },
    { label: '', cls: 'keep', render: (r) => r.status === 'void' ? fmt.status('void') : (!r.with_document && can('transactions.void') ? h('button', { class: 'btn small danger', onclick: () => confirmVoid('customer_payments', r.id, 'receipt', state.rerender) }, 'Void') : '') },
  ], c.payments)));
  return root;
}

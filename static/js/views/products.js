import {
  h, api, state, fmt, can, pageHead, linkBtn, card, table, hashQuery, setHashQuery, field, input, numInput, select,
  showError, toast, modal, busy, dl, icon,
} from '../core.js';
import { loadRefs } from '../app.js';

const UNITS = ['piece', 'set', 'pair', 'dozen', 'metre', 'box'];
const split = (v) => v.split(',').map((x) => x.trim()).filter(Boolean);

export async function productList() {
  const f = hashQuery();
  const rows = await api.get('/api/products', { q: f.q, category_id: f.category_id, all: f.all });
  const showCost = can('inventory.cost');
  const search = input('q', { placeholder: 'Search name, SKU or category', value: f.q || '' });
  search.addEventListener('change', () => { setHashQuery(Object.assign({}, f, { q: search.value })); state.rerender(); });
  const cat = select('category_id', [{ value: '', label: 'All categories' }].concat(state.categories.map((c) => ({ value: c.id, label: c.name }))), f.category_id || '',
    { onchange: (e) => { setHashQuery(Object.assign({}, f, { category_id: e.target.value })); state.rerender(); } });
  return h('div', null,
    pageHead('Products', `${rows.length} product(s)`, [can('products.manage') ? linkBtn('#/products/new', 'New product', 'primary', 'plus') : null].filter(Boolean)),
    h('div', { class: 'filters' }, h('div', { style: { flex: '1 1 260px', maxWidth: '380px' } }, search), h('div', { style: { minWidth: '180px' } }, cat),
      h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: !!f.all, onchange: (e) => { setHashQuery(Object.assign({}, f, { all: e.target.checked ? '1' : '' })); state.rerender(); } }), 'Show inactive')),
    card(null, table([
      { label: 'Product / design', render: (r) => h('span', null, r.name, r.active ? '' : h('span', { class: 'badge plain', style: { marginLeft: '6px' } }, 'Inactive')) },
      { label: 'Category', key: 'category' }, { label: 'Unit', key: 'unit' },
      { label: 'Tracking', render: (r) => r.has_variants ? `${r.variant_count} variants` : 'Simple' },
      { label: 'In stock', num: true, render: (r) => fmt.num(r.stock_qty) },
      showCost ? { label: 'Value at cost', num: true, render: (r) => fmt.inr(r.stock_value) } : null,
      { label: 'Retail price', num: true, render: (r) => r.min_retail === r.max_retail ? fmt.inr(r.min_retail) : `${fmt.inr0(r.min_retail)}–${fmt.inr0(r.max_retail)}` },
    ].filter(Boolean), rows, {
      onRow: (r) => { location.hash = `#/products/${r.id}`; },
      empty: 'No products yet. Add your designs and their sizes / colours.',
      emptyAction: can('products.manage') ? h('div', null, linkBtn('#/products/new', 'Add a product', 'primary')) : null,
    })));
}

// Product form shared by the full page and the quick-create modal.
function productFields(initial = {}) {
  const name = input('name', { value: initial.name || '', placeholder: 'e.g. Chanderi silk kurti — design 204' });
  const catSel = select('category_id', state.categories.map((c) => ({ value: c.id, label: c.name })), initial.category_id || (state.categories[0] || {}).id);
  const addCat = h('button', { class: 'btn small ghost', type: 'button', onclick: async () => {
    const n = prompt('New category name');
    if (!n) return;
    try {
      const c = await api.post('/api/categories', { name: n });
      await loadRefs();
      catSel.append(h('option', { value: c.id }, c.name));
      catSel.value = c.id;
    } catch (ex) { toast(ex.message, 'bad'); }
  } }, '+ New category');
  const unit = select('unit', UNITS.map((u) => ({ value: u, label: u })), initial.unit || 'piece');
  const low = numInput('low_stock_level', { value: initial.low_stock_level ?? state.settings.low_stock_default ?? 5 });
  const desc = input('description', { value: initial.description || '' });
  let mode = 'simple';
  const seg = h('div', { class: 'seg', role: 'tablist' });
  const simpleBox = h('div', { class: 'form-grid' });
  const variantBox = h('div', { class: 'stack hidden' });
  const sku = input('variants.0.sku', { placeholder: 'Auto if blank' });
  const retail = numInput('variants.0.retail_price', { placeholder: '0.00' });
  const whole = numInput('variants.0.wholesale_price', { placeholder: '0.00' });
  simpleBox.append(field('SKU', sku), field('Retail selling price (₹)', retail), field('Wholesale price (₹)', whole));
  const sizes = input('sizes', { placeholder: 'S, M, L, XL' });
  const colours = input('colours', { placeholder: 'Red, Blue' });
  const designs = input('designs', { placeholder: 'optional, e.g. Floral, Plain' });
  const vRetail = numInput('v_retail', { placeholder: '0.00' });
  const vWhole = numInput('v_whole', { placeholder: '0.00' });
  const grid = h('div');
  let rows = [];
  const regen = () => {
    const S = split(sizes.value), C = split(colours.value), D = split(designs.value);
    const combos = [];
    for (const sz of S.length ? S : ['']) for (const co of C.length ? C : ['']) for (const de of D.length ? D : ['']) if (sz || co || de) combos.push({ size: sz, colour: co, design: de });
    rows = combos.map((c, i) => Object.assign(c, {
      retail: numInput(`variants.${i}.retail_price`, { value: vRetail.value }),
      whole: numInput(`variants.${i}.wholesale_price`, { value: vWhole.value }),
      sku: input(`variants.${i}.sku`, { placeholder: 'auto' }),
    }));
    grid.replaceChildren(rows.length ? h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, ['Size', 'Colour', 'Design', 'SKU', 'Retail ₹', 'Wholesale ₹'].map((x) => h('th', null, x)))),
      h('tbody', null, rows.map((r) => h('tr', null, h('td', null, r.size), h('td', null, r.colour), h('td', null, r.design),
        h('td', null, r.sku), h('td', null, r.retail), h('td', null, r.whole)))))) : h('div', { class: 'hint' }, 'Enter sizes and/or colours to generate variants.'));
  };
  [sizes, colours, designs, vRetail, vWhole].forEach((el) => el.addEventListener('change', regen));
  variantBox.append(h('div', { class: 'form-grid' }, field('Sizes', sizes, { hint: 'Comma separated' }), field('Colours', colours), field('Designs', designs),
    field('Default retail price', vRetail), field('Default wholesale price', vWhole)), grid);
  const setMode = (m) => {
    mode = m;
    seg.querySelectorAll('button').forEach((b) => b.classList.toggle('on', b.dataset.m === m));
    simpleBox.classList.toggle('hidden', m !== 'simple');
    variantBox.classList.toggle('hidden', m !== 'variants');
    regen();
  };
  seg.append(h('button', { type: 'button', dataset: { m: 'simple' }, onclick: () => setMode('simple') }, 'Simple — one design, one stock count'),
    h('button', { type: 'button', dataset: { m: 'variants' }, onclick: () => setMode('variants') }, 'Variants — by size / colour / design'));
  setMode('simple');
  const el = h('div', { class: 'stack' },
    h('div', { class: 'form-grid' },
      field('Product name / design', name, { required: true, class: 'span-2' }),
      h('div', null, field('Category', catSel, { required: true }), addCat),
      field('Unit', unit, { hint: 'How quantity is counted' }),
      field('Low-stock alert at', low, { hint: 'Per variant' }),
      field('Description', desc, { class: 'span-2' })),
    h('div', null, h('div', { class: 'small', style: { fontWeight: 600, marginBottom: '6px' } }, 'How to track stock'), seg),
    simpleBox, variantBox);
  const data = () => {
    const d = { name: name.value, category_id: catSel.value, unit: unit.value, low_stock_level: low.value, description: desc.value, has_variants: mode === 'variants' };
    if (mode === 'simple') { d.sku = sku.value; d.retail_price = retail.value; d.wholesale_price = whole.value; }
    else d.variants = rows.map((r) => ({ size: r.size, colour: r.colour, design: r.design, sku: r.sku.value, retail_price: r.retail.value, wholesale_price: r.whole.value }));
    return d;
  };
  return { el, data };
}

export function productModal(initial, onSaved) {
  const pf = productFields(initial);
  modal({ title: 'New product', body: pf.el, wide: true, actions: [
    (m) => h('button', { class: 'btn', onclick: m.close }, 'Cancel'),
    (m) => h('button', { class: 'btn primary', onclick: async (e) => busy(e.target, async () => {
      try {
        const r = await api.post('/api/products', pf.data());
        m.close(); toast('Product created'); onSaved && onSaved(r.id);
      } catch (ex) { showError(pf.el, ex); }
    }) }, 'Create product'),
  ] });
}

export async function productNew() {
  const pf = productFields();
  const save = h('button', { class: 'btn primary', onclick: async (e) => busy(e.target, async () => {
    try {
      const r = await api.post('/api/products', pf.data());
      toast('Product created');
      location.hash = `#/products/${r.id}`;
    } catch (ex) { showError(pf.el, ex); }
  }) }, 'Create product');
  return h('div', null, pageHead('New product', 'Stock is added through purchases or opening stock, not here'),
    card(null, pf.el), h('div', { class: 'form-actions' }, h('a', { class: 'btn', href: '#/products' }, 'Cancel'), save));
}

export async function productDetail(id) {
  const p = await api.get(`/api/products/${id}`);
  const showCost = can('inventory.cost');
  const manage = can('products.manage');
  const total = p.variants.reduce((a, v) => a + v.stock_qty, 0);
  const root = h('div', null, pageHead(p.name, `${p.category} · ${p.unit} · ${fmt.num(total)} in stock`, [
    manage ? h('button', { class: 'btn', onclick: () => editModal(p) }, 'Edit') : null,
    manage ? h('button', { class: 'btn', onclick: () => addVariantsModal(p) }, 'Add variants') : null,
    can('reports.view') ? linkBtn(`#/sales?product_id=${p.id}&product_name=${encodeURIComponent(p.name)}`, 'Sales of this product') : null,
  ].filter(Boolean)));
  root.append(card('Details', dl([['Category', p.category], ['Unit', p.unit], ['Low-stock alert at', fmt.num(p.low_stock_level)],
    ['Tracking', p.has_variants ? 'Variants by size / colour / design' : 'Simple'], ['Status', p.active ? 'Active' : 'Inactive'],
    p.description ? ['Description', p.description] : null])));
  root.append(h('div', { style: { height: '16px' } }), card('Variants and stock', table([
    { label: 'SKU', key: 'sku' }, { label: 'Size', key: 'size' }, { label: 'Colour', key: 'colour' }, { label: 'Design', key: 'design' },
    { label: 'In stock', num: true, render: (v) => h('span', { class: v.stock_qty <= 0 ? 'neg' : (v.stock_qty <= p.low_stock_level ? 'neg' : '') }, fmt.num(v.stock_qty)) },
    showCost ? { label: 'Avg cost', num: true, render: (v) => v.stock_qty > 0 ? fmt.inr(v.stock_value / v.stock_qty) : '—' } : null,
    showCost ? { label: 'Value', num: true, render: (v) => fmt.inr(v.stock_value) } : null,
    { label: 'Retail', num: true, render: (v) => fmt.inr(v.retail_price) },
    { label: 'Wholesale', num: true, render: (v) => fmt.inr(v.wholesale_price) },
    { label: '', render: (v) => h('span', { class: 'row', style: { gap: '4px', flexWrap: 'nowrap' } },
      can('inventory.view') ? h('a', { class: 'btn small', href: `#/inventory/ledger/${v.id}`, onclick: (e) => e.stopPropagation() }, 'Ledger') : null,
      manage ? h('button', { class: 'btn small', onclick: () => priceModal(v) }, 'Prices') : null) },
  ].filter(Boolean), p.variants)));
  return root;
}

function editModal(p) {
  const name = input('name', { value: p.name });
  const cat = select('category_id', state.categories.map((c) => ({ value: c.id, label: c.name })), p.category_id);
  const unit = select('unit', UNITS.map((u) => ({ value: u, label: u })), p.unit);
  const low = numInput('low_stock_level', { value: p.low_stock_level });
  const desc = input('description', { value: p.description });
  const active = h('input', { type: 'checkbox', checked: !!p.active });
  const body = h('div', { class: 'form-grid' }, field('Name', name, { class: 'span-2' }), field('Category', cat), field('Unit', unit),
    field('Low-stock alert at', low), field('Description', desc), h('label', { class: 'check' }, active, 'Active (shown in sale & purchase search)'));
  modal({ title: 'Edit product', body, wide: true, actions: [
    (m) => h('button', { class: 'btn', onclick: m.close }, 'Cancel'),
    (m) => h('button', { class: 'btn primary', onclick: async (e) => busy(e.target, async () => {
      try {
        await api.put(`/api/products/${p.id}`, { name: name.value, category_id: cat.value, unit: unit.value, low_stock_level: low.value, description: desc.value, active: active.checked });
        m.close(); toast('Saved'); state.rerender();
      } catch (ex) { showError(body, ex); }
    }) }, 'Save'),
  ] });
}

function priceModal(v) {
  const r = numInput('retail_price', { value: v.retail_price });
  const w = numInput('wholesale_price', { value: v.wholesale_price });
  const active = h('input', { type: 'checkbox', checked: !!v.active });
  const body = h('div', { class: 'form-grid' }, field('Retail price', r), field('Wholesale price', w), h('label', { class: 'check' }, active, 'Active'));
  modal({ title: `Prices — ${v.sku}`, body, actions: [
    (m) => h('button', { class: 'btn', onclick: m.close }, 'Cancel'),
    (m) => h('button', { class: 'btn primary', onclick: async () => {
      try { await api.put(`/api/variants/${v.id}`, { retail_price: r.value, wholesale_price: w.value, active: active.checked }); m.close(); toast('Prices updated'); state.rerender(); }
      catch (ex) { showError(body, ex); }
    } }, 'Save'),
  ] });
}

function addVariantsModal(p) {
  const sizes = input('sizes', { placeholder: 'S, M, L' });
  const colours = input('colours', { placeholder: 'Red, Blue' });
  const designs = input('designs');
  const r = numInput('retail', { value: (p.variants[0] || {}).retail_price || '' });
  const w = numInput('whole', { value: (p.variants[0] || {}).wholesale_price || '' });
  const body = h('div', { class: 'stack' }, h('div', { class: 'form-grid' }, field('Sizes', sizes), field('Colours', colours), field('Designs', designs), field('Retail price', r), field('Wholesale price', w)),
    h('div', { class: 'hint' }, 'Every combination of the values you enter is created. Existing combinations are rejected.'));
  modal({ title: `Add variants — ${p.name}`, body, wide: true, actions: [
    (m) => h('button', { class: 'btn', onclick: m.close }, 'Cancel'),
    (m) => h('button', { class: 'btn primary', onclick: async (e) => busy(e.target, async () => {
      const S = split(sizes.value), C = split(colours.value), D = split(designs.value);
      const variants = [];
      for (const sz of S.length ? S : ['']) for (const co of C.length ? C : ['']) for (const de of D.length ? D : ['']) if (sz || co || de) variants.push({ size: sz, colour: co, design: de, retail_price: r.value, wholesale_price: w.value });
      try { await api.post(`/api/products/${p.id}/variants`, { variants }); m.close(); toast(`${variants.length} variant(s) added`); state.rerender(); }
      catch (ex) { showError(body, ex); }
    }) }, 'Add'),
  ] });
}

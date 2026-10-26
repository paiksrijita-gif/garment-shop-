import { h, api, state, can, isOwner, icon, toast, field, input, showError, busy } from './core.js';
import { dashboardView, homeView } from './views/dashboard.js';
import { salesList, saleForm, saleDetail } from './views/sales.js';
import { purchaseList, purchaseForm, purchaseDetail } from './views/purchases.js';
import { inventoryView, ledgerView } from './views/inventory.js';
import { productList, productDetail, productNew } from './views/products.js';
import { supplierList, supplierDetail, customerList, customerDetail } from './views/parties.js';
import { expensesView, capitalView } from './views/money.js';
import { profitView, reportsView, reportView } from './views/reports.js';
import { settingsView, setupWizard } from './views/settings.js';

const NAV = [
  { group: null, items: [
    { href: '#/', label: 'Dashboard', icon: 'dashboard', match: /^\/$/ },
  ] },
  { group: 'Daily entry', items: [
    { href: '#/sales', label: 'Sales', icon: 'sale', perm: ['sales.create', 'sales.view_all'], match: /^\/sales/ },
    { href: '#/purchases', label: 'Purchases', icon: 'purchase', perm: ['purchases.create', 'purchases.view'], match: /^\/purchases/ },
    { href: '#/expenses', label: 'Expenses', icon: 'expense', perm: ['expenses.create', 'reports.view'], match: /^\/expenses/ },
  ] },
  { group: 'Stock', items: [
    { href: '#/inventory', label: 'Inventory', icon: 'inventory', perm: ['inventory.view'], match: /^\/inventory/ },
    { href: '#/products', label: 'Products', icon: 'product', perm: ['products.manage', 'inventory.view'], match: /^\/products/ },
  ] },
  { group: 'People', items: [
    { href: '#/suppliers', label: 'Suppliers', icon: 'supplier', perm: ['suppliers.manage', 'purchases.view'], match: /^\/suppliers/ },
    { href: '#/customers', label: 'Customers', icon: 'customer', perm: ['customers.manage', 'payments.record'], match: /^\/customers/ },
  ] },
  { group: 'Money', items: [
    { href: '#/profit', label: 'Revenue & Profit', icon: 'profit', perm: ['reports.view'], match: /^\/profit/ },
    { href: '#/capital', label: 'Capital & Cash', icon: 'capital', perm: ['owner'], match: /^\/capital/ },
    { href: '#/reports', label: 'Reports', icon: 'report', perm: ['reports.view'], match: /^\/reports/ },
  ] },
  { group: null, items: [
    { href: '#/settings', label: 'Settings', icon: 'settings', perm: ['owner'], match: /^\/settings|^\/setup/ },
  ] },
];

const ROUTES = [
  [/^\/$/, () => (can('reports.view') ? dashboardView() : homeView())],
  [/^\/sales$/, salesList], [/^\/sales\/new$/, saleForm], [/^\/sales\/(\d+)$/, saleDetail],
  [/^\/purchases$/, purchaseList], [/^\/purchases\/new$/, purchaseForm], [/^\/purchases\/(\d+)$/, purchaseDetail],
  [/^\/inventory$/, inventoryView], [/^\/inventory\/ledger\/(\d+)$/, ledgerView],
  [/^\/products$/, productList], [/^\/products\/new$/, productNew], [/^\/products\/(\d+)$/, productDetail],
  [/^\/suppliers$/, supplierList], [/^\/suppliers\/(\d+)$/, supplierDetail],
  [/^\/customers$/, customerList], [/^\/customers\/(\d+)$/, customerDetail],
  [/^\/expenses$/, expensesView], [/^\/capital$/, capitalView],
  [/^\/profit$/, profitView], [/^\/reports$/, reportsView], [/^\/reports\/([a-z-]+)$/, reportView],
  [/^\/settings$/, settingsView], [/^\/setup$/, setupWizard],
];

const app = document.getElementById('app');
let shell = null, main = null, navEl = null, titleEl = null;

function path() { return (location.hash.slice(1).split('?')[0]) || '/'; }

async function boot() {
  let st;
  try {
    st = await api.get('/api/status');
  } catch (e) {
    app.replaceChildren(h('div', { class: 'auth' }, h('div', { class: 'card' }, h('h1', null, 'Cannot connect'), h('p', null, e.message))));
    return;
  }
  state.today = st.today;
  state.shopName = st.shop_name;
  if (st.needs_owner) return ownerSetup();
  if (!st.user) return loginView();
  state.user = st.user;
  await loadRefs();
  renderShell();
  if (isOwner() && state.settings.setup_complete !== '1' && path() === '/') location.hash = '#/setup';
  route();
}

export async function loadRefs() {
  const [settings, cats, ecats] = await Promise.all([
    api.get('/api/settings'), api.get('/api/categories'), api.get('/api/expense-categories')]);
  state.settings = settings;
  state.categories = cats;
  state.expenseCategories = ecats;
  state.shopName = settings.shop_name;
}

function authCard(title, sub, form) {
  app.replaceChildren(h('div', { class: 'auth' }, h('div', { class: 'card' },
    h('div', { class: 'brand', style: { padding: '0 0 14px' } }, h('div', { class: 'brand-mark' }, icon('product')),
      h('div', null, h('div', { class: 'brand-name' }, state.shopName || 'Garment Shop'), h('div', { class: 'brand-sub' }, 'Inventory · Sales · Profit'))),
    h('h1', null, title), h('p', { class: 'muted small' }, sub), form)));
}

function loginView() {
  const u = input('username', { autocomplete: 'username', autocapitalize: 'none' });
  const p = input('password', { type: 'password', autocomplete: 'current-password' });
  const btn = h('button', { class: 'btn primary', type: 'submit', style: { width: '100%' } }, 'Sign in');
  const form = h('form', { class: 'stack', onsubmit: async (e) => {
    e.preventDefault();
    await busy(btn, async () => {
      try {
        const r = await api.post('/api/login', { username: u.value, password: p.value });
        state.user = r.user;
        location.hash = '#/';
        await loadRefs();
        renderShell();
        route();
      } catch (ex) { showError(form, ex); }
    });
  } }, field('Username', u), field('Password', p), btn);
  authCard('Sign in', 'Owner and staff sign in with their own account.', form);
  u.focus();
}

function ownerSetup() {
  const shop = input('shop_name', { placeholder: 'e.g. Lakshmi Garments' });
  const name = input('full_name', { autocomplete: 'name' });
  const u = input('username', { autocomplete: 'username', autocapitalize: 'none' });
  const p = input('password', { type: 'password', autocomplete: 'new-password' });
  const p2 = input('password2', { type: 'password', autocomplete: 'new-password' });
  const btn = h('button', { class: 'btn primary', type: 'submit', style: { width: '100%' } }, 'Create owner account');
  const form = h('form', { class: 'stack', onsubmit: async (e) => {
    e.preventDefault();
    if (p.value !== p2.value) return showError(form, { field: 'password2', message: 'Passwords do not match' });
    await busy(btn, async () => {
      try {
        const r = await api.post('/api/setup/owner', { shop_name: shop.value, full_name: name.value, username: u.value, password: p.value });
        state.user = r.user;
        await loadRefs();
        location.hash = '#/setup';
        renderShell();
        route();
      } catch (ex) { showError(form, ex); }
    });
  } },
  field('Shop name', shop, { required: true }), field('Your name', name, { required: true }),
  field('Username', u, { required: true, hint: 'Letters and numbers, used to sign in' }),
  field('Password', p, { required: true, hint: 'At least 8 characters' }), field('Confirm password', p2, { required: true }), btn);
  authCard('Welcome — set up your shop', 'Create the owner account. You will add staff accounts and opening balances next.', form);
  shop.focus();
}

function renderShell() {
  navEl = h('nav', { class: 'nav', 'aria-label': 'Main' });
  for (const g of NAV) {
    const items = g.items.filter((it) => !it.perm || it.perm.some(can));
    if (!items.length) continue;
    if (g.group) navEl.append(h('div', { class: 'nav-group' }, g.group));
    for (const it of items) navEl.append(h('a', { href: it.href, dataset: { match: it.match.source } }, icon(it.icon), it.label));
  }
  const u = state.user;
  const sidebar = h('aside', { class: 'sidebar' },
    h('a', { class: 'brand', href: '#/', style: { color: 'inherit', textDecoration: 'none' } },
      h('div', { class: 'brand-mark' }, icon('product')),
      h('div', null, h('div', { class: 'brand-name' }, state.shopName), h('div', { class: 'brand-sub' }, 'Garment Shop Manager'))),
    navEl,
    h('div', { class: 'sidebar-foot' },
      h('div', { style: { fontWeight: 600 } }, u.full_name),
      h('div', { class: 'muted small' }, u.role === 'owner' ? 'Owner' : 'Staff', ' · @', u.username),
      h('div', { class: 'row', style: { marginTop: '8px' } },
        h('button', { class: 'btn small', onclick: changePassword }, 'Password'),
        h('button', { class: 'btn small', onclick: logout }, icon('logout'), 'Sign out'))));
  titleEl = h('div', { class: 'title' }, state.shopName);
  const topbar = h('header', { class: 'topbar' },
    h('button', { class: 'icon-btn', 'aria-label': 'Menu', onclick: () => shell.classList.toggle('nav-open') }, icon('menu')),
    titleEl);
  main = h('main', { class: 'main', id: 'main' });
  const mobileActions = h('div', { class: 'mobile-actions' },
    can('sales.create') ? h('a', { class: 'btn primary', href: '#/sales/new' }, icon('plus'), 'New sale') : null,
    can('purchases.create') ? h('a', { class: 'btn', href: '#/purchases/new' }, icon('plus'), 'New purchase') : null);
  shell = h('div', { class: 'shell', onclick: (e) => { if (e.target === shell) shell.classList.remove('nav-open'); } },
    sidebar, h('div', null, topbar, main), mobileActions);
  sidebar.addEventListener('click', (e) => { if (e.target.closest('a')) shell.classList.remove('nav-open'); });
  app.replaceChildren(shell);
}

async function logout() {
  await api.post('/api/logout').catch(() => {});
  state.user = null;
  location.hash = '#/';
  loginView();
}

function changePassword() {
  import('./core.js').then(({ modal }) => {
    const cur = input('current_password', { type: 'password', autocomplete: 'current-password' });
    const nw = input('new_password', { type: 'password', autocomplete: 'new-password' });
    const body = h('div', { class: 'stack' }, field('Current password', cur), field('New password', nw, { hint: 'At least 8 characters' }));
    modal({ title: 'Change password', body, actions: [
      (m) => h('button', { class: 'btn', onclick: m.close }, 'Cancel'),
      (m) => h('button', { class: 'btn primary', onclick: async () => {
        try { await api.post('/api/me/password', { current_password: cur.value, new_password: nw.value }); m.close(); toast('Password changed'); }
        catch (ex) { showError(body, ex); }
      } }, 'Save'),
    ] });
  });
}

let routeSeq = 0;
async function route() {
  if (!state.user) return;
  const p = path();
  for (const a of navEl.querySelectorAll('a')) a.classList.toggle('active', new RegExp(a.dataset.match).test(p));
  const hit = ROUTES.find(([rx]) => rx.test(p));
  const my = ++routeSeq;
  main.replaceChildren(h('div', { class: 'muted' }, 'Loading…'));
  try {
    const view = hit ? await hit[1](...p.match(hit[0]).slice(1)) : h('div', { class: 'empty' }, 'Page not found');
    if (my !== routeSeq) return;
    main.replaceChildren(view);
    const t = view.querySelector && view.querySelector('h1');
    titleEl.textContent = t ? t.textContent : state.shopName;
    document.title = `${titleEl.textContent} · ${state.shopName}`;
    window.scrollTo(0, 0);
  } catch (e) {
    if (my !== routeSeq) return;
    main.replaceChildren(h('div', { class: 'notice bad' }, e.status === 403 ? 'You do not have access to this page.' : e.message));
  }
}

// Filter-only changes use history.replaceState, which does not fire hashchange.
window.addEventListener('hashchange', route);
state.rerender = route;

boot();

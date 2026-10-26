// Shared helpers: DOM builder, API client, formatting, toasts, modals, forms.

export const state = { user: null, settings: {}, categories: [], expenseCategories: [], today: null, shopName: '' };

// ---------------------------------------------------------------- DOM
export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v === undefined || v === null || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
      else if (k === 'dataset') Object.assign(el.dataset, v);
      else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
      else if (k === 'value') el.value = v;
      else if (k === 'checked') el.checked = !!v;
      else if (k === 'html') el.innerHTML = v; // only used with static strings (icons)
      else el.setAttribute(k, v === true ? '' : v);
    }
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const c of children) {
    if (c === null || c === undefined || c === false) continue;
    if (Array.isArray(c)) append(el, c);
    else el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}

export const svgNS = 'http://www.w3.org/2000/svg';
export function s(tag, attrs, ...children) {
  const el = document.createElementNS(svgNS, tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
    else el.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

const ICONS = {
  dashboard: '<path d="M3 13h8V3H3v10zm0 8h8v-6H3v6zm10 0h8V11h-8v10zm0-18v6h8V3h-8z"/>',
  sale: '<path d="M7 18c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zM1 2v2h2l3.6 7.6-1.4 2.4c-.1.3-.2.6-.2 1 0 1.1.9 2 2 2h12v-2H7.4c-.1 0-.2-.1-.2-.2v-.1l.9-1.7h7.4c.8 0 1.4-.4 1.7-1l3.6-6.5c.1-.2.1-.3.1-.5 0-.6-.4-1-1-1H5.2l-.9-2H1zm16 16c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2z"/>',
  purchase: '<path d="M20 8h-3V4H3c-1.1 0-2 .9-2 2v11h2c0 1.7 1.3 3 3 3s3-1.3 3-3h6c0 1.7 1.3 3 3 3s3-1.3 3-3h2v-5l-3-4zM6 18.5c-.8 0-1.5-.7-1.5-1.5s.7-1.5 1.5-1.5 1.5.7 1.5 1.5-.7 1.5-1.5 1.5zm13.5-9 2 2.5H17V9.5h2.5zM18 18.5c-.8 0-1.5-.7-1.5-1.5s.7-1.5 1.5-1.5 1.5.7 1.5 1.5-.7 1.5-1.5 1.5z"/>',
  inventory: '<path d="M20 2H4c-1 0-2 .9-2 2v3c0 .7.4 1.4 1 1.7V20c0 1.1 1.1 2 2 2h14c.9 0 2-.9 2-2V8.7c.6-.3 1-1 1-1.7V4c0-1.1-1-2-2-2zm-5 12H9v-2h6v2zm5-7H4V4h16v3z"/>',
  product: '<path d="M16 3l-4 2-4-2-6 3 2 5 2-1v11h12V10l2 1 2-5-6-3z"/>',
  supplier: '<path d="M12 7V3H2v18h20V7H12zM6 19H4v-2h2v2zm0-4H4v-2h2v2zm0-4H4V9h2v2zm0-4H4V5h2v2zm4 12H8v-2h2v2zm0-4H8v-2h2v2zm0-4H8V9h2v2zm0-4H8V5h2v2zm10 12h-8v-2h2v-2h-2v-2h2v-2h-2V9h8v10zm-2-8h-2v2h2v-2zm0 4h-2v2h2v-2z"/>',
  customer: '<path d="M16 11c1.7 0 3-1.3 3-3s-1.3-3-3-3-3 1.3-3 3 1.3 3 3 3zm-8 0c1.7 0 3-1.3 3-3S9.7 5 8 5 5 6.3 5 8s1.3 3 3 3zm0 2c-2.3 0-7 1.2-7 3.5V19h14v-2.5C15 14.2 10.3 13 8 13zm8 0c-.3 0-.6 0-1 .1 1.2.8 2 2 2 3.4V19h6v-2.5c0-2.3-4.7-3.5-7-3.5z"/>',
  expense: '<path d="M19 14V6c0-1.1-.9-2-2-2H3c-1.1 0-2 .9-2 2v8c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2zm-9-1c-1.7 0-3-1.3-3-3s1.3-3 3-3 3 1.3 3 3-1.3 3-3 3zm13-6v11c0 1.1-.9 2-2 2H4v-2h17V7h2z"/>',
  capital: '<path d="M4 10v7h3v-7H4zm6 0v7h3v-7h-3zM2 22h19v-3H2v3zm14-12v7h3v-7h-3zm-4.5-9L2 6v2h19V6l-9.5-5z"/>',
  profit: '<path d="M16 6l2.3 2.3-4.9 4.9-4-4L2 16.6 3.4 18l6-6 4 4 6.3-6.3L22 12V6z"/>',
  report: '<path d="M14 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z"/>',
  settings: '<path d="M19.1 12.9c0-.3.1-.6.1-.9s0-.6-.1-.9l2-1.6c.2-.1.2-.4.1-.6l-1.9-3.3c-.1-.2-.4-.3-.6-.2l-2.4 1c-.5-.4-1-.7-1.6-.9L14.4 3c0-.2-.2-.4-.5-.4h-3.8c-.2 0-.4.2-.5.4l-.4 2.5c-.6.2-1.1.6-1.6.9l-2.4-1c-.2-.1-.5 0-.6.2L2.7 8.9c-.1.2-.1.5.1.6l2 1.6c0 .3-.1.6-.1.9s0 .6.1.9l-2 1.6c-.2.1-.2.4-.1.6l1.9 3.3c.1.2.4.3.6.2l2.4-1c.5.4 1 .7 1.6.9l.4 2.5c0 .2.2.4.5.4h3.8c.2 0 .4-.2.5-.4l.4-2.5c.6-.2 1.1-.6 1.6-.9l2.4 1c.2.1.5 0 .6-.2l1.9-3.3c.1-.2.1-.5-.1-.6l-2.1-1.6zM12 15.5c-1.9 0-3.5-1.6-3.5-3.5s1.6-3.5 3.5-3.5 3.5 1.6 3.5 3.5-1.6 3.5-3.5 3.5z"/>',
  home: '<path d="M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z"/>',
  plus: '<path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/>',
  menu: '<path d="M3 18h18v-2H3v2zm0-5h18v-2H3v2zm0-7v2h18V6H3z"/>',
  close: '<path d="M19 6.4 17.6 5 12 10.6 6.4 5 5 6.4 10.6 12 5 17.6 6.4 19 12 13.4 17.6 19 19 17.6 13.4 12z"/>',
  download: '<path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/>',
  trash: '<path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/>',
  print: '<path d="M19 8H5c-1.7 0-3 1.3-3 3v6h4v4h12v-4h4v-6c0-1.7-1.3-3-3-3zm-3 11H8v-5h8v5zm3-7c-.6 0-1-.4-1-1s.4-1 1-1 1 .4 1 1-.4 1-1 1zm-1-9H6v4h12V3z"/>',
  back: '<path d="M20 11H7.8l5.6-5.6L12 4l-8 8 8 8 1.4-1.4L7.8 13H20v-2z"/>',
  logout: '<path d="M10.1 15.6 11.5 17l5-5-5-5-1.4 1.4 2.6 2.6H3v2h9.7l-2.6 2.6zM19 3H5c-1.1 0-2 .9-2 2v4h2V5h14v14H5v-4H3v4c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2z"/>',
};
export function icon(name, cls) {
  const el = s('svg', { viewBox: '0 0 24 24', fill: 'currentColor', 'aria-hidden': 'true', class: cls || null });
  el.innerHTML = ICONS[name] || '';
  return el;
}

// ---------------------------------------------------------------- API
export class ApiError extends Error {
  constructor(status, message, field) { super(message); this.status = status; this.field = field; }
}

async function request(method, path, body) {
  const opts = { method, headers: { 'X-Requested-With': 'garment-shop' }, credentials: 'same-origin' };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(path, opts);
  } catch (e) {
    throw new ApiError(0, 'Cannot reach the shop server. Check that it is running.');
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    if (res.status === 401 && path !== '/api/login' && state.user) {
      state.user = null;
      location.hash = '#/login';
    }
    throw new ApiError(res.status, data.error || 'Request failed', data.field);
  }
  return data;
}

export function qs(params) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params || {})) if (v !== undefined && v !== null && v !== '') p.set(k, v);
  const str = p.toString();
  return str ? '?' + str : '';
}

export const api = {
  get: (path, params) => request('GET', path + qs(params)),
  post: (path, body) => request('POST', path, body || {}),
  put: (path, body) => request('PUT', path, body || {}),
  download(path, params) {
    const a = h('a', { href: path + qs(params), download: '' });
    document.body.append(a);
    a.click();
    a.remove();
  },
};

export function can(perm) {
  const u = state.user;
  if (!u) return false;
  if (u.role === 'owner') return true;
  if (perm === 'owner') return false;
  return u.permissions.includes(perm);
}
export const isOwner = () => state.user && state.user.role === 'owner';

// ---------------------------------------------------------------- formatting
const inrFmt = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', minimumFractionDigits: 2, maximumFractionDigits: 2 });
const inr0Fmt = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 });
const numFmt = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 3 });
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export const fmt = {
  inr: (n) => (n === null || n === undefined || n === '') ? '—' : inrFmt.format(Number(n) + 0),
  inr0: (n) => (n === null || n === undefined) ? '—' : inr0Fmt.format(Math.round(Number(n)) + 0),
  num: (n) => (n === null || n === undefined || n === '') ? '—' : numFmt.format(Number(n) + 0),
  pct: (n) => (n === null || n === undefined) ? '—' : `${Number(n).toFixed(1)}%`,
  date: (iso) => {
    if (!iso) return '—';
    const d = String(iso).slice(0, 10).split('-');
    return d.length === 3 ? `${d[2]}-${d[1]}-${d[0]}` : iso;
  },
  datetime: (iso) => {
    if (!iso) return '—';
    const [d, t] = String(iso).split(' ');
    return `${fmt.date(d)} ${t ? t.slice(0, 5) : ''}`;
  },
  month: (key) => {
    if (!key || key.length < 7) return key;
    const [y, m] = key.split('-');
    if (key.length === 10) return `${key.slice(8, 10)} ${MONTHS[+m - 1]}`;
    return `${MONTHS[+m - 1]} ${y}`;
  },
  // compact Indian notation for chart axes: ₹1.2K, ₹3.4L, ₹1.1Cr
  compact: (n) => {
    const a = Math.abs(n), sign = n < 0 ? '-' : '';
    if (a >= 1e7) return `${sign}₹${trim(a / 1e7)}Cr`;
    if (a >= 1e5) return `${sign}₹${trim(a / 1e5)}L`;
    if (a >= 1e3) return `${sign}₹${trim(a / 1e3)}K`;
    return `${sign}₹${Math.round(a)}`;
  },
  compactNum: (n) => {
    const a = Math.abs(n);
    if (a >= 1e5) return `${trim(n / 1e5)}L`;
    if (a >= 1e3) return `${trim(n / 1e3)}K`;
    return String(Math.round(n));
  },
  channel: (c) => h('span', { class: `badge ${c}` }, c === 'wholesale' ? 'Wholesale' : 'Retail'),
  status: (st) => st === 'void' ? h('span', { class: 'badge bad' }, 'Void') : null,
};
function trim(x) { return x >= 100 ? Math.round(x).toString() : x.toFixed(1).replace(/\.0$/, ''); }

export const round2 = (x) => Math.round((Number(x) + Number.EPSILON) * 100) / 100;

// ---------------------------------------------------------------- dates
export function addDays(iso, n) {
  const d = new Date(iso + 'T00:00:00');
  d.setDate(d.getDate() + n);
  return isoDate(d);
}
export function isoDate(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}
export function datePresets() {
  const t = state.today;
  const [y, m] = t.split('-').map(Number);
  const monthStart = t.slice(0, 8) + '01';
  const lastMonthEnd = addDays(monthStart, -1);
  const lastMonthStart = lastMonthEnd.slice(0, 8) + '01';
  const fyYear = m >= 4 ? y : y - 1;
  return [
    { key: 'today', label: 'Today', from: t, to: t },
    { key: '7d', label: '7 days', from: addDays(t, -6), to: t },
    { key: 'month', label: 'This month', from: monthStart, to: t },
    { key: 'lastmonth', label: 'Last month', from: lastMonthStart, to: lastMonthEnd },
    { key: 'fy', label: `FY ${fyYear}-${String(fyYear + 1).slice(2)}`, from: `${fyYear}-04-01`, to: t },
    { key: 'all', label: 'All time', from: '', to: '' },
  ];
}

// ---------------------------------------------------------------- feedback
export function toast(msg, kind) {
  const el = h('div', { class: `toast ${kind || ''}`, role: 'status' }, msg);
  document.getElementById('toasts').append(el);
  setTimeout(() => el.remove(), kind === 'bad' ? 6000 : 3200);
}

export function modal({ title, body, actions, wide, onClose }) {
  const close = () => { overlay.remove(); document.removeEventListener('keydown', esc); onClose && onClose(); };
  const esc = (e) => { if (e.key === 'Escape') close(); };
  const foot = h('div', { class: 'modal-foot' });
  const overlay = h('div', { class: 'overlay', onmousedown: (e) => { if (e.target === overlay) close(); } },
    h('div', { class: `modal ${wide ? 'wide' : ''}`, role: 'dialog', 'aria-modal': 'true', 'aria-label': title },
      h('div', { class: 'modal-head' }, h('h2', null, title), h('span', { class: 'spacer' }),
        h('button', { class: 'icon-btn', 'aria-label': 'Close', onclick: close }, icon('close'))),
      h('div', { class: 'modal-body' }, body),
      foot));
  const ctl = { close, foot, overlay };
  for (const a of actions || []) foot.append(a(ctl));
  document.body.append(overlay);
  document.addEventListener('keydown', esc);
  const first = overlay.querySelector('input:not([type=hidden]), select, textarea');
  if (first) setTimeout(() => first.focus(), 30);
  return ctl;
}

export function confirmVoid(table, id, what, onDone) {
  const reason = h('textarea', { placeholder: 'Why is this being voided? (required)', 'data-field': 'reason' });
  const err = h('div', { class: 'field-error' });
  modal({
    title: `Void ${what}`,
    body: h('div', { class: 'stack' },
      h('p', { class: 'small' }, 'Voiding keeps the record for audit but removes its effect on stock, balances and profit. This cannot be undone.'),
      h('label', { class: 'field' }, h('span', { class: 'lbl' }, 'Reason'), reason), err),
    actions: [
      (m) => h('button', { class: 'btn', onclick: m.close }, 'Cancel'),
      (m) => h('button', {
        class: 'btn primary', onclick: async (e) => {
          e.target.disabled = true;
          try {
            await api.post(`/api/void/${table}/${id}`, { reason: reason.value });
            m.close();
            toast(`${what} voided`);
            onDone && onDone();
          } catch (ex) {
            err.textContent = ex.message;
            e.target.disabled = false;
          }
        },
      }, 'Void'),
    ],
  });
}

// ---------------------------------------------------------------- forms
export function field(label, input, opts = {}) {
  return h('label', { class: `field ${opts.class || ''}` },
    h('span', { class: 'lbl' }, label, opts.required ? h('span', { class: 'req' }, ' *') : null),
    input,
    opts.hint ? h('span', { class: 'hint' }, opts.hint) : null);
}

export function input(name, attrs = {}) {
  return h('input', Object.assign({ name, 'data-field': name, type: 'text' }, attrs));
}
export function numInput(name, attrs = {}) {
  return h('input', Object.assign({ name, 'data-field': name, type: 'number', inputmode: 'decimal', step: 'any', min: '0' }, attrs));
}
export function dateInput(name, value) {
  return h('input', { name, 'data-field': name, type: 'date', value: value || state.today, max: state.today });
}
export function select(name, options, value, attrs = {}) {
  const el = h('select', Object.assign({ name, 'data-field': name }, attrs),
    options.map((o) => h('option', { value: o.value }, o.label)));
  if (value !== undefined && value !== null) el.value = String(value);
  return el;
}
export const PAYMENT_METHODS = ['Cash', 'UPI', 'Card', 'Bank Transfer', 'Cheque'];
export const methodSelect = (name, value) => select(name, PAYMENT_METHODS.map((m) => ({ value: m, label: m })), value || 'Cash');

export function clearErrors(root) {
  root.querySelectorAll('.invalid').forEach((el) => el.classList.remove('invalid'));
  root.querySelectorAll('.field-error.auto').forEach((el) => el.remove());
}

export function showError(root, err) {
  clearErrors(root);
  let target = null;
  if (err.field) target = root.querySelector(`[data-field="${CSS.escape(err.field)}"]`);
  if (target) {
    target.classList.add('invalid');
    const msg = h('div', { class: 'field-error auto' }, err.message);
    (target.closest('label.field, td, .channel-pick') || target).append(msg);
    if (target.focus) target.focus();
    target.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }
  toast(err.message, 'bad');
}

export function clientRef() {
  return (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random()).slice(0, 60);
}

// Prevent double-submits: disables the button while the promise runs.
export async function busy(btn, fn) {
  if (btn.disabled) return;
  btn.disabled = true;
  const label = btn.textContent;
  btn.textContent = 'Saving…';
  try { return await fn(); } finally { btn.disabled = false; btn.textContent = label; }
}

// ---------------------------------------------------------------- combobox
// source(q) -> Promise<[{value, label, sub, data}]>; onPick(item)
export function combobox({ name, placeholder, source, onPick, value, label, action }) {
  const inp = h('input', { type: 'text', placeholder: placeholder || 'Search…', autocomplete: 'off', 'data-field': name, role: 'combobox', 'aria-expanded': 'false' });
  if (label) inp.value = label;
  const list = h('div', { class: 'combo-list hidden', role: 'listbox' });
  const root = h('div', { class: 'combo' }, inp, list);
  let items = [], active = -1, timer = null, seq = 0;
  root.value = value || null;

  const render = () => {
    list.replaceChildren();
    if (!items.length) list.append(h('div', { class: 'combo-empty' }, 'No matches'));
    items.forEach((it, i) => list.append(h('div', {
      class: `combo-item ${i === active ? 'active' : ''}`, role: 'option',
      onmousedown: (e) => { e.preventDefault(); pick(it); },
    }, h('span', null, it.label), it.sub ? h('span', { class: 'sub' }, it.sub) : null)));
    if (action) list.append(h('div', {
      class: 'combo-item action', onmousedown: (e) => { e.preventDefault(); hide(); action.run(inp.value, pick); },
    }, '+ ', action.label));
  };
  // The list is fixed-positioned so scrolling tables / cards never clip it.
  const place = () => {
    const r = inp.getBoundingClientRect();
    const below = window.innerHeight - r.bottom;
    list.style.left = `${Math.max(8, Math.min(r.left, window.innerWidth - Math.max(r.width, 260) - 8))}px`;
    list.style.width = `${Math.max(r.width, 260)}px`;
    if (below < 220 && r.top > below) { list.style.top = ''; list.style.bottom = `${window.innerHeight - r.top + 4}px`; }
    else { list.style.bottom = ''; list.style.top = `${r.bottom + 4}px`; }
  };
  const onScroll = (e) => { if (!list.contains(e.target)) place(); };
  const show = () => {
    place(); list.classList.remove('hidden'); inp.setAttribute('aria-expanded', 'true');
    window.addEventListener('scroll', onScroll, true); window.addEventListener('resize', place);
  };
  const hide = () => {
    list.classList.add('hidden'); inp.setAttribute('aria-expanded', 'false');
    window.removeEventListener('scroll', onScroll, true); window.removeEventListener('resize', place);
  };
  const load = async () => {
    const my = ++seq;
    const res = await source(inp.value.trim());
    if (my !== seq) return;
    items = res; active = items.length ? 0 : -1;
    render(); show();
  };
  const pick = (it) => {
    root.value = it.value;
    inp.value = it.label;
    inp.classList.remove('invalid');
    hide();
    onPick && onPick(it);
  };
  root.pick = pick;
  root.clear = () => { root.value = null; inp.value = ''; };
  root.focus = () => inp.focus();
  inp.addEventListener('input', () => { root.value = null; clearTimeout(timer); timer = setTimeout(load, 140); });
  inp.addEventListener('focus', () => { inp.select(); load(); });
  inp.addEventListener('blur', () => setTimeout(hide, 120));
  inp.addEventListener('keydown', (e) => {
    if (list.classList.contains('hidden')) return;
    if (e.key === 'ArrowDown') { active = Math.min(items.length - 1, active + 1); render(); e.preventDefault(); }
    else if (e.key === 'ArrowUp') { active = Math.max(0, active - 1); render(); e.preventDefault(); }
    else if (e.key === 'Enter') { if (items[active]) { pick(items[active]); e.preventDefault(); } }
    else if (e.key === 'Escape') hide();
  });
  return root;
}

// ---------------------------------------------------------------- tables
// columns: [{label, key|render(row), num, cls}]
export function table(columns, rows, opts = {}) {
  if (!rows.length) return h('div', { class: 'empty' }, opts.empty || 'Nothing recorded yet.', opts.emptyAction || null);
  const thead = h('thead', null, h('tr', null, columns.map((c) => h('th', { class: c.num ? 'num' : '' }, c.label))));
  const tbody = h('tbody', null, rows.map((r) => h('tr', {
    class: `${opts.onRow ? 'click' : ''} ${r.status === 'void' ? 'void' : ''}`,
    onclick: opts.onRow ? () => opts.onRow(r) : null,
  }, columns.map((c) => {
    const v = c.render ? c.render(r) : r[c.key];
    return h('td', { class: `${c.num ? 'num' : ''} ${c.cls || ''}` }, v === null || v === undefined ? '' : v);
  }))));
  const t = h('table', null, thead, tbody);
  if (opts.totals) t.append(h('tfoot', null, h('tr', null, columns.map((c, i) => h('td', { class: c.num ? 'num' : '' },
    opts.totals[c.key] !== undefined ? opts.totals[c.key] : (i === 0 ? 'Total' : ''))))));
  return h('div', { class: 'table-wrap' }, t);
}

export function pageHead(title, sub, actions) {
  return h('div', { class: 'page-head' },
    h('div', null, h('h1', null, title), sub ? h('div', { class: 'sub' }, sub) : null),
    actions && actions.length ? h('div', { class: 'actions' }, actions) : null);
}

export function linkBtn(href, label, cls = '', ic) {
  return h('a', { class: `btn ${cls}`, href }, ic ? icon(ic) : null, label);
}

export function card(title, body, opts = {}) {
  return h('div', { class: `card ${opts.class || ''}` },
    title ? h('div', { class: 'card-head' }, h('h2', null, title), opts.sub ? h('span', { class: 'sub' }, opts.sub) : null,
      h('span', { class: 'spacer' }), opts.actions || null) : null,
    h('div', { class: 'card-body' }, body));
}

export function dl(pairs) {
  return h('dl', { class: 'dl' }, pairs.filter(Boolean).map(([k, v]) => [h('dt', null, k), h('dd', null, v)]));
}

export function variantSource(params = {}) {
  return async (q) => {
    const list = await api.get('/api/variants', Object.assign({ q, limit: 40 }, params));
    return list.map((v) => ({
      value: v.id, label: v.label, data: v,
      sub: `${v.sku} · ${fmt.num(v.stock_qty)} ${v.unit} in stock`,
    }));
  };
}

// Filter state lives in the URL hash query so views are linkable / click-through.
export function hashQuery() {
  const i = location.hash.indexOf('?');
  return Object.fromEntries(new URLSearchParams(i >= 0 ? location.hash.slice(i + 1) : ''));
}
export function setHashQuery(params, replace = true) {
  const base = location.hash.split('?')[0] || '#/';
  const url = base + qs(params);
  if (replace) history.replaceState(null, '', url); else location.hash = url;
}

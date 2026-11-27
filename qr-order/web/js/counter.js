/* Counter screen: staff ring up takeaway (and table) orders and record how the customer paid. */
(function () {
  'use strict';
  var Q = window.QRO, h = Q.h, $ = Q.$, api = Q.api, session = Q.session;
  var slug = new URLSearchParams(location.search).get('outlet');
  var outlet, brand, menu = [], byId = {}, token = null;
  var bills = { unpaid: [], refunds: [], low_stock: [] }, showBills = false, timer = null;
  var cart = {}, kind = 'takeaway', pay = null, table = 1, name = '', key = null, busy = false, error = '', last = null;

  function money(n) { return (outlet.currency === 'INR' ? 'Rs. ' : outlet.currency + ' ') + n; }
  function makeKey() { var b = new Uint8Array(16); window.crypto.getRandomValues(b); return Array.prototype.map.call(b, function (x) { return x.toString(16).padStart(2, '0'); }).join(''); }
  function count() { return Object.keys(cart).reduce(function (s, k) { return s + cart[k]; }, 0); }
  function total() { return Object.keys(cart).reduce(function (s, k) { return s + cart[k] * byId[k].price; }, 0); }

  async function boot() {
    if (!slug) { $('app').textContent = 'Open the counter from the staff home page.'; return; }
    try { var r = await api('/api/outlet/' + slug); outlet = r.outlet; brand = r.brand; } catch (e) { $('app').textContent = 'Outlet not found.'; return; }
    document.title = 'Counter - ' + outlet.name;
    if (!outlet.takeaway) kind = 'dine_in';
    token = session.read('qro_tok_kitchen_' + slug);
    if (token) start(); else loginView();
  }

  function loginView(msg) {
    clearInterval(timer); timer = null;
    var app = $('app');
    app.textContent = '';
    var pin = h('input', { type: 'password', inputmode: 'numeric', autocomplete: 'off', 'aria-label': 'Staff PIN', maxlength: '12' });
    var err = h('p', { class: 'err', role: 'alert', text: msg || '' });
    var go = async function () {
      try {
        var r = await api('/api/login', { method: 'POST', body: { scope: 'kitchen', slug: slug, pin: pin.value } });
        token = r.token; session.write('qro_tok_kitchen_' + slug, r.token); session.write('qro_key_kitchen_' + slug, r.stream_key); start();
      } catch (e) { err.textContent = e.message; pin.value = ''; pin.focus(); }
    };
    pin.addEventListener('keydown', function (e) { if (e.key === 'Enter') go(); });
    var btn = h('button', { class: 'btn big', type: 'button', style: 'width:100%', text: 'Open counter' });
    btn.addEventListener('click', go);
    app.appendChild(h('div', { class: 'login' }, [h('h1', { text: 'Counter' }), h('p', { text: outlet.name }), err, pin, btn]));
    pin.focus();
  }

  async function start() {
    var d = await api('/api/menu/' + slug);
    menu = d.categories; byId = {};
    menu.forEach(function (c) { c.items.forEach(function (i) { byId[i.id] = i; }); });
    Object.keys(cart).forEach(function (k) { if (!byId[k] || !byId[k].available) delete cart[k]; });
    render();
    clearInterval(timer);
    timer = setInterval(loadBills, 10000);
    loadBills();
  }

  function signedOut() { session.drop('qro_tok_kitchen_' + slug); session.drop('qro_key_kitchen_' + slug); token = null; loginView('Please sign in again'); }

  /* ---- bills: who still has to pay, and money to give back */
  async function loadBills() {
    try { bills = await api('/api/kitchen/' + slug + '/bills', { token: token }); drawBills(); }
    catch (e) { if (e.status === 401 || e.status === 403) signedOut(); }
  }
  async function billAction(path, body, question) {
    if (!confirm(question)) return;
    try { await api('/api/kitchen/' + slug + '/orders/' + path, { method: 'POST', token: token, body: body }); }
    catch (e) { if (e.status === 401 || e.status === 403) { signedOut(); return; } alert(e.message); }
    loadBills();
  }
  function whose(b) { return 'Token ' + String(b.token).padStart(3, '0') + ' · ' + (b.kind === 'takeaway' ? 'takeaway ' + b.name : 'table ' + b.table + (b.name ? ' · ' + b.name : '')); }
  function drawBills() {
    var tab = $('billbtn'), box = $('bills'), low = $('lowline');
    if (!tab || !box) return;
    tab.textContent = 'Bills (' + (bills.unpaid.length + bills.refunds.length) + ')';
    tab.setAttribute('aria-pressed', String(showBills));
    low.textContent = bills.low_stock.length ? 'Low stock: ' + bills.low_stock.map(function (s) { return s.name + (s.status === 'OUT' ? ' (none left)' : ''); }).join(', ') : '';
    low.hidden = !bills.low_stock.length;
    box.hidden = !showBills;
    box.textContent = '';
    if (!showBills) return;
    var row = function (b, extra) { return h('div', { class: 'billrow' }, [h('span', { text: whose(b) }), h('b', { text: money(b.total) })].concat(extra)); };
    var act = function (label, fn) { var x = h('button', { class: 'btn ghost', type: 'button', text: label }); x.addEventListener('click', fn); return x; };
    if (bills.refunds.length) {
      box.appendChild(h('h3', { class: 'err', text: 'Give this money back (order rejected after payment)' }));
      bills.refunds.forEach(function (b) {
        box.appendChild(row(b, [act('Money returned', function () { billAction(b.public_id + '/refunded', {}, 'Have you given ' + money(b.total) + ' back for ' + whose(b) + '?'); })]));
      });
    }
    box.appendChild(h('h3', { text: 'Unpaid bills' }));
    if (!bills.unpaid.length) box.appendChild(h('p', { class: 'hint', text: 'Nothing waiting for payment.' }));
    bills.unpaid.forEach(function (b) {
      box.appendChild(row(b, [['Cash', 'cash'], ['UPI', 'upi'], ['Card', 'card']].map(function (m) {
        return act(m[0], function () { billAction(b.public_id + '/pay', { method: m[1] }, 'Received ' + money(b.total) + ' by ' + m[0] + ' for ' + whose(b) + '?'); });
      })));
    });
  }

  function change(id, d) {
    var q = Math.max(0, Math.min(20, (cart[id] || 0) + d));
    if (q) cart[id] = q; else delete cart[id];
    key = null; last = null; render();
  }

  function choice(label, value, current, set) {
    var b = h('button', { class: 'tog', type: 'button', 'aria-pressed': String(value === current), text: label });
    b.addEventListener('click', function () { set(value); key = null; render(); });
    return b;
  }

  async function place() {
    if (busy) return;
    busy = true; error = ''; render();
    if (!key) key = makeKey();
    var body = { outlet: slug, kind: kind, name: name.trim(), client_key: key, lines: Object.keys(cart).map(function (id) { return { item_id: Number(id), qty: cart[id] }; }) };
    if (kind === 'dine_in') body.table = table;
    if (pay && pay !== 'later') body.pay_method = pay;
    try {
      var r = await api('/api/orders', { method: 'POST', token: token, body: body });
      last = { token: r.token, total: r.total, pay: pay, kind: kind, name: name };
      cart = {}; name = ''; pay = null; key = null; busy = false;
      $('live').textContent = 'Order placed, token ' + r.token;
      render();
      loadBills();
    } catch (e) {
      busy = false;
      if (e.status === 401 || e.status === 403) { signedOut(); return; }
      error = e.status ? e.message : 'Could not reach the server. Press again: it will not charge or order twice.';
      render();
    }
  }

  function render() {
    var app = $('app');
    app.textContent = '';
    var out = h('button', { class: 'btn ghost', type: 'button', text: 'Sign out' });
    out.addEventListener('click', async function () {
      try { await api('/api/logout', { method: 'POST', token: token, body: {} }); } catch (e) { /* already signed out */ }
      session.drop('qro_tok_kitchen_' + slug); session.drop('qro_key_kitchen_' + slug); token = null; loginView('Signed out');
    });
    var billBtn = h('button', { class: 'tog', type: 'button', id: 'billbtn', 'aria-pressed': 'false', text: 'Bills' });
    billBtn.addEventListener('click', function () { showBills = !showBills; drawBills(); if (showBills) loadBills(); });
    app.appendChild(h('div', { class: 'bar' }, [h('h1', { text: 'Counter · ' + outlet.name }), h('span', { class: 'grow' }), billBtn,
      h('a', { class: 'btn ghost', href: '/kitchen.html?outlet=' + slug, text: 'Kitchen screen' }), out]));

    var left = h('section', { 'aria-label': 'Menu' });
    if (!menu.some(function (c) { return c.items.length; })) left.appendChild(h('p', { class: 'hint', text: 'The menu is empty. The owner adds dishes in the owner panel.' }));
    menu.forEach(function (c) {
      if (!c.items.length) return;
      left.appendChild(h('h3', { text: c.names.en || c.slug }));
      var grid = h('div', { class: 'pick' });
      c.items.forEach(function (i) {
        var b = h('button', { class: 'pickb' + (cart[i.id] ? ' on' : ''), type: 'button' }, [h('b', { text: i.names.en || '' }), h('span', { text: i.available ? money(i.price) : 'Out of stock' }),
          cart[i.id] ? h('em', { text: 'x ' + cart[i.id] }) : null]);
        if (!i.available) b.disabled = true;
        b.addEventListener('click', function () { change(i.id, 1); });
        grid.appendChild(b);
      });
      left.appendChild(grid);
    });

    var right = h('aside', { class: 'till', 'aria-label': 'Current sale' });
    if (last) right.appendChild(h('div', { class: 'done', role: 'status' }, [h('div', { text: 'ORDER PLACED - TOKEN' }), h('strong', { text: String(last.token).padStart(3, '0') }),
      h('div', { text: money(last.total) + (last.pay && last.pay !== 'later' ? ' · paid ' + last.pay.toUpperCase() : ' · to be paid') })]));
    if (outlet.takeaway) right.appendChild(h('div', { class: 'inline' }, [choice('Takeaway', 'takeaway', kind, function (v) { kind = v; if (pay === 'later') pay = null; }),
      choice('Table order', 'dine_in', kind, function (v) { kind = v; })]));
    Object.keys(cart).forEach(function (id) {
      var minus = h('button', { class: 'btn ghost', type: 'button', 'aria-label': 'One less ' + byId[id].names.en, text: '-' });
      minus.addEventListener('click', function () { change(id, -1); });
      right.appendChild(h('div', { class: 'line' }, [minus, h('span', { text: cart[id] + ' x ' + byId[id].names.en }), h('b', { text: money(cart[id] * byId[id].price) })]));
    });
    right.appendChild(h('div', { class: 'sum' }, [h('span', { text: 'Total' }), h('b', { text: money(total()) })]));
    if (kind === 'dine_in') {
      var sel = h('select', { id: 'ctable' });
      for (var n = 1; n <= outlet.tables; n++) sel.appendChild(h('option', { value: String(n), text: 'Table ' + n }));
      sel.value = String(table);
      sel.addEventListener('change', function () { table = Number(sel.value); key = null; });
      right.appendChild(h('label', { class: 'f', for: 'ctable', text: 'Table' })); right.appendChild(sel);
    }
    var who = h('input', { type: 'text', id: 'cname', maxlength: '30' });
    who.value = name;
    right.appendChild(h('label', { class: 'f', for: 'cname', text: kind === 'takeaway' ? 'Customer name (to call out)' : 'Name (optional)' })); right.appendChild(who);
    right.appendChild(h('label', { class: 'f', text: 'Payment' }));
    var methods = [['Cash', 'cash'], ['UPI', 'upi'], ['Card', 'card']].concat(kind === 'dine_in' ? [['Pay later', 'later']] : []);
    right.appendChild(h('div', { class: 'inline' }, methods.map(function (m) { return choice(m[0], m[1], pay, function (v) { pay = v; }); })));
    if (error) right.appendChild(h('p', { class: 'err', role: 'alert', text: error }));
    var go = h('button', { class: 'btn big', type: 'button', style: 'width:100%;margin-top:12px' });
    var paint = function () {
      var why = !count() ? 'Add items' : !pay ? 'Choose the payment' : (kind === 'takeaway' && !name.trim()) ? 'Enter the customer name' : '';
      go.textContent = why || 'Place order · ' + money(total());
      go.disabled = !!why || busy;
    };
    who.addEventListener('input', function () { name = who.value; key = null; paint(); });
    go.addEventListener('click', place);
    paint();
    right.appendChild(go);
    right.appendChild(h('p', { class: 'hint', text: 'This records how the customer paid. It does not take the money: use your cash drawer, UPI or card machine.' }));
    app.appendChild(h('div', { id: 'lowline', class: 'pline bad', hidden: true }));
    app.appendChild(h('section', { id: 'bills', class: 'pbox', hidden: true, 'aria-label': 'Bills' }));
    app.appendChild(h('div', { class: 'pos' }, [left, right]));
    drawBills();
  }

  boot();
})();

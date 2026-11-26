/*
 * CUTTING CHAI CO. - table ordering.
 * Cart and order live in this browser's localStorage. There is no server and
 * no payment: the "kitchen" is simulated by a timer (see CAFE.stageSeconds in
 * menu.js). To make it real, send `order` to your kitchen printer or POS in
 * placeOrder() and drive the tracker from the kitchen's status instead.
 */
(function () {
  'use strict';

  var CAFE = window.CAFE;
  var MENU = window.MENU;
  var rs = window.rs;
  var KEYS = { cart: 'cc_cart_v1', order: 'cc_order_v1', seq: 'cc_seq_v1' };
  var STALE_MS = 6 * 60 * 60 * 1000;
  var STAGES = [
    { label: 'Order Received', sub: 'Your token is punched' },
    { label: 'Kettle On', sub: 'Brewing and plating' },
    { label: 'Pouring', sub: 'Final touches' },
    { label: 'At Your Table', sub: 'Aaiye, chai pijiye!' }
  ];
  var STRENGTH = ['Halka', 'Normal', 'Kadak'];
  var SUGAR = ['Kam', 'Normal', 'Zyada'];

  /* ---------- helpers ---------- */
  var byId = {};
  MENU.categories.forEach(function (c) {
    c.items.forEach(function (i) { i.cat = c.id; byId[i.id] = i; });
  });

  function read(key, fallback) {
    try { var v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; } catch (e) { return fallback; }
  }
  function write(key, val) { try { localStorage.setItem(key, JSON.stringify(val)); } catch (e) { /* private mode: keep going in memory */ } }
  function drop(key) { try { localStorage.removeItem(key); } catch (e) { /* ignore */ } }
  function $(id) { return document.getElementById(id); }
  function h(tag, attrs, kids) {
    var e = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'text') e.textContent = attrs[k];
      else if (k === 'class') e.className = attrs[k];
      else e.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (c) { if (c) e.appendChild(c); });
    return e;
  }
  function announce(msg) { $('live').textContent = msg; }
  function pad(n) { return ('0000' + n).slice(-4); }

  /* ---------- state ---------- */
  var state = read(KEYS.cart, null) || {};
  state.items = state.items || {};
  Object.keys(state.items).forEach(function (id) { if (!byId[id] || !(state.items[id] > 0)) delete state.items[id]; });
  state.table = state.table || null;
  state.name = state.name || '';
  state.strength = state.strength || 'Kadak';
  state.sugar = state.sugar || 'Normal';
  var order = read(KEYS.order, null);
  var activeTab = 'all';
  var timer = null;
  var lastStage = -1;

  function save() { write(KEYS.cart, state); }
  function lines() {
    return Object.keys(state.items).map(function (id) { return { item: byId[id], qty: state.items[id] }; });
  }
  function count() { return lines().reduce(function (s, l) { return s + l.qty; }, 0); }
  function total() { return lines().reduce(function (s, l) { return s + l.qty * l.item.price; }, 0); }
  function hasChai() { return lines().some(function (l) { return l.item.cat === 'chai'; }); }

  function setQty(id, delta) {
    var q = Math.max(0, Math.min(20, (state.items[id] || 0) + delta));
    if (q === 0) delete state.items[id]; else state.items[id] = q;
    save();
    refreshDish(id);
    renderCart();
    refreshBar();
    announce(byId[id].name + (delta > 0 ? ' added. ' : ' removed. ') + count() + ' items, ' + rs(total()));
  }

  /* ---------- menu list ---------- */
  function buildTabs() {
    var box = $('tabs');
    var tabs = [{ id: 'all', title: 'Everything' }].concat(MENU.categories.map(function (c) { return { id: c.id, title: c.title }; }));
    tabs.forEach(function (t) {
      box.appendChild(h('button', { class: 'tab', type: 'button', 'data-act': 'tab', 'data-v': t.id, 'aria-pressed': String(t.id === activeTab), text: t.title }));
    });
  }
  function buildDishes() {
    var box = $('dishes');
    MENU.categories.forEach(function (c) {
      c.items.forEach(function (it) {
        var title = h('h3', { text: it.name });
        if (it.tag) title.appendChild(h('span', { class: 'tag', text: it.tag }));
        var card = h('article', { class: 'dish', 'data-id': it.id, 'data-cat': c.id }, [
          title,
          it.desc ? h('p', { class: 'desc', text: it.desc }) : null,
          h('div', { class: 'row' }, [h('span', { class: 'price', text: rs(it.price) }), h('span', { class: 'ctl' })])
        ]);
        box.appendChild(card);
        refreshDish(it.id);
      });
    });
  }
  function stepper(id, qty, name) {
    return h('span', { class: 'stepper' }, [
      h('button', { type: 'button', 'data-act': 'dec', 'data-id': id, 'aria-label': 'Remove one ' + name, text: '-' }),
      h('output', { 'aria-label': name + ' quantity', text: String(qty) }),
      h('button', { type: 'button', 'data-act': 'inc', 'data-id': id, 'aria-label': 'Add one ' + name, text: '+' })
    ]);
  }
  function refreshDish(id) {
    var card = document.querySelector('.dish[data-id="' + id + '"]');
    if (!card) return;
    var ctl = card.querySelector('.ctl');
    var q = state.items[id] || 0;
    ctl.textContent = '';
    if (q === 0) {
      ctl.appendChild(h('button', { class: 'add', type: 'button', 'data-act': 'inc', 'data-id': id, 'aria-label': 'Add ' + byId[id].name, text: 'Add' }));
      card.classList.remove('in');
    } else {
      ctl.appendChild(stepper(id, q, byId[id].name));
      card.classList.add('in');
    }
  }
  function applyTab() {
    Array.prototype.forEach.call(document.querySelectorAll('.dish'), function (d) {
      d.hidden = !(activeTab === 'all' || d.getAttribute('data-cat') === activeTab);
    });
    Array.prototype.forEach.call(document.querySelectorAll('.tab'), function (b) {
      b.setAttribute('aria-pressed', String(b.getAttribute('data-v') === activeTab));
    });
  }

  /* ---------- the ticket (cart) ---------- */
  function seg(name, options, current) {
    var g = h('div', { class: 'seg' });
    options.forEach(function (o) {
      g.appendChild(h('button', { type: 'button', 'data-act': name, 'data-v': o, 'aria-pressed': String(o === current), text: o }));
    });
    return g;
  }
  function renderCart() {
    var ls = lines();
    var n = count();
    var inn = h('div', { class: 'slip-in' });
    inn.appendChild(h('h2', { id: 'cart-h', text: 'Your Ticket' }));
    inn.appendChild(h('p', { class: 'sub', text: n ? n + (n === 1 ? ' item' : ' items') : 'Empty - tap Add on a dish' }));

    if (n) {
      var ul = h('ul', { class: 'lines' });
      ls.forEach(function (l) {
        ul.appendChild(h('li', {}, [
          h('span', { class: 'nm', text: l.item.name }),
          h('span', { class: 'lp', text: rs(l.item.price * l.qty) }),
          stepper(l.item.id, l.qty, l.item.name)
        ]));
      });
      inn.appendChild(ul);
      inn.appendChild(h('div', { class: 'total' }, [h('span', { text: 'Total' }), h('span', { text: rs(total()) })]));
    } else {
      inn.appendChild(h('p', { class: 'empty', text: 'Nothing on the ticket yet. Start with a Cutting Chai?' }));
    }

    var tf = h('fieldset', {}, [h('legend', { text: 'Your table no.' })]);
    var grid = h('div', { class: 'tables' });
    for (var t = 1; t <= CAFE.tables; t++) {
      grid.appendChild(h('button', { type: 'button', 'data-act': 'table', 'data-v': String(t), 'aria-pressed': String(state.table === t), 'aria-label': 'Table ' + t, text: String(t) }));
    }
    tf.appendChild(grid);
    inn.appendChild(tf);

    if (hasChai()) {
      inn.appendChild(h('fieldset', {}, [h('legend', { text: 'Chai ka mizaaz: strength' }), seg('strength', STRENGTH, state.strength)]));
      inn.appendChild(h('fieldset', {}, [h('legend', { text: 'Sugar' }), seg('sugar', SUGAR, state.sugar)]));
    }

    var nf = h('fieldset', {}, [h('legend', { text: 'Name (optional)' })]);
    var input = h('input', { type: 'text', id: 'who', maxlength: '30', autocomplete: 'given-name', 'aria-label': 'Your name, optional' });
    input.value = state.name;
    input.addEventListener('input', function () { state.name = input.value; save(); });
    nf.appendChild(input);
    inn.appendChild(nf);

    var label = !n ? 'Add something first' : !state.table ? 'Pick your table' : 'Place order - ' + rs(total());
    var place = h('button', { class: 'btn place', type: 'button', 'data-act': 'place', text: label });
    if (!n || !state.table) place.disabled = true;
    inn.appendChild(place);
    inn.appendChild(h('p', { class: 'hint', text: 'No payment needed. Settle at the counter on your way out.' }));

    var slip = h('section', { class: 'slip', 'aria-labelledby': 'cart-h' }, [inn]);
    var box = $('cart');
    box.textContent = '';
    box.appendChild(slip);
  }
  function refreshBar() {
    var n = count();
    var bar = $('bar');
    $('bar-text').textContent = n + (n === 1 ? ' item' : ' items') + ' - ' + rs(total());
    var show = n > 0 && !order;
    bar.classList.toggle('on', show);
    document.body.classList.toggle('has-bar', show);
  }

  /* ---------- placing the order ---------- */
  function placeOrder() {
    var ls = lines();
    if (!ls.length || !state.table) return;
    var seq = read(KEYS.seq, 100) + 1;
    write(KEYS.seq, seq);
    order = {
      token: pad(seq),
      table: state.table,
      name: (state.name || '').trim(),
      chai: hasChai() ? { strength: state.strength, sugar: state.sugar } : null,
      lines: ls.map(function (l) { return { name: l.item.name, qty: l.qty, price: l.item.price }; }),
      total: total(),
      placedAt: Date.now()
    };
    write(KEYS.order, order);
    state.items = {};
    save();
    showTracker();
  }

  /* ---------- tracker: the order drives to the table ---------- */
  function taxiSvg() {
    var ns = 'http://www.w3.org/2000/svg';
    var wrap = h('div', { class: 'taxi', id: 'taxi' });
    wrap.innerHTML = '<svg viewBox="0 0 120 64" role="img" aria-label="Kaali-Peeli taxi carrying your order">' +
      '<polygon points="30,30 42,12 82,12 94,30" fill="#F4C430" stroke="#141414" stroke-width="3"/>' +
      '<polygon points="40,28 48,16 78,16 87,28" fill="#141414"/>' +
      '<rect x="50" y="3" width="22" height="9" fill="#141414"/><rect x="53" y="6" width="16" height="3" fill="#F4C430"/>' +
      '<rect x="6" y="30" width="108" height="12" fill="#F4C430" stroke="#141414" stroke-width="3"/>' +
      '<rect x="6" y="42" width="108" height="12" fill="#141414"/>' +
      '<rect x="108" y="33" width="6" height="6" fill="#FFF3D6"/>' +
      '<circle cx="28" cy="54" r="9" fill="#141414"/><circle cx="28" cy="54" r="3" fill="#FFF3D6"/>' +
      '<circle cx="92" cy="54" r="9" fill="#141414"/><circle cx="92" cy="54" r="3" fill="#FFF3D6"/>' +
      '</svg>';
    return wrap;
  }
  function buildTracker() {
    var box = $('tracker');
    box.textContent = '';
    var who = order.name ? ' - ' + order.name : '';
    box.appendChild(h('span', { class: 'kick', text: 'Token No. ' + order.token + ' - Table ' + order.table + who }));
    box.appendChild(h('h1', { id: 'track-h', text: 'Your order is coming right up to your table!' }));
    box.appendChild(h('p', { class: 'status', id: 'status', 'aria-live': 'polite', text: STAGES[0].label }));
    box.appendChild(h('p', { class: 'eta', id: 'eta', text: '' }));

    var route = h('div', { class: 'route', role: 'img', 'aria-label': 'Order progress: received, kettle on, pouring, at your table' });
    STAGES.forEach(function (s, i) {
      route.appendChild(h('div', { class: 'stop', id: 'stop' + i, style: 'left:' + (i / (STAGES.length - 1) * 100) + '%' }, [
        document.createTextNode(String(i + 1)),
        h('span', { text: s.label })
      ]));
    });
    route.appendChild(taxiSvg());
    box.appendChild(route);

    var inn = h('div', { class: 'slip-in' });
    inn.appendChild(h('h2', { text: 'Order Slip' }));
    inn.appendChild(h('p', { class: 'sub', text: 'Token ' + order.token + ' - Table ' + order.table }));
    var ul = h('ul', { class: 'lines' });
    order.lines.forEach(function (l) {
      ul.appendChild(h('li', {}, [
        h('span', { text: l.qty + ' x' }),
        h('span', { class: 'nm', text: l.name }),
        h('span', { class: 'lp', text: rs(l.price * l.qty) })
      ]));
    });
    inn.appendChild(ul);
    if (order.chai) inn.appendChild(h('p', { class: 'hint', text: 'Chai: ' + order.chai.strength + ' strength, ' + order.chai.sugar + ' sugar' }));
    inn.appendChild(h('div', { class: 'total' }, [h('span', { text: 'Total' }), h('span', { text: rs(order.total) })]));
    inn.appendChild(h('p', { class: 'hint', text: 'Pay at the counter. Keep this token number handy.' }));
    box.appendChild(h('section', { class: 'slip receipt', 'aria-label': 'Order slip' }, [inn]));

    var again = h('button', { class: 'btn again', type: 'button', id: 'again', 'data-act': 'again', text: 'Order something more' });
    again.hidden = true;
    box.appendChild(again);
  }
  function updateTracker() {
    var t = CAFE.stageSeconds;
    var elapsed = (Date.now() - order.placedAt) / 1000;
    var idx = 0;
    t.forEach(function (at, i) { if (elapsed >= at) idx = i; });
    var done = elapsed >= t[t.length - 1];
    var p = 1;
    if (!done) {
      var seg0 = (elapsed - t[idx]) / (t[idx + 1] - t[idx]);
      p = (idx + seg0) / (t.length - 1);
    }
    $('taxi').style.left = (p * 100) + '%';
    STAGES.forEach(function (s, i) {
      var el = $('stop' + i);
      el.className = 'stop' + (i < idx || done ? ' done' : '') + (i === idx && !done ? ' now' : '');
    });
    if (idx !== lastStage) {
      lastStage = idx;
      $('status').textContent = STAGES[idx].label + ' - ' + STAGES[idx].sub;
    }
    if (done) {
      $('eta').textContent = 'Delivered. Enjoy your chai!';
      $('track-h').textContent = 'Your order has reached your table!';
      $('again').hidden = false;
      clearInterval(timer);
      timer = null;
    } else {
      var left = Math.ceil(t[t.length - 1] - elapsed);
      $('eta').textContent = 'Arriving in about ' + (left >= 60 ? Math.ceil(left / 60) + ' min' : left + ' sec');
    }
  }
  function showTracker() {
    $('shop').hidden = true;
    $('tracker').hidden = false;
    $('bar').classList.remove('on');
    document.body.classList.remove('has-bar');
    lastStage = -1;
    buildTracker();
    updateTracker();
    if (timer === null && ((Date.now() - order.placedAt) / 1000) < CAFE.stageSeconds[CAFE.stageSeconds.length - 1]) {
      timer = setInterval(updateTracker, 1000);
    }
    window.scrollTo(0, 0);
  }
  function showShop() {
    $('tracker').hidden = true;
    $('shop').hidden = false;
    renderCart();
    refreshBar();
  }

  /* ---------- events ---------- */
  document.addEventListener('click', function (e) {
    var b = e.target.closest ? e.target.closest('button[data-act]') : null;
    if (!b) return;
    var act = b.getAttribute('data-act');
    var id = b.getAttribute('data-id');
    var v = b.getAttribute('data-v');
    var scope = b.closest('#cart') ? '#cart' : '#dishes';
    if (act === 'inc') { setQty(id, 1); restoreFocus(scope, 'inc', id); }
    else if (act === 'dec') { setQty(id, -1); restoreFocus(scope, 'dec', id); }
    else if (act === 'tab') { activeTab = v; applyTab(); }
    else if (act === 'table') { state.table = Number(v); save(); renderCart(); restoreFocus('#cart', 'table', null, v); }
    else if (act === 'strength' || act === 'sugar') { state[act] = v; save(); renderCart(); restoreFocus('#cart', act, null, v); }
    else if (act === 'place') { placeOrder(); }
    else if (act === 'again') {
      drop(KEYS.order);
      order = null;
      showShop();
      window.scrollTo(0, 0);
    }
  });
  function restoreFocus(scope, act, id, v) {
    var sel = scope + ' [data-act="' + act + '"]' + (id ? '[data-id="' + id + '"]' : '') + (v ? '[data-v="' + v + '"]' : '');
    var el = document.querySelector(sel) || (id ? document.querySelector(scope + ' [data-act="inc"][data-id="' + id + '"]') : null);
    if (el) el.focus();
  }

  /* ---------- start ---------- */
  buildTabs();
  buildDishes();
  applyTab();
  if (order && (Date.now() - order.placedAt) > STALE_MS) { drop(KEYS.order); order = null; }
  if (order) showTracker(); else showShop();
})();

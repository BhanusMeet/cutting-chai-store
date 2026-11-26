/* Guest ordering page. It is opened by scanning the QR code on a table: /r/<outlet>/<table>?k=<table code>.
   Dine-in only: takeaway is ordered and paid at the counter. After ordering, the guest sees a confirmation;
   the phone opens no live connection and checks nothing in the background. */
(function () {
  'use strict';

  var Q = window.QRO, h = Q.h, $ = Q.$, api = Q.api, store = Q.store;
  var I = window.I18N, t = I.t;
  var KEEP_MS = 2 * 3600 * 1000;

  var parts = location.pathname.split('/').filter(Boolean);
  var params = new URLSearchParams(location.search);
  var slug = parts[0] === 'r' ? parts[1] : params.get('outlet');
  var table = parseInt(parts[2], 10) || null;
  var tableKey = params.get('k') || '';
  var tableOk = false;

  var brand, outlet, categories = [], itemById = {}, theme;
  var cart = {}, prefs, nameVal, order = null, activeTab = 'all', placing = false, placeError = '', pendingKey = null;
  var CK, OK;

  function live(msg) { $('live').textContent = msg; }
  // "Cutting Chai Co. - Malad" -> "Malad" (the restaurant name is already the page title)
  function placeName() {
    return outlet.name.indexOf(brand.name) === 0 ? outlet.name.slice(brand.name.length).replace(/^[\s-]+/, '') || outlet.name : outlet.name;
  }
  function money(n) { return I.money(outlet.currency, n); }
  function countItems() { return Object.keys(cart).reduce(function (s, k) { return s + cart[k]; }, 0); }
  function totalPrice() { return Object.keys(cart).reduce(function (s, k) { return s + cart[k] * itemById[k].price; }, 0); }
  function hasChai() { return Object.keys(cart).some(function (k) { return itemById[k].cat === 'chai'; }); }
  function saveCart() { store.write(CK, cart); pendingKey = null; }  // a changed cart is a new order attempt

  var wait = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };
  // Try again on a network error or server hiccup (busy restaurant Wi-Fi, weak signal).
  async function withRetry(call) {
    for (var i = 0; ; i++) {
      try { return await call(); }
      catch (e) { if ((e.status && e.status < 500) || i >= 3) throw e; await wait(700 * (i + 1) + Math.random() * 500); }
    }
  }
  function getRetry(path) { return withRetry(function () { return api(path); }); }
  // Every attempt at one order carries the same key, so a retry or double tap can never order twice.
  function makeKey() {
    var b = new Uint8Array(16);
    window.crypto.getRandomValues(b);
    return Array.prototype.map.call(b, function (x) { return x.toString(16).padStart(2, '0'); }).join('');
  }

  /* ---------------------------------------------------------------- boot */
  function fatal(msg) {
    var app = $('app');
    app.textContent = '';
    app.appendChild(h('p', { style: 'padding:40px 20px;text-align:center;font:18px Georgia,serif', text: msg }));
  }

  function indexMenu() {
    itemById = {};
    categories.forEach(function (c) { c.items.forEach(function (i) { i.cat = c.slug; itemById[i.id] = i; }); });
    Object.keys(cart).forEach(function (id) { if (!itemById[id] || !itemById[id].available) delete cart[id]; });
  }

  function loadTheme() {
    [theme.fonts, theme.css].forEach(function (href) { document.head.appendChild(h('link', { rel: 'stylesheet', href: href })); });
    document.body.setAttribute('data-theme', brand.theme);
  }

  function pickLang() {
    var want = params.get('lang') || store.read('qro_lang', null) || (navigator.language || 'en').slice(0, 2);
    return brand.langs.indexOf(want) >= 0 ? want : brand.default_lang;
  }

  async function boot() {
    if (!slug) return fatal(t('no_link'));
    try {
      var res = await Promise.all([getRetry('/api/outlet/' + slug), getRetry('/api/menu/' + slug)]);
      brand = res[0].brand; outlet = res[0].outlet; categories = res[1].categories;
    } catch (e) { return fatal(e.status === 404 ? t('not_found') : e.message); }
    if (table && tableKey) {
      try { tableOk = (await getRetry('/api/table/' + slug + '/' + table + '?k=' + encodeURIComponent(tableKey))).valid; } catch (e) { tableOk = false; }
    }

    CK = 'qro_cart_' + slug; OK = 'qro_order_' + slug + '_' + (table || 0);
    theme = window.THEMES[brand.theme] || window.THEMES.bombay;
    loadTheme();
    I.setLang(pickLang(), brand.default_lang);
    document.title = outlet.name;
    cart = store.read(CK, {}) || {};
    prefs = store.read('qro_prefs', { strength: 'Kadak', sugar: 'Normal' });
    nameVal = store.read('qro_name', '');
    indexMenu();

    var saved = store.read(OK, null);
    if (saved) {
      try {
        order = await api('/api/orders/' + saved);
        if (order.status === 'served' || order.status === 'cancelled' || Date.now() / 1000 - order.created_at > KEEP_MS / 1000) { store.drop(OK); order = null; }
      } catch (e) { store.drop(OK); order = null; }
    }
    build();
  }

  /* ---------------------------------------------------------------- shell */
  function build() {
    var app = $('app');
    app.textContent = '';
    (theme.top(brand, outlet) || []).forEach(function (n) { app.appendChild(n); });

    var hdr = h('header', { class: 'hdr' }, [
      h('h1', { class: 'brand', text: brand.name }),
      brand.tagline ? h('p', { class: 'tagline', text: brand.tagline }) : null,
      h('p', { class: 'where', text: placeName() + ' · ' + outlet.city })
    ]);
    if (brand.langs.length > 1) {
      var lang = h('div', { class: 'lang', role: 'group', 'aria-label': t('language') }, [h('span', { text: t('language') })]);
      brand.langs.forEach(function (l) {
        lang.appendChild(h('button', { type: 'button', 'data-lang': l, 'aria-pressed': String(l === I.lang()), lang: l, text: I.NAMES[l] || l }));
      });
      hdr.appendChild(lang);
    }
    var extra = theme.headerExtra && theme.headerExtra();
    if (extra) hdr.appendChild(extra);

    var wrap = h('div', { class: 'wrap' }, [hdr]);
    if (!outlet.accepting) wrap.appendChild(h('p', { class: 'notice', role: 'status', text: t('closed') }));
    if (!tableOk) wrap.appendChild(h('p', { class: 'notice', role: 'status', text: t('scan_qr') }));
    wrap.appendChild(h('div', { class: 'shop', id: 'shop' }, [
      h('section', { 'aria-label': t('order_at_table') }, [h('div', { class: 'tabs', id: 'tabs', role: 'group' }), h('div', { class: 'dishes', id: 'dishes' })]),
      h('aside', { class: 'cart', id: 'cart', 'aria-label': t('ticket') })
    ]));
    wrap.appendChild(h('section', { class: 'track', id: 'track', hidden: true, 'aria-live': 'polite' }));
    app.appendChild(wrap);
    app.appendChild(h('div', { class: 'bar', id: 'bar' }, [h('span', { id: 'bar-text' }), h('a', { href: '#cart', text: t('view_ticket') })]));

    renderTabs(); renderDishes(); renderCart();
    if (order) showConfirm(); else showShop();
  }

  /* ---------------------------------------------------------------- menu */
  function renderTabs() {
    var box = $('tabs');
    box.textContent = '';
    [{ slug: 'all', names: null }].concat(categories).forEach(function (c) {
      box.appendChild(h('button', { class: 'tab', type: 'button', 'data-tab': c.slug, 'aria-pressed': String(c.slug === activeTab), text: c.names ? I.pick(c.names) : t('everything') }));
    });
  }

  function dishCard(it) {
    var title = h('h3', { class: 'name' }, [h('span', { class: 'veg' + (it.veg ? '' : ' non'), role: 'img', 'aria-label': it.veg ? 'Vegetarian' : 'Non-vegetarian' })]);
    title.appendChild(document.createTextNode(I.pick(it.names)));
    if (it.tag) title.appendChild(h('span', { class: 'tag', text: it.tag }));
    var desc = I.pick(it.descs);
    return h('article', { class: 'dish' + (it.available ? '' : ' off'), 'data-id': it.id, 'data-cat': it.cat }, [
      title,
      desc ? h('p', { class: 'desc', text: desc }) : null,
      h('div', { class: 'row' }, [h('span', { class: 'price', text: money(it.price) }), h('span', { class: 'ctl' })])
    ]);
  }

  function renderDishes() {
    var box = $('dishes');
    box.textContent = '';
    categories.forEach(function (c) {
      if (!c.items.length) return;
      box.appendChild(h('h2', { class: 'cat-title', 'data-cat': c.slug, text: I.pick(c.names) }));
      c.items.forEach(function (it) { box.appendChild(dishCard(it)); refreshDish(it.id, box); });
    });
    applyTab();
  }

  function stepper(id, qty, name) {
    return h('span', { class: 'stepper' }, [
      h('button', { type: 'button', 'data-act': 'dec', 'data-id': id, 'aria-label': '-1 ' + name, text: '-' }),
      h('output', { 'aria-label': name, text: String(qty) }),
      h('button', { type: 'button', 'data-act': 'inc', 'data-id': id, 'aria-label': '+1 ' + name, text: '+' })
    ]);
  }

  function refreshDish(id, scope) {
    var card = (scope || document).querySelector('.dish[data-id="' + id + '"]');
    if (!card) return;
    var it = itemById[id], ctl = card.querySelector('.ctl'), q = cart[id] || 0, name = I.pick(it.names);
    ctl.textContent = '';
    if (!it.available) ctl.appendChild(h('button', { class: 'add', type: 'button', disabled: true, text: t('unavailable') }));
    else if (q === 0) ctl.appendChild(h('button', { class: 'add', type: 'button', 'data-act': 'inc', 'data-id': id, 'aria-label': t('add') + ' ' + name, text: t('add') }));
    else ctl.appendChild(stepper(id, q, name));
    card.classList.toggle('in', q > 0);
  }

  function applyTab() {
    Array.prototype.forEach.call(document.querySelectorAll('#dishes [data-cat]'), function (e) {
      e.hidden = !(activeTab === 'all' || e.getAttribute('data-cat') === activeTab);
    });
    Array.prototype.forEach.call(document.querySelectorAll('.tab'), function (b) {
      b.setAttribute('aria-pressed', String(b.getAttribute('data-tab') === activeTab));
    });
  }

  function setQty(id, delta) {
    var q = Math.max(0, Math.min(20, (cart[id] || 0) + delta));
    if (q === 0) delete cart[id]; else cart[id] = q;
    saveCart(); refreshDish(id); renderCart(); refreshBar();
    live(t(delta > 0 ? 'added' : 'removed', { name: I.pick(itemById[id].names) }) + '. ' + money(totalPrice()));
  }

  /* ---------------------------------------------------------------- ticket */
  function seg(kind, options, current) {
    var g = h('div', { class: 'seg' });
    options.forEach(function (o) { g.appendChild(h('button', { type: 'button', 'data-act': kind, 'data-v': o, 'aria-pressed': String(o === current), text: t(o) })); });
    return g;
  }

  function renderCart() {
    var n = countItems(), inn = h('div', { class: 'cart-in' });
    inn.appendChild(h('h2', { text: t('ticket') }));
    inn.appendChild(h('p', { class: 'sub', text: n ? t(n === 1 ? 'item_one' : 'item_many', { n: n }) : t('empty_sub') }));
    if (n) {
      var ul = h('ul', { class: 'lines' });
      Object.keys(cart).forEach(function (id) {
        var it = itemById[id], nm = I.pick(it.names);
        ul.appendChild(h('li', {}, [h('span', { class: 'nm', text: nm }), h('span', { class: 'lp', text: money(it.price * cart[id]) }), stepper(id, cart[id], nm)]));
      });
      inn.appendChild(ul);
      inn.appendChild(h('div', { class: 'total' }, [h('span', { text: t('total') }), h('span', { text: money(totalPrice()) })]));
    } else {
      inn.appendChild(h('p', { class: 'empty', text: t('nothing') }));
    }
    if (tableOk) inn.appendChild(h('fieldset', {}, [h('legend', { text: t('your_table') }), h('div', { class: 'tableline' }, [h('span', { text: t('table', { n: table }) })])]));
    if (hasChai()) {
      inn.appendChild(h('fieldset', {}, [h('legend', { text: t('pref_head') + ': ' + t('strength') }), seg('strength', ['Halka', 'Normal', 'Kadak'], prefs.strength)]));
      inn.appendChild(h('fieldset', {}, [h('legend', { text: t('sugar') }), seg('sugar', ['Kam', 'Normal', 'Zyada'], prefs.sugar)]));
    }
    var input = h('input', { type: 'text', maxlength: '30', autocomplete: 'given-name', 'aria-label': t('name_opt') });
    input.value = nameVal;
    input.addEventListener('input', function () { nameVal = input.value; store.write('qro_name', nameVal); });
    inn.appendChild(h('fieldset', {}, [h('legend', { text: t('name_opt') }), input]));
    if (placeError) inn.appendChild(h('p', { class: 'notice', role: 'alert', text: placeError }));
    var place = h('button', { class: 'btn place', type: 'button', 'data-act': 'place',
      text: !n ? t('add_first') : !tableOk ? t('scan_first') : t('place_total', { total: money(totalPrice()) }) });
    if (!n || !tableOk || !outlet.accepting || placing) place.disabled = true;
    inn.appendChild(place);
    inn.appendChild(h('p', { class: 'hint', text: t('no_payment') }));
    inn.appendChild(h('p', { class: 'hint', text: t('takeaway_counter') }));
    var box = $('cart');
    box.textContent = '';
    box.appendChild(inn);
  }

  function refreshBar() {
    var n = countItems(), bar = $('bar');
    if (!bar) return;
    $('bar-text').textContent = t(n === 1 ? 'item_one' : 'item_many', { n: n }) + ' - ' + money(totalPrice());
    var on = n > 0 && !order;
    bar.classList.toggle('on', on);
    document.body.classList.toggle('has-bar', on);
  }

  /* ---------------------------------------------------------------- placing */
  async function placeOrder() {
    if (!countItems() || placing || !tableOk) return;
    placing = true; placeError = ''; renderCart();
    try {
      if (!pendingKey) pendingKey = makeKey();
      var body = { outlet: slug, table: table, key: tableKey, kind: 'dine_in', name: nameVal.trim(), client_key: pendingKey,
        lines: Object.keys(cart).map(function (id) { return { item_id: Number(id), qty: cart[id] }; }) };
      if (hasChai()) body.prefs = { strength: prefs.strength, sugar: prefs.sugar };
      var res = await withRetry(function () { return api('/api/orders', { method: 'POST', body: body }); });
      pendingKey = null;
      store.write(OK, res.public_id);
      cart = {}; saveCart();
      order = await getRetry('/api/orders/' + res.public_id);
      placing = false;
      renderDishes(); renderCart();
      showConfirm();
    } catch (e) {
      placing = false;
      placeError = e.status && e.status < 500 ? e.message : t('err_place');
      if (e.status === 409) {
        try { categories = (await api('/api/menu/' + slug)).categories; indexMenu(); saveCart(); renderDishes(); } catch (x) { /* keep going */ }
      }
      renderCart(); refreshBar();
    }
  }

  /* ---------------------------------------------------------------- confirmation */
  function showShop() { $('track').hidden = true; $('shop').hidden = false; refreshBar(); }

  function orderSlip() {
    var tok = String(order.token).padStart(3, '0');
    var inn = h('div', { class: 'cart-in' });
    inn.appendChild(h('h2', { text: t('slip') }));
    inn.appendChild(h('p', { class: 'sub', text: t('token_table', { token: tok, n: order.table }) }));
    var ul = h('ul', { class: 'lines' });
    order.lines.forEach(function (l) {
      ul.appendChild(h('li', {}, [h('span', { text: l.qty + ' x' }), h('span', { class: 'nm', text: I.pick(l.names) }), h('span', { class: 'lp', text: money(l.price * l.qty) })]));
    });
    inn.appendChild(ul);
    if (order.prefs) inn.appendChild(h('p', { class: 'hint', text: t('pref_head') + ': ' + t(order.prefs.strength) + ', ' + t('sugar') + ': ' + t(order.prefs.sugar) }));
    inn.appendChild(h('div', { class: 'total' }, [h('span', { text: t('total') }), h('span', { text: money(order.total) })]));
    inn.appendChild(h('p', { class: 'hint', text: t('pay_counter') }));
    return h('section', { class: 'cart slip', 'aria-label': t('slip') }, [inn]);
  }

  function showConfirm() {
    $('shop').hidden = true;
    var box = $('track');
    box.hidden = false;
    box.textContent = '';
    refreshBar();
    var tok = String(order.token).padStart(3, '0');
    box.appendChild(h('span', { class: 'kick', text: t('token_table', { token: tok, n: order.table }) + (order.name ? ' · ' + order.name : '') }));
    box.appendChild(h('h2', { text: order.status === 'cancelled' ? t('cancelled') : t('confirm_title') }));
    if (order.status !== 'cancelled') box.appendChild(h('p', { class: 'status', text: t('confirm_text', { n: order.table }) }));
    box.appendChild(orderSlip());
    box.appendChild(h('button', { class: 'btn again', type: 'button', 'data-act': 'again', text: t('more') }));
    live(t('confirm_title'));
    window.scrollTo(0, 0);
  }

  /* ---------------------------------------------------------------- events */
  document.addEventListener('click', function (e) {
    var el = e.target.closest ? e.target.closest('button[data-act],button[data-tab],button[data-lang]') : null;
    if (!el) return;
    var act = el.getAttribute('data-act'), id = el.getAttribute('data-id'), v = el.getAttribute('data-v');
    var scope = el.closest('#cart') ? '#cart' : '#dishes';
    if (el.hasAttribute('data-lang')) { var l = el.getAttribute('data-lang'); I.setLang(l, brand.default_lang); store.write('qro_lang', l); build(); return; }
    if (el.hasAttribute('data-tab')) { activeTab = el.getAttribute('data-tab'); applyTab(); return; }
    if (act === 'inc') { setQty(id, 1); focusBack(scope, 'inc', id); }
    else if (act === 'dec') { setQty(id, -1); focusBack(scope, 'dec', id); }
    else if (act === 'strength' || act === 'sugar') { prefs[act] = v; store.write('qro_prefs', prefs); renderCart(); focusBack('#cart', act, null, v); }
    else if (act === 'place') placeOrder();
    else if (act === 'again') { store.drop(OK); order = null; showShop(); window.scrollTo(0, 0); }
  });

  function focusBack(scope, act, id, v) {
    var sel = scope + ' [data-act="' + act + '"]' + (id ? '[data-id="' + id + '"]' : '') + (v ? '[data-v="' + v + '"]' : '');
    var el = document.querySelector(sel) || (id ? document.querySelector(scope + ' [data-act="inc"][data-id="' + id + '"]') : null);
    if (el) el.focus();
  }

  boot();
})();

/* The guest connection kit: everything a restaurant's own website needs to talk to the shared backend.
   A design only draws screens. It never works out prices, decides who may order, or retries by itself.
   See web/kit/README.md. Needs /js/api.js loaded first. */
(function () {
  'use strict';

  var Q = window.QRO, api = Q.api, store = Q.store;
  var KEEP_ORDER_MS = 2 * 3600 * 1000;

  var wait = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };
  // Try again on a lost connection or a server hiccup. A refusal (4xx) is final.
  async function retry(call) {
    for (var i = 0; ; i++) {
      try { return await call(); }
      catch (e) { if ((e.status && e.status < 500) || i >= 3) throw e; await wait(700 * (i + 1) + Math.random() * 500); }
    }
  }
  function randomKey() {
    var b = new Uint8Array(16);
    window.crypto.getRandomValues(b);
    return Array.prototype.map.call(b, function (x) { return x.toString(16).padStart(2, '0'); }).join('');
  }

  /* open() reads the address (/r/<outlet>[/<table>]?k=<table code>) and returns the session below. */
  async function open() {
    var parts = location.pathname.split('/').filter(Boolean);
    var params = new URLSearchParams(location.search);
    var slug = parts[0] === 'r' ? parts[1] : params.get('outlet');
    var table = parseInt(parts[2], 10) || null;
    var tableKey = params.get('k') || '';
    if (!slug) { var none = new Error('No restaurant in this address'); none.status = 404; throw none; }

    var first = await retry(function () { return Promise.all([api('/api/outlet/' + slug), api('/api/menu/' + slug)]); });
    var tableOk = false;
    if (table && tableKey) {
      try { tableOk = (await retry(function () { return api('/api/table/' + slug + '/' + table + '?k=' + encodeURIComponent(tableKey)); })).valid; }
      catch (e) { tableOk = false; }
    }

    var CART = 'qro_cart_' + slug, LAST = 'qro_order_' + slug + '_' + (table || 0);
    var cart = store.read(CART, {}) || {};
    var pendingKey = null, placing = false;

    var s = {
      brand: first[0].brand,
      outlet: first[0].outlet,
      categories: [],
      items: {},
      table: tableOk ? table : null,
      // True only with a valid table code, and while the restaurant is taking orders. The server checks again.
      get canOrder() { return tableOk && s.outlet.accepting; },
      get hasTableCode() { return tableOk; },

      setMenu: function (categories) {
        s.categories = categories;
        s.items = {};
        categories.forEach(function (c) { c.items.forEach(function (i) { i.cat = c.slug; s.items[i.id] = i; }); });
        Object.keys(cart).forEach(function (id) { if (!s.items[id] || !s.items[id].available) delete cart[id]; });
        store.write(CART, cart);
      },
      reloadMenu: async function () { s.setMenu((await api('/api/menu/' + slug)).categories); },

      qty: function (id) { return cart[id] || 0; },
      lines: function () { return Object.keys(cart).map(function (id) { return { item: s.items[id], qty: cart[id] }; }); },
      count: function () { return Object.keys(cart).reduce(function (n, k) { return n + cart[k]; }, 0); },
      // For showing only. The server works out the real price when the order arrives.
      total: function () { return Object.keys(cart).reduce(function (n, k) { return n + cart[k] * s.items[k].price; }, 0); },
      change: function (id, delta) {
        if (!s.items[id] || !s.items[id].available) return;
        var q = Math.max(0, Math.min(20, (cart[id] || 0) + delta));
        if (q === 0) delete cart[id]; else cart[id] = q;
        store.write(CART, cart);
        pendingKey = null;
      },

      /* extra: {name, note, prefs}. Resolves with the saved order; throws an Error with a message for the guest. */
      place: async function (extra) {
        if (placing || !s.canOrder || !s.count()) return null;
        placing = true;
        try {
          // One key per order attempt, so a retry or a double tap can never order twice.
          if (!pendingKey) pendingKey = randomKey();
          var body = { outlet: slug, table: table, key: tableKey, kind: 'dine_in', client_key: pendingKey,
            name: (extra && extra.name || '').trim(), note: (extra && extra.note || '').trim(),
            lines: Object.keys(cart).map(function (id) { return { item_id: Number(id), qty: cart[id] }; }) };
          if (extra && extra.prefs) body.prefs = extra.prefs;
          var saved = await retry(function () { return api('/api/orders', { method: 'POST', body: body }); });
          pendingKey = null;
          cart = {};
          store.write(CART, cart);
          store.write(LAST, saved.public_id);
          return await retry(function () { return api('/api/orders/' + saved.public_id); });
        } catch (e) {
          if (e.status === 409) { try { await s.reloadMenu(); } catch (x) { /* show the first error */ } }
          throw e;
        } finally {
          placing = false;
        }
      },

      /* The order this phone placed at this table recently, or null. */
      lastOrder: async function () {
        var id = store.read(LAST, null);
        if (!id) return null;
        try {
          var o = await api('/api/orders/' + id);
          if (o.status === 'served' || o.status === 'cancelled' || Date.now() - o.created_at * 1000 > KEEP_ORDER_MS) { store.drop(LAST); return null; }
          return o;
        } catch (e) { store.drop(LAST); return null; }
      },
      forgetOrder: function () { store.drop(LAST); }
    };
    s.setMenu(first[1].categories);
    return s;
  }

  window.QROKit = { open: open };
})();

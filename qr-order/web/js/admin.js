/* Owner admin for a brand: head-office overview, menu editor, tables and QR sheet, settings. */
(function () {
  'use strict';

  var Q = window.QRO, h = Q.h, $ = Q.$, api = Q.api, session = Q.session;
  var params = new URLSearchParams(location.search);
  var brandSlug = params.get('brand');
  var token = null, brand = null, overview = null, outletSlug = params.get('outlet'), menu = null, tab = params.get('tab') || 'overview';
  var editing = null, baseUrl = location.origin, qr = null;
  var NAMES = { en: 'English', hi: 'Hindi', mr: 'Marathi' };

  function money(cur, n) { return (cur === 'INR' ? 'Rs. ' : cur + ' ') + n; }
  function pickName(names) { return (names && (names[brand.default_lang] || names.en || names[Object.keys(names)[0]])) || ''; }
  function toast(msg) {
    var t = h('div', { class: 'toast', role: 'status', text: msg });
    document.body.appendChild(t);
    setTimeout(function () { t.remove(); }, 2200);
  }
  function out() { return overview.outlets.filter(function (o) { return o.slug === outletSlug; })[0]; }
  function call(path, opts) {
    opts = opts || {}; opts.token = token;
    return api('/api/admin/' + brandSlug + path, opts).catch(function (e) {
      if (e.status === 401 || e.status === 403) { forget(); loginView('Please sign in again'); }
      throw e;
    });
  }

  function forget() { window.QROBusiness.drop(); session.drop('qro_tok_admin_' + brandSlug); session.drop('qro_key_admin_' + brandSlug); token = null; overview = null; }

  /* ------------------------------------------------------------ login */
  async function boot() {
    if (!brandSlug) { $('app').appendChild(h('p', { style: 'padding:30px', text: 'Open this page from your restaurant link (admin.html?brand=...).' })); return; }
    token = session.read('qro_tok_admin_' + brandSlug);
    if (token) await load(); else loginView();
  }

  function loginView(msg) {
    var app = $('app');
    app.textContent = '';
    var pin = h('input', { type: 'password', autocomplete: 'current-password', 'aria-label': 'Owner password', maxlength: '128', style: 'letter-spacing:0' });
    var err = h('p', { class: 'err', role: 'alert', text: msg || '' });
    var go = async function () {
      try {
        var r = await api('/api/login', { method: 'POST', body: { scope: 'admin', slug: brandSlug, pin: pin.value } });
        token = r.token; session.write('qro_tok_admin_' + brandSlug, token); session.write('qro_key_admin_' + brandSlug, r.stream_key); await load();
      } catch (e) { err.textContent = e.message; pin.value = ''; pin.focus(); }
    };
    pin.addEventListener('keydown', function (e) { if (e.key === 'Enter') go(); });
    var btn = h('button', { class: 'btn big', type: 'button', style: 'width:100%', text: 'Open owner panel' });
    btn.addEventListener('click', go);
    app.appendChild(h('div', { class: 'login' }, [h('h1', { text: 'Owner panel' }), h('p', { text: brandSlug }), err, pin, btn]));
    pin.focus();
  }

  async function load() {
    try {
      overview = await call('/overview');
      brand = overview.brand;
      if (!out()) outletSlug = overview.outlets[0].slug;
      menu = await call('/menu?outlet=' + outletSlug);
      render();
    } catch (e) { /* login view already shown on auth errors */ }
  }

  async function reloadMenu() { menu = await call('/menu?outlet=' + outletSlug); render(); }
  async function reloadAll() { overview = await call('/overview'); menu = await call('/menu?outlet=' + outletSlug); render(); }

  /* ------------------------------------------------------------ frame */
  function render() {
    if (!overview) return;
    var app = $('app');
    app.textContent = '';
    var sel = h('select', { 'aria-label': 'Outlet', style: 'width:auto' });
    overview.outlets.forEach(function (o) { sel.appendChild(h('option', { value: o.slug, text: o.name + ' (' + o.city + ')' })); });
    sel.value = outletSlug;
    sel.addEventListener('change', async function () { outletSlug = sel.value; editing = null; qr = null; window.QROBusiness.drop(); await reloadMenu(); });
    var logout = h('button', { class: 'btn ghost', type: 'button', text: 'Sign out' });
    logout.addEventListener('click', async function () {
      try { await api('/api/logout', { method: 'POST', token: token, body: {} }); } catch (e) { /* already signed out */ }
      forget(); loginView('Signed out');
    });
    app.appendChild(h('div', { class: 'bar' }, [h('h1', { text: brand.name }), h('span', { class: 'stat', text: 'Owner panel' }), h('span', { class: 'grow' }), sel, logout]));

    var tabs = h('div', { class: 'tabs', role: 'tablist' });
    [['overview', 'Overview'], ['menu', 'Menu'], ['stock', 'Stock'], ['recipes', 'Dish costs'], ['reports', 'Money & Excel'], ['qr', 'Tables & QR'], ['settings', 'Settings'], ['security', 'Security & backups'], ['activity', 'Activity']].forEach(function (t) {
      var b = h('button', { type: 'button', 'aria-pressed': String(tab === t[0]), text: t[1] });
      b.addEventListener('click', function () { tab = t[0]; editing = null; qr = null; window.QROBusiness.drop(); render(); });
      tabs.appendChild(b);
    });
    app.appendChild(tabs);
    var pane = h('div', { class: 'pane' });
    app.appendChild(pane);
    ({ overview: drawOverview, menu: drawMenu, qr: drawQr, settings: drawSettings, security: drawSecurity, activity: drawActivity,
      stock: business('stock'), recipes: business('recipes'), reports: business('reports') })[tab](pane);
  }

  function business(name) {
    var ctx = { outlet: out, call: call, toast: toast, render: render, brandSlug: brandSlug, token: function () { return token; },
      money: function (n) { return money(out().currency, n); } };
    return function (pane) { window.QROBusiness[name](pane, ctx); };
  }

  /* ------------------------------------------------------------ overview */
  function drawOverview(pane) {
    pane.appendChild(h('h2', { text: 'Today across all outlets' }));
    var cards = h('div', { class: 'cards' });
    overview.outlets.forEach(function (o) {
      var kitchen = h('a', { href: '/kitchen.html?outlet=' + o.slug, target: '_blank', rel: 'noopener', text: 'Open kitchen screen' });
      cards.appendChild(h('div', { class: 'card' }, [
        h('h3', { text: o.name }),
        h('div', { class: 'sub', text: o.city + ', ' + o.country }),
        h('div', { class: 'big', text: money(o.currency, o.sales_today) }),
        h('div', { class: 'sub', text: o.orders_today + ' orders today · ' + o.live + ' in progress' }),
        h('div', { class: 'sub', text: o.accepting ? 'Taking orders' : 'NOT taking orders' }),
        o.unpaid_total ? h('div', { class: 'sub', text: money(o.currency, o.unpaid_total) + ' in unpaid bills' }) : null,
        o.low_stock.length ? h('div', { class: 'err', text: 'Low stock: ' + o.low_stock.join(', ') }) : null,
        h('p', {}, [kitchen])
      ]));
    });
    pane.appendChild(cards);
    pane.appendChild(h('h2', { text: 'Top items today (all outlets)' }));
    if (!overview.top_items.length) pane.appendChild(h('p', { class: 'hint', text: 'No orders yet today. Place one from a table link and it will show here.' }));
    else {
      var tb = h('table', { class: 't' }, [h('tr', {}, [h('th', { text: 'Item' }), h('th', { text: 'Sold' })])]);
      overview.top_items.forEach(function (t) { tb.appendChild(h('tr', {}, [h('td', { text: pickName(t.names) }), h('td', { text: String(t.qty) })])); });
      pane.appendChild(tb);
    }
    var refresh = h('button', { class: 'btn ghost', type: 'button', text: 'Refresh numbers' });
    refresh.addEventListener('click', reloadAll);
    pane.appendChild(refresh);
  }

  /* ------------------------------------------------------------ menu */
  function drawMenu(pane) {
    var o = out();
    pane.appendChild(h('h2', { text: 'Menu for ' + o.name }));
    pane.appendChild(h('p', { class: 'hint', text: 'One master menu for the brand. Here you can change this outlet\'s price and mark items out of stock. Editing an item changes it at every outlet.' }));
    var add = h('button', { class: 'btn', type: 'button', text: '+ Add item' });
    add.addEventListener('click', function () { editing = { id: null }; render(); });
    pane.appendChild(add);
    if (!menu.categories.length) { add.disabled = true; pane.appendChild(h('p', { class: 'err', text: 'First add a menu section (for example Chai or Snacks) below.' })); }
    var secName = h('input', { type: 'text', maxlength: '60', placeholder: 'New menu section name', 'aria-label': 'New menu section name (English)', style: 'max-width:320px' });
    var secBtn = h('button', { class: 'btn ghost', type: 'button', text: '+ Add menu section' });
    secBtn.addEventListener('click', async function () {
      try { await call('/categories', { method: 'POST', body: { names: { en: secName.value } } }); toast('Section added'); await reloadMenu(); } catch (e) { toast(e.message); }
    });
    pane.appendChild(h('div', { class: 'inline', style: 'margin-top:10px' }, [secName, secBtn]));
    if (editing && editing.id === null) pane.appendChild(editor(null));
    menu.categories.forEach(function (cat) {
      pane.appendChild(h('h3', { style: 'margin-top:22px', text: pickName(cat.names) }));
      var tb = h('table', { class: 't' }, [h('tr', {}, ['Item', 'Base price', 'Price here', 'Available', 'Always ready?', ''].map(function (x) { return h('th', { text: x }); }))]);
      cat.items.forEach(function (it) {
        var ov = h('input', { type: 'number', class: 'price', min: '0', placeholder: String(it.base_price), 'aria-label': 'Price at this outlet for ' + pickName(it.names), value: it.override === null ? '' : String(it.override) });
        ov.addEventListener('change', function () { saveOutletItem(it, ov.value === '' ? null : Number(ov.value), it.available); });
        var tog = h('button', { class: 'tog off', type: 'button', 'aria-pressed': String(it.available), text: it.available ? 'In stock' : 'Out of stock' });
        tog.addEventListener('click', function () { saveOutletItem(it, it.override, !it.available); });
        var inst = h('button', { class: 'tog', type: 'button', 'aria-pressed': String(it.instant), title: 'Always-ready items print at once and skip the kitchen queue (all outlets)', text: it.instant ? 'Instant' : 'Cooked' });
        inst.addEventListener('click', async function () {
          try { await call('/items/' + it.id, { method: 'PUT', body: { instant: !it.instant } }); toast('Saved for every outlet'); await reloadMenu(); } catch (e) { toast(e.message); }
        });
        var edit = h('button', { class: 'btn ghost', type: 'button', text: 'Edit' });
        edit.addEventListener('click', function () { editing = { id: it.id }; render(); });
        tb.appendChild(h('tr', { class: it.available ? '' : 'row-off' }, [
          h('td', { text: (it.veg ? '' : '[non-veg] ') + pickName(it.names) + (it.tag ? '  (' + it.tag + ')' : '') }),
          h('td', { text: money(o.currency, it.base_price) }), h('td', {}, [ov]), h('td', {}, [tog]), h('td', {}, [inst]), h('td', {}, [edit])
        ]));
        if (editing && editing.id === it.id) tb.appendChild(h('tr', {}, [h('td', { colspan: '6' }, [editor(it)])]));
      });
      pane.appendChild(tb);
    });
  }

  async function saveOutletItem(it, price, available) {
    try {
      await call('/outlet-items?outlet=' + outletSlug, { method: 'PUT', body: { item_id: it.id, price: price, available: available } });
      toast('Saved'); await reloadMenu();
    } catch (e) { toast(e.message); }
  }

  function editor(it) {
    var box = h('div', { class: 'editor' }), fields = {};
    box.appendChild(h('h3', { text: it ? 'Edit item' : 'New item' }));
    var catSel = null;
    if (!it) {
      catSel = h('select', { 'aria-label': 'Category' });
      menu.categories.forEach(function (c) { catSel.appendChild(h('option', { value: c.slug, text: pickName(c.names) })); });
      box.appendChild(h('label', { class: 'f', text: 'Category' })); box.appendChild(catSel);
    }
    brand.langs.forEach(function (l) {
      box.appendChild(h('label', { class: 'f', text: 'Name in ' + (NAMES[l] || l) + (l === brand.default_lang ? ' (required)' : '') }));
      var n = h('input', { type: 'text', maxlength: '120', value: it ? (it.names[l] || '') : '' });
      fields['n_' + l] = n; box.appendChild(n);
    });
    brand.langs.forEach(function (l) {
      box.appendChild(h('label', { class: 'f', text: 'Description in ' + (NAMES[l] || l) + ' (optional, falls back to the default language)' }));
      var d = h('input', { type: 'text', maxlength: '120', value: it ? (it.descs[l] || '') : '' });
      fields['d_' + l] = d; box.appendChild(d);
    });
    box.appendChild(h('label', { class: 'f', text: 'Base price (in the outlet currency)' }));
    var price = h('input', { type: 'number', min: '0', class: 'price', value: it ? String(it.base_price) : '' }); box.appendChild(price);
    box.appendChild(h('label', { class: 'f', text: 'Tag (optional, e.g. Bestseller)' }));
    var tag = h('input', { type: 'text', maxlength: '30', value: it ? (it.tag || '') : '' }); box.appendChild(tag);
    var veg = h('input', { type: 'checkbox', id: 'vegcb' }); veg.checked = it ? it.veg : true;
    box.appendChild(h('p', {}, [veg, h('label', { for: 'vegcb', text: ' Vegetarian' })]));
    var save = h('button', { class: 'btn', type: 'button', text: 'Save' }), cancel = h('button', { class: 'btn ghost', type: 'button', text: 'Cancel' });
    cancel.addEventListener('click', function () { editing = null; render(); });
    save.addEventListener('click', async function () {
      var names = {}, descs = {};
      brand.langs.forEach(function (l) { names[l] = fields['n_' + l].value; descs[l] = fields['d_' + l].value; });
      var body = { names: names, descs: descs, price: Number(price.value), veg: veg.checked, tag: tag.value };
      try {
        if (it) await call('/items/' + it.id, { method: 'PUT', body: body });
        else { body.category = catSel.value; await call('/items', { method: 'POST', body: body }); }
        editing = null; toast('Saved for every outlet'); await reloadMenu();
      } catch (e) { toast(e.message); }
    });
    var row = h('div', { class: 'inline' }, [save, cancel]);
    if (it) {
      var remove = h('button', { class: 'btn red', type: 'button', text: 'Remove dish' });
      remove.addEventListener('click', async function () {
        if (!confirm('Remove this dish from the menu at every outlet? Past sales stay in your records.')) return;
        try { await call('/items/' + it.id, { method: 'PUT', body: { archived: true } }); editing = null; toast('Removed'); await reloadMenu(); } catch (e) { toast(e.message); }
      });
      row.appendChild(remove);
    }
    box.appendChild(row);
    return box;
  }

  /* ------------------------------------------------------------ tables & QR */
  function drawQr(pane) {
    var o = out();
    if (!qr || qr.outlet !== o.slug || qr.tables.length !== o.tables) {
      pane.appendChild(h('p', { class: 'hint', text: 'Loading table codes...' }));
      call('/qr?outlet=' + o.slug).then(function (d) { d.outlet = o.slug; qr = d; if (tab === 'qr') render(); }).catch(function (e) { toast(e.message); });
      return;
    }
    pane.appendChild(h('h2', { text: 'Table QR codes for ' + o.name }));
    pane.appendChild(h('p', { class: 'hint', text: 'Each table gets its own QR code with the table number inside the link, so customers never pick a table. Print the sheet and stick one on every table.' }));

    var tables = h('input', { type: 'number', min: '1', max: '200', class: 'price', value: String(o.tables), 'aria-label': 'Number of tables' });
    var saveT = h('button', { class: 'btn', type: 'button', text: 'Save table count' });
    saveT.addEventListener('click', async function () {
      try { await call('/outlets/' + o.slug, { method: 'PUT', body: { tables: Number(tables.value) } }); toast('Saved'); await reloadAll(); } catch (e) { toast(e.message); }
    });
    pane.appendChild(h('div', { class: 'inline' }, [h('label', { class: 'f', style: 'margin:0', text: 'Number of tables' }), tables, saveT]));

    pane.appendChild(h('label', { class: 'f', text: 'Web address the QR codes point to' }));
    var base = h('input', { type: 'text', value: baseUrl, 'aria-label': 'Base web address' });
    base.addEventListener('change', function () { baseUrl = base.value.replace(/\/+$/, ''); render(); });
    pane.appendChild(base);
    var hint = h('p', { class: 'hint', text: 'Phones cannot open "localhost". To use phones on the shop Wi-Fi, start the server with --lan and press the button below. Once the store is online, put its web address here.' });
    pane.appendChild(hint);
    var lan = h('button', { class: 'btn ghost', type: 'button', text: 'Use my Wi-Fi address (for phones)' });
    lan.addEventListener('click', function () { baseUrl = (qr.https ? 'https://' : 'http://') + qr.lan_ip + ':' + qr.port; render(); });
    pane.appendChild(lan);
    var fresh = h('button', { class: 'btn red noprint', type: 'button', style: 'margin-left:8px', text: 'Make new QR codes' });
    fresh.addEventListener('click', async function () {
      if (!confirm('Every printed QR code for this outlet will STOP working. You must print and replace them all. Continue?')) return;
      try { await call('/outlets/' + o.slug + '/new-qr', { method: 'POST', body: {} }); qr = null; toast('New codes made. Print them now.'); render(); } catch (e) { toast(e.message); }
    });
    pane.appendChild(fresh);
    pane.appendChild(h('p', { class: 'hint', text: 'Each code holds a secret for its table, so only someone who has scanned it can order. If a code is photographed and misused, make new codes.' }));

    var print = h('button', { class: 'btn noprint', type: 'button', style: 'margin-left:8px', text: 'Print / save as PDF' });
    print.addEventListener('click', function () { window.print(); });
    pane.appendChild(print);

    var sheet = h('div', { class: 'qrsheet' });
    for (var n = 1; n <= o.tables; n++) sheet.appendChild(qrCard(o, n));
    pane.appendChild(sheet);
  }

  function qrCard(o, n) {
    var url = baseUrl + qr.tables[n - 1].path;
    var holder = h('div', { class: 'qr' });
    try {
      var code = window.qrcode(0, 'M'); code.addData(url); code.make();
      holder.appendChild(Q.svg(code.createSvgTag({ cellSize: 4, margin: 0, scalable: true })));
    } catch (e) { holder.appendChild(h('p', { class: 'hint', text: 'QR library not loaded (needs internet once).' })); }
    var place = o.name.indexOf(brand.name) === 0 ? o.name.slice(brand.name.length).replace(/^[\s-]+/, '') : o.name;
    return h('div', { class: 'qrcard' }, [
      h('div', { class: 'brandname', text: brand.name }), h('div', { class: 'scan', text: place }),
      h('div', { class: 'tno', text: 'Table ' + n }), holder,
      h('div', { class: 'scan', text: 'Scan to order from your table' }),
      h('a', { class: 'noprint openq', href: qr.tables[n - 1].path, target: '_blank', rel: 'noopener', text: 'Open as this table' })
    ]);
  }

  /* ------------------------------------------------------------ settings */
  function drawSettings(pane) {
    var o = out();
    pane.appendChild(h('h2', { text: 'Settings for ' + o.name }));
    var acc = h('button', { class: 'tog off', type: 'button', 'aria-pressed': String(o.accepting), text: o.accepting ? 'Taking orders' : 'Paused - not taking orders' });
    acc.addEventListener('click', async function () {
      try { await call('/outlets/' + o.slug, { method: 'PUT', body: { accepting: !o.accepting } }); await reloadAll(); toast('Saved'); } catch (e) { toast(e.message); }
    });
    pane.appendChild(h('label', { class: 'f', text: 'Order intake' })); pane.appendChild(acc);
    pane.appendChild(h('p', { class: 'hint', text: 'Pause when the kitchen is overwhelmed or closing. Customers see a notice and cannot place orders.' }));

    var save = async function (body) {
      try { await call('/outlets/' + o.slug, { method: 'PUT', body: body }); await reloadAll(); toast('Saved'); } catch (e) { toast(e.message); }
    };
    var take = h('button', { class: 'tog off', type: 'button', 'aria-pressed': String(o.takeaway), text: o.takeaway ? 'Takeaway ON' : 'Dine-in only' });
    take.addEventListener('click', function () { save({ takeaway: !o.takeaway }); });
    pane.appendChild(h('label', { class: 'f', text: 'Takeaway sales' })); pane.appendChild(take);
    var auto = h('button', { class: 'tog off', type: 'button', 'aria-pressed': String(o.auto_accept), text: o.auto_accept ? 'Auto-accept ON' : 'Auto-accept OFF' });
    auto.addEventListener('click', function () { save({ auto_accept: !o.auto_accept }); });
    pane.appendChild(h('label', { class: 'f', text: 'Accepting new orders in the kitchen' })); pane.appendChild(auto);
    pane.appendChild(h('p', { class: 'hint', text: 'On: orders are accepted by themselves and their slips go straight to the print queue. Off: staff press Accept on each one.' }));

    var printing = h('div', { class: 'inline', style: 'flex-wrap:wrap' }, [h('span', { text: 'Checking...' })]);
    pane.appendChild(h('label', { class: 'f', text: 'Printing at THIS outlet' })); pane.appendChild(printing);
    pane.appendChild(h('p', { class: 'hint', text: 'No print: orders show on screens only, and nobody is asked about printers. Printers are the ones plugged into the store computer by USB. The kitchen screen also has a test print and reprint.' }));
    drawPrinting(printing, o);

    var gap = h('input', { type: 'number', min: '0', max: '120', step: '0.5', class: 'price', value: String(o.print_gap), 'aria-label': 'Seconds between kitchen slips' });
    gap.addEventListener('change', function () { save({ print_gap: Number(gap.value) }); });
    var quick = [5, 2, 0].map(function (n) {
      var b = h('button', { class: 'btn ghost', type: 'button', text: n ? n + ' s' : 'No gap' });
      b.addEventListener('click', function () { save({ print_gap: n }); });
      return b;
    });
    pane.appendChild(h('label', { class: 'f', text: 'Seconds between kitchen slips at THIS outlet' }));
    pane.appendChild(h('div', { class: 'inline' }, [gap].concat(quick)));
    pane.appendChild(h('p', { class: 'hint', text: o.print_gap > 0
      ? 'That is at most ' + Math.round(60 / o.print_gap) + ' kitchen slips a minute. If more orders than that arrive, they wait in the queue and the kitchen screen warns you.'
      : 'No gap: every slip prints as soon as the order arrives.' }));

    var po = h('select', { 'aria-label': 'Print order', style: 'max-width:340px' }, [
      h('option', { value: 'fifo', text: 'First in, first out' }),
      h('option', { value: 'small_first', text: 'Small orders first (nothing waits over 2 min)' })]);
    po.value = o.print_order;
    po.addEventListener('change', function () { save({ print_order: po.value }); });
    pane.appendChild(h('label', { class: 'f', text: 'Which slip prints next' })); pane.appendChild(po);
    pane.appendChild(h('p', {}, [h('a', { href: '/board.html?outlet=' + o.slug, target: '_blank', rel: 'noopener', text: 'Open the takeaway token board for this outlet' })]));

    var kl = h('select', { 'aria-label': 'Kitchen language', style: 'max-width:240px' });
    brand.langs.forEach(function (l) { kl.appendChild(h('option', { value: l, text: NAMES[l] || l })); });
    kl.value = o.kitchen_lang;
    kl.addEventListener('change', async function () {
      try { await call('/outlets/' + o.slug, { method: 'PUT', body: { kitchen_lang: kl.value } }); await reloadAll(); toast('Saved'); } catch (e) { toast(e.message); }
    });
    pane.appendChild(h('label', { class: 'f', text: 'Language the kitchen screen shows dish names in' })); pane.appendChild(kl);
    pane.appendChild(h('p', { class: 'hint', text: 'Customers can order in any language. The kitchen always sees its own, because orders store the dish, not the translated words.' }));

    pane.appendChild(h('label', { class: 'f', text: 'Kitchen screen link' }));
    pane.appendChild(h('p', {}, [h('a', { href: '/kitchen.html?outlet=' + o.slug, target: '_blank', rel: 'noopener', text: location.origin + '/kitchen.html?outlet=' + o.slug })]));
  }

  function drawPrinting(box, o, data) {
    var path = '/api/kitchen/' + o.slug + '/printer';
    if (!data) {
      api(path, { token: token }).then(function (d) { drawPrinting(box, o, d); }).catch(function (e) { box.textContent = e.message; });
      return;
    }
    box.textContent = '';
    var width = h('select', { 'aria-label': 'Paper width', style: 'width:auto' }, [h('option', { value: '80', text: '80 mm paper' }), h('option', { value: '58', text: '58 mm paper' })]);
    width.value = String(data.width);
    var set = function (body) {
      api(path, { method: 'PUT', token: token, body: body }).then(function (d) { toast('Saved'); drawPrinting(box, o, d); }).catch(function (e) { toast(e.message); });
    };
    var choice = function (label, on, body) {
      var b = h('button', { class: 'tog', type: 'button', 'aria-pressed': String(on), text: label });
      b.addEventListener('click', function () {
        if (body.mode === 'none' && (data.waiting || data.failed) && data.mode === 'usb' && !confirm('Slips that are waiting or failed will NOT be printed. Continue?')) return;
        if (body.mode === 'usb') body.width = Number(width.value);
        set(body);
      });
      box.appendChild(b);
    };
    choice('No print', data.mode === 'none', { mode: 'none' });
    choice('Ask when a USB printer is connected', data.mode === 'ask', { mode: 'ask' });
    data.detected.forEach(function (p) {
      choice('Print on ' + p.name + (p.connected ? '' : ' (not connected)'), data.mode === 'usb' && data.name === p.name, { mode: 'usb', name: p.name });
    });
    if (data.mode === 'usb' && !data.detected.some(function (p) { return p.name === data.name; })) box.appendChild(h('span', { class: 'err', text: data.name + ' is no longer set up on this computer' }));
    if (data.detected.length) box.appendChild(width);
    if (data.mode !== 'none' && !data.detected.length) box.appendChild(h('span', { class: 'hint', text: 'No USB printer found right now.' }));
  }

  /* ------------------------------------------------------------ security and backups */
  function passField(pane, label, auto) {
    var id = 'p' + Math.random().toString(36).slice(2);
    var i = h('input', { type: 'password', id: id, autocomplete: auto, maxlength: '128', style: 'max-width:420px' });
    pane.appendChild(h('label', { class: 'f', for: id, text: label })); pane.appendChild(i);
    return i;
  }
  function action(pane, label, fn) {
    var b = h('button', { class: 'btn', type: 'button', style: 'margin-top:12px', text: label });
    b.addEventListener('click', async function () { b.disabled = true; try { await fn(); } catch (e) { toast(e.message); } b.disabled = false; });
    pane.appendChild(b);
  }

  function drawSecurity(pane) {
    var o = out();
    pane.appendChild(h('h2', { text: 'Owner password' }));
    var cur = passField(pane, 'Current password', 'current-password'), neu = passField(pane, 'New password (at least 10 characters)', 'new-password'), again = passField(pane, 'New password again', 'new-password');
    action(pane, 'Change owner password', async function () {
      if (neu.value !== again.value) { toast('The new passwords do not match'); return; }
      await call('/password', { method: 'POST', body: { current: cur.value, new: neu.value } });
      forget(); loginView('Password changed. Sign in with the new one.');
    });

    pane.appendChild(h('h2', { style: 'margin-top:28px', text: 'Staff PIN for ' + o.name }));
    pane.appendChild(h('p', { class: 'hint', text: 'Used by the kitchen screen and the counter. Change it when someone leaves. All staff screens are signed out.' }));
    var mine = passField(pane, 'Your owner password', 'current-password'), pin = passField(pane, 'New staff PIN (6 to 12 digits)', 'new-password');
    action(pane, 'Change staff PIN', async function () {
      await call('/outlets/' + o.slug + '/staff-pin', { method: 'POST', body: { current_password: mine.value, pin: pin.value } });
      mine.value = pin.value = ''; toast('Staff PIN changed');
    });

    pane.appendChild(h('h2', { style: 'margin-top:28px', text: 'Backups' }));
    pane.appendChild(h('p', { class: 'hint', text: 'A backup is saved on this computer every day (the last 14 are kept). Download a copy to another device regularly: if this computer breaks, backups stored only on it are lost too. Customer phone numbers are deleted after 30 days.' }));
    action(pane, 'Make a backup now', async function () { var r = await call('/backup', { method: 'POST', body: {} }); toast('Saved ' + r.name); });
    var dl = passField(pane, 'To download a copy, enter your owner password', 'current-password');
    action(pane, 'Download a backup copy', async function () {
      var res = await fetch('/api/admin/' + brandSlug + '/backup/download', { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token }, body: JSON.stringify({ password: dl.value }) });
      if (!res.ok) throw new Error((await res.json()).error || 'Download failed');
      var url = URL.createObjectURL(await res.blob());
      var a = h('a', { href: url, download: (res.headers.get('Content-Disposition') || '').split('"')[1] || 'store-backup.db' });
      document.body.appendChild(a); a.click(); a.remove(); setTimeout(function () { URL.revokeObjectURL(url); }, 5000);
      dl.value = ''; toast('Keep that file somewhere private: it holds your sales and customer data');
    });
  }

  function drawActivity(pane) {
    pane.appendChild(h('h2', { text: 'Activity log (latest 200)' }));
    pane.appendChild(h('p', { class: 'hint', text: 'Sign-ins (including wrong ones), price and settings changes, counter sales, rejected orders and backups.' }));
    var box = h('div', { text: 'Loading...' });
    pane.appendChild(box);
    call('/activity').then(function (d) {
      var tb = h('table', { class: 't' }, [h('tr', {}, ['When', 'Who', 'From', 'What', 'Detail'].map(function (x) { return h('th', { text: x }); }))]);
      d.activity.forEach(function (a) {
        tb.appendChild(h('tr', {}, [new Date(a.at * 1000).toLocaleString(), a.actor, a.ip, a.action, a.detail].map(function (x) { return h('td', { text: x || '' }); })));
      });
      box.textContent = ''; box.appendChild(tb);
    }).catch(function (e) { box.textContent = e.message; });
  }

  boot();
})();

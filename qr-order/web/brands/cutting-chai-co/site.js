/* Cutting Chai Co.'s own guest website. It only draws screens: the menu, cart rules, table check and
   ordering all come from the shared connection kit (/kit/guest.js) and the backend behind it. */
(function () {
  'use strict';

  var Q = window.QRO, h = Q.h, $ = Q.$, store = Q.store;
  var I = window.I18N, t = I.t;
  var s = null, tab = 'all', placing = false, error = '';
  var prefs = store.read('qro_prefs', { strength: 'Kadak', sugar: 'Normal' });
  var guestName = store.read('qro_name', ''), note = '';

  function money(n) { return I.money(s.outlet.currency, n); }
  function live(msg) { $('live').textContent = msg; }
  function hasChai() { return s.lines().some(function (l) { return l.item.cat === 'chai'; }); }
  function placeName() { return s.outlet.name.indexOf(s.brand.name) === 0 ? s.outlet.name.slice(s.brand.name.length).replace(/^[\s-]+/, '') : s.outlet.name; }

  /* ---------------------------------------------------------------- page-level words */
  function drawFrame() {
    var strip = $('tablestrip');
    strip.hidden = !s.hasTableCode;
    if (s.hasTableCode) strip.textContent = t('table', { n: s.table }) + ' · ' + placeName();
    document.body.classList.toggle('at-table', s.hasTableCode);  // a guest at a table gets to the order button sooner
    var go = s.hasTableCode ? 'Order from table ' + s.table : 'See the menu';
    $('hero-go').textContent = go;
    $('nav-go').textContent = s.hasTableCode ? 'Order Now' : 'Menu';
    if (s.brand.tagline) $('tagline').textContent = s.brand.tagline;
    $('where').textContent = placeName() + ' · ' + s.outlet.city + ' · Brewed and published in Bombay';

    var box = $('lang');
    box.textContent = '';
    if (s.brand.langs.length > 1) {
      s.brand.langs.forEach(function (l) {
        box.appendChild(h('button', { type: 'button', 'data-lang': l, 'aria-pressed': String(l === I.lang()), lang: l, text: I.NAMES[l] || l }));
      });
    }
    var n = $('notice');
    var message = !s.outlet.accepting ? t('closed') : !s.hasTableCode ? t('scan_qr') : '';
    n.hidden = !message;
    n.textContent = message;
  }

  /* ---------------------------------------------------------------- menu */
  function drawTabs() {
    var box = $('tabs');
    box.textContent = '';
    [{ slug: 'all', names: null }].concat(s.categories).forEach(function (c) {
      box.appendChild(h('button', { class: 'tab', type: 'button', 'data-tab': c.slug, 'aria-pressed': String(c.slug === tab), text: c.names ? I.pick(c.names) : t('everything') }));
    });
  }

  function stepper(id, qty, name) {
    return h('span', { class: 'stepper' }, [
      h('button', { type: 'button', 'data-act': 'dec', 'data-id': id, 'aria-label': '-1 ' + name, text: '-' }),
      h('output', { 'aria-label': name, text: String(qty) }),
      h('button', { type: 'button', 'data-act': 'inc', 'data-id': id, 'aria-label': '+1 ' + name, text: '+' })
    ]);
  }

  function dishCard(it) {
    var name = I.pick(it.names), q = s.qty(it.id);
    var title = h('h3', {}, [h('span', { class: 'veg' + (it.veg ? '' : ' non'), role: 'img', 'aria-label': it.veg ? 'Vegetarian' : 'Non-vegetarian' })]);
    title.appendChild(document.createTextNode(name));
    if (it.tag) title.appendChild(h('span', { class: 'tag', text: it.tag }));
    var control = !it.available ? h('button', { class: 'add', type: 'button', disabled: true, text: t('unavailable') })
      : q === 0 ? h('button', { class: 'add', type: 'button', 'data-act': 'inc', 'data-id': it.id, 'aria-label': t('add') + ' ' + name, text: t('add') })
        : stepper(it.id, q, name);
    var desc = I.pick(it.descs);
    return h('article', { class: 'dish' + (q ? ' in' : '') + (it.available ? '' : ' off'), 'data-id': it.id }, [
      title, desc ? h('p', { class: 'desc', text: desc }) : h('p', { class: 'desc' }),
      h('div', { class: 'row' }, [h('span', { class: 'price', text: money(it.price) }), control])
    ]);
  }

  function drawDishes() {
    var box = $('dishes');
    box.textContent = '';
    s.categories.forEach(function (c) {
      if (!c.items.length || (tab !== 'all' && tab !== c.slug)) return;
      box.appendChild(h('h3', { class: 'cat', text: I.pick(c.names) }));
      c.items.forEach(function (it) { box.appendChild(dishCard(it)); });
    });
    if (!box.firstChild) box.appendChild(h('p', { class: 'note', text: 'The menu is being written. Please ask our staff.' }));
  }

  /* ---------------------------------------------------------------- ticket */
  function seg(kind, options) {
    return h('div', { class: 'seg' }, options.map(function (o) {
      return h('button', { type: 'button', 'data-act': kind, 'data-v': o, 'aria-pressed': String(o === prefs[kind]), text: t(o) });
    }));
  }
  function textBox(id, label, value, max, placeholder, save) {
    var input = h('input', { type: 'text', id: id, maxlength: String(max), placeholder: placeholder || '', 'aria-label': label });
    input.value = value;
    input.addEventListener('input', function () { save(input.value); });
    return h('fieldset', {}, [h('legend', { text: label }), input]);
  }

  function drawTicket() {
    var n = s.count(), inn = h('div', { class: 'slip-in' });
    inn.appendChild(h('h2', { text: t('ticket') }));
    inn.appendChild(h('p', { class: 'sub', text: n ? t(n === 1 ? 'item_one' : 'item_many', { n: n }) : t('empty_sub') }));
    if (n) {
      inn.appendChild(h('ul', { class: 'lines' }, s.lines().map(function (l) {
        var nm = I.pick(l.item.names);
        return h('li', {}, [h('span', { class: 'nm', text: nm }), h('span', { class: 'lp', text: money(l.item.price * l.qty) }), stepper(l.item.id, l.qty, nm)]);
      })));
      inn.appendChild(h('div', { class: 'total' }, [h('span', { text: t('total') }), h('span', { text: money(s.total()) })]));
    } else {
      inn.appendChild(h('p', { class: 'empty', text: t('nothing') }));
    }
    if (hasChai()) {
      inn.appendChild(h('fieldset', {}, [h('legend', { text: t('pref_head') + ': ' + t('strength') }), seg('strength', ['Halka', 'Normal', 'Kadak'])]));
      inn.appendChild(h('fieldset', {}, [h('legend', { text: t('sugar') }), seg('sugar', ['Kam', 'Normal', 'Zyada'])]));
    }
    if (n) {
      inn.appendChild(textBox('note', t('note_label'), note, 120, t('note_hint'), function (v) { note = v; }));
      inn.appendChild(textBox('who', t('name_opt'), guestName, 30, '', function (v) { guestName = v; store.write('qro_name', v); }));
    }
    if (error) inn.appendChild(h('p', { class: 'problem', role: 'alert', text: error }));
    var label = !n ? t('add_first') : !s.hasTableCode ? t('scan_first') : placing ? '...' : t('place_total', { total: money(s.total()) });
    var place = h('button', { class: 'btn place', type: 'button', 'data-act': 'place', text: label });
    if (!n || !s.canOrder || placing) place.disabled = true;
    inn.appendChild(place);
    inn.appendChild(h('p', { class: 'hint', text: t('no_payment') }));
    var box = $('cart');
    box.textContent = '';
    box.appendChild(h('section', { class: 'slip' }, [inn]));
  }

  function drawBar() {
    var n = s.count(), on = n > 0 && !$('shop').hidden;
    $('bar-text').textContent = n ? t(n === 1 ? 'item_one' : 'item_many', { n: n }) + ' - ' + money(s.total()) : '';
    $('bar-go').textContent = t('view_ticket');
    $('bar').classList.toggle('on', on);
    document.body.classList.toggle('has-bar', on);
  }

  function drawAll() { drawFrame(); drawTabs(); drawDishes(); drawTicket(); drawBar(); }

  /* ---------------------------------------------------------------- order received */
  function showDone(order) {
    var box = $('done'), tok = String(order.token).padStart(3, '0');
    $('shop').hidden = true;
    box.hidden = false;
    box.textContent = '';
    box.appendChild(h('span', { class: 'kick', text: t('token_table', { token: tok, n: order.table }) }));
    box.appendChild(h('h1', { text: order.status === 'cancelled' ? t('cancelled') : t('confirm_title') }));
    if (order.status !== 'cancelled') box.appendChild(h('p', { class: 'status', text: t('confirm_text', { n: order.table }) }));
    var inn = h('div', { class: 'slip-in' }, [h('h2', { text: t('slip') })]);
    inn.appendChild(h('ul', { class: 'lines' }, order.lines.map(function (l) {
      return h('li', {}, [h('span', { text: l.qty + ' x' }), h('span', { class: 'nm', text: I.pick(l.names) }), h('span', { class: 'lp', text: money(l.price * l.qty) })]);
    })));
    if (order.prefs) inn.appendChild(h('p', { class: 'hint', text: t('pref_head') + ': ' + t(order.prefs.strength) + ', ' + t('sugar') + ': ' + t(order.prefs.sugar) }));
    if (order.note) inn.appendChild(h('p', { class: 'hint', text: t('note_short') + ': ' + order.note }));
    inn.appendChild(h('div', { class: 'total' }, [h('span', { text: t('total') }), h('span', { text: money(order.total) })]));
    inn.appendChild(h('p', { class: 'hint', text: t('pay_counter') }));
    box.appendChild(h('section', { class: 'slip receipt' }, [inn]));
    box.appendChild(h('button', { class: 'btn again', type: 'button', 'data-act': 'again', text: t('more') }));
    drawBar();
    live(t('confirm_title'));
    $('menu').scrollIntoView();
  }

  async function place() {
    placing = true; error = ''; drawTicket();
    try {
      var order = await s.place({ name: guestName, note: note, prefs: hasChai() ? prefs : null });
      placing = false;
      if (!order) { drawTicket(); return; }
      note = '';
      drawDishes(); drawTicket();
      showDone(order);
    } catch (e) {
      placing = false;
      error = e.status && e.status < 500 ? e.message : t('err_place');
      drawAll();
    }
  }

  /* ---------------------------------------------------------------- events */
  document.addEventListener('click', function (e) {
    var el = e.target.closest ? e.target.closest('button[data-act],button[data-tab],button[data-lang]') : null;
    if (!el || !s) return;
    var act = el.getAttribute('data-act'), id = el.getAttribute('data-id'), v = el.getAttribute('data-v');
    var scope = el.closest('#cart') ? '#cart' : '#dishes';
    if (el.hasAttribute('data-lang')) {
      var l = el.getAttribute('data-lang'); I.setLang(l, s.brand.default_lang); store.write('qro_lang', l); document.documentElement.lang = l; drawAll(); return;
    }
    if (el.hasAttribute('data-tab')) { tab = el.getAttribute('data-tab'); drawTabs(); drawDishes(); return; }
    if (act === 'inc' || act === 'dec') {
      s.change(Number(id), act === 'inc' ? 1 : -1); error = '';
      drawDishes(); drawTicket(); drawBar();
      live(t(act === 'inc' ? 'added' : 'removed', { name: I.pick(s.items[id].names) }) + '. ' + money(s.total()));
      var back = document.querySelector(scope + ' [data-act="' + act + '"][data-id="' + id + '"]') || document.querySelector(scope + ' [data-act="inc"][data-id="' + id + '"]');
      if (back) back.focus({ preventScroll: true });
    } else if (act === 'strength' || act === 'sugar') { prefs[act] = v; store.write('qro_prefs', prefs); drawTicket(); }
    else if (act === 'place') place();
    else if (act === 'again') { s.forgetOrder(); $('done').hidden = true; $('shop').hidden = false; drawBar(); $('menu').scrollIntoView(); }
  });

  async function boot() {
    try { s = await window.QROKit.open(); }
    catch (e) {
      $('dishes').textContent = '';
      $('dishes').appendChild(h('p', { class: 'note', text: e.status === 404 ? t('not_found') : 'We could not load the menu. Please ask our staff.' }));
      return;
    }
    var want = new URLSearchParams(location.search).get('lang') || store.read('qro_lang', null) || (navigator.language || 'en').slice(0, 2);
    I.setLang(s.brand.langs.indexOf(want) >= 0 ? want : s.brand.default_lang, s.brand.default_lang);
    drawAll();
    var last = await s.lastOrder();
    if (last) showDone(last);
  }

  boot();
})();

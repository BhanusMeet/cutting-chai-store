/* Kitchen display: live order board for one outlet. */
(function () {
  'use strict';

  var Q = window.QRO, h = Q.h, $ = Q.$, api = Q.api, session = Q.session;
  var slug = new URLSearchParams(location.search).get('outlet');
  var outlet = null, brandSlug = null, token = null;
  var orders = {}, servedToday = 0, es = null, state = 'connecting', soundOn = false, audio = null;
  var printer = { mode: 'ask', waiting: 0, oldest_wait: 0, gap: 0, order: 'fifo', detected: [], failed: 0 }, printed = [], notices = [], drawQueued = false;
  var panelOpen = false, paperWidth = 80, testNote = '';
  var streamKey = null, timers = [];
  var COLS = [['new', 'New'], ['preparing', 'Preparing'], ['ready', 'Ready to serve']];

  function say(m) { $('live').textContent = m; }

  /* ---- sound: a short two-tone chime made in the browser, no audio file */
  function enableSound() {
    try {
      audio = audio || new (window.AudioContext || window.webkitAudioContext)();
      if (audio.state === 'suspended') audio.resume();
      soundOn = true;
    } catch (e) { soundOn = false; }
  }
  function chime() {
    if (!soundOn || !audio) return;
    [[880, 0], [1175, 0.16]].forEach(function (n) {
      var o = audio.createOscillator(), g = audio.createGain(), t0 = audio.currentTime + n[1];
      o.type = 'square'; o.frequency.value = n[0];
      g.gain.setValueAtTime(0.0001, t0); g.gain.exponentialRampToValueAtTime(0.15, t0 + 0.02); g.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.28);
      o.connect(g); g.connect(audio.destination); o.start(t0); o.stop(t0 + 0.3);
    });
  }

  /* ---- boot and login */
  async function boot() {
    if (!slug) { $('app').appendChild(h('p', { style: 'padding:30px', text: 'Open this page from your restaurant link (kitchen.html?outlet=...).' })); return; }
    try {
      var info = await api('/api/outlet/' + slug);
      outlet = info.outlet; brandSlug = info.brand.slug;
    } catch (e) { $('app').appendChild(h('p', { style: 'padding:30px', text: 'Restaurant not found.' })); return; }
    document.title = 'Kitchen - ' + outlet.name;
    token = session.read('qro_tok_kitchen_' + slug);
    streamKey = session.read('qro_key_kitchen_' + slug);
    if (!token) { token = session.read('qro_tok_admin_' + brandSlug); streamKey = session.read('qro_key_admin_' + brandSlug); }
    if (token && streamKey) start(); else loginView();
  }

  function forget() {
    timers.forEach(clearInterval); timers = [];
    if (es) { es.close(); es = null; }
    ['qro_tok_kitchen_' + slug, 'qro_key_kitchen_' + slug, 'qro_tok_admin_' + brandSlug, 'qro_key_admin_' + brandSlug].forEach(session.drop);
    token = streamKey = null; orders = {}; printed = []; notices = [];
  }
  async function signOut() {
    try { await api('/api/logout', { method: 'POST', token: token, body: {} }); } catch (e) { /* already signed out */ }
    forget(); loginView('Signed out');
  }

  function loginView(msg) {
    var app = $('app');
    app.textContent = '';
    var pin = h('input', { type: 'password', inputmode: 'numeric', autocomplete: 'off', 'aria-label': 'Staff PIN', maxlength: '12' });
    var err = h('p', { class: 'err', role: 'alert', text: msg || '' });
    var go = async function () {
      try {
        var r = await api('/api/login', { method: 'POST', body: { scope: 'kitchen', slug: slug, pin: pin.value } });
        token = r.token; streamKey = r.stream_key; session.write('qro_tok_kitchen_' + slug, token); session.write('qro_key_kitchen_' + slug, streamKey); enableSound(); start();
      } catch (e) { err.textContent = e.message; pin.value = ''; pin.focus(); }
    };
    pin.addEventListener('keydown', function (e) { if (e.key === 'Enter') go(); });
    app.appendChild(h('div', { class: 'login' }, [
      h('h1', { text: 'Kitchen' }), h('p', { text: outlet.name }), err, pin,
      h('button', { class: 'btn big', type: 'button', style: 'width:100%', text: 'Open kitchen screen' })
    ]));
    app.querySelector('button').addEventListener('click', go);
    pin.focus();
  }

  async function start() {
    $('app').textContent = '';
    await refresh();
    connect();
    timers.push(setInterval(render, 15000)); // keeps the "minutes ago" labels fresh
    timers.push(setInterval(async function () {  // how long is this store's print queue right now?
      try {
        var next = await api('/api/kitchen/' + slug + '/printer', { token: token });
        var changed = signature(next) !== signature(printer);
        printer = next;
        if (changed) render(); else drawPrinterLine();
      }
      catch (e) { if (e.status === 401 || e.status === 403) { forget(); loginView('You were signed out. Please sign in again.'); } }
    }, 3000));
  }

  async function refresh() {
    try {
      var d = await api('/api/kitchen/' + slug + '/orders', { token: token });
      orders = {};
      d.orders.forEach(function (o) { orders[o.public_id] = o; });
      servedToday = d.served_today; outlet = d.outlet; printer = d.printer; printed = d.recent_slips;
      if (printer.mode === 'usb') paperWidth = printer.width;
      render();
    } catch (e) {
      if (e.status === 401 || e.status === 403) { forget(); loginView('Please sign in again'); }
    }
  }

  function connect() {
    if (es) es.close();
    es = Q.sse('/api/stream?outlet=' + encodeURIComponent(slug) + '&key=' + encodeURIComponent(streamKey), {
      order_new: function (o) { orders[o.public_id] = o; o._fresh = true; say('New order'); if (o.status === 'new') chime(); soon(); },
      slip: function (s) {  // a slip was released, printed or failed
        var at = printed.map(function (x) { return x.id; }).indexOf(s.id);
        var was = at >= 0 ? printed[at].status : 'queued';
        if (at >= 0) printed[at] = s; else { printed.unshift(s); printed = printed.slice(0, 8); }
        var o = orders[s.public_id];
        if (o && s.station === 'kitchen' && o.slips_waiting && (s.status === 'screen' || s.status === 'printed') && was !== s.status) o.slips_waiting--;
        if (at < 0 || s.status === 'failed') chime();
        soon();
      },
      order_update: function (o) {
        if (o.status === 'served') { servedToday++; delete orders[o.public_id]; }
        else if (o.status === 'cancelled') delete orders[o.public_id];
        else orders[o.public_id] = o;
        soon();
      }
    }, function (s) { var was = state; state = s; if (s === 'live' && was === 'reconnecting') refresh(); else render(); });
  }

  /* ---- drawing */
  function ago(sec) {
    var m = Math.floor((Date.now() / 1000 - sec) / 60);
    return m < 1 ? 'just now' : m + ' min ago';
  }

  function soon() {  // many events can arrive at once: redraw at most a few times a second
    if (drawQueued) return;
    drawQueued = true;
    setTimeout(function () { drawQueued = false; render(); }, 250);
  }

  function waited(w) { return w >= 60 ? Math.floor(w / 60) + ' min ' + (w % 60) + ' s' : w + ' s'; }
  function printerText() {
    if (printer.mode === 'none') return 'No print: orders show on this screen only';
    var pace = printer.gap > 0 ? '1 kitchen slip every ' + printer.gap + ' s' : 'no gap between slips';
    var head = printer.mode === 'usb' ? 'Printer: ' + printer.name + ' (' + printer.width + ' mm)' + (printer.problem ? '' : ' · ready')
      : 'No printer chosen: slips only show on this screen';
    return head + ' · ' + pace + ' · ' + (printer.order === 'small_first' ? 'small orders first' : 'first in, first out') +
      ' · waiting ' + printer.waiting + (printer.waiting ? ' · oldest ' + waited(printer.oldest_wait) : '');
  }
  function behind() { return printer.mode !== 'none' && !printer.problem && printer.oldest_wait > 120; }
  function drawPrinterLine() {
    var el = $('pline');
    if (!el) return;
    el.textContent = printerText() + (behind() ? ' · THE PRINTER IS FALLING BEHIND: use a shorter gap' : '');
    el.className = 'pline' + (behind() || (printer.mode === 'usb' && (printer.problem || printer.failed)) ? ' bad' : '');
  }
  function signature(p) { return JSON.stringify([p.mode, p.name, p.problem, p.stopped, p.failed, p.detected, p.without_driver]); }

  /* ---- printer actions */
  async function printerCall(method, path, body) {
    try { return await api('/api/kitchen/' + slug + path, { method: method, token: token, body: body || {} }); }
    catch (e) {
      if (e.status === 401 || e.status === 403) { forget(); loginView('Please sign in again'); } else alert(e.message);
      return null;
    }
  }
  async function choosePrinter(mode, name) {
    if (mode === 'none' && printer.mode === 'usb' && (printer.waiting || printer.failed) &&
        !confirm('Slips that are waiting or failed will NOT be printed. Turn printing off?')) return;
    var d = await printerCall('PUT', '/printer', mode === 'usb' ? { mode: mode, name: name, width: paperWidth } : { mode: mode });
    if (!d) return;
    printer = d; testNote = ''; panelOpen = mode === 'usb';
    await refresh();
  }
  async function testPrint() {
    testNote = 'Printing a test slip...'; render();
    var d = await printerCall('POST', '/printer/test');
    if (!d) { testNote = ''; return; }
    testNote = d.ok ? 'Test slip sent. Check the paper: all three languages should be readable.' : 'Test failed: ' + d.error;
    render();
  }
  async function printerStep(path) { if (await printerCall('POST', path)) await refresh(); }

  function button(label, cls, fn) {
    var b = h('button', { class: 'btn ' + cls, type: 'button', text: label });
    b.addEventListener('click', fn);
    return b;
  }
  function widthPicker() {
    var s = h('select', { 'aria-label': 'Paper width', style: 'width:auto' }, [h('option', { value: '80', text: '80 mm paper' }), h('option', { value: '58', text: '58 mm paper' })]);
    s.value = String(paperWidth);
    s.addEventListener('change', function () { paperWidth = Number(s.value); });
    return s;
  }
  function dismissed(name) { return (session.read('qro_notnow_' + slug) || '').split('\n').indexOf(name) >= 0; }
  function notNow(name) { session.write('qro_notnow_' + slug, (session.read('qro_notnow_' + slug) || '') + '\n' + name); render(); }

  /* The question that appears by itself when a USB printer is plugged in. Never shown with 'No print'. */
  function printerPrompt() {
    if (printer.mode === 'none') return null;
    var chosen = printer.detected.filter(function (p) { return p.name === printer.name; })[0];
    if (printer.mode === 'usb' && chosen && chosen.connected) return null;
    var found = printer.detected.filter(function (p) { return p.connected && p.name !== (printer.mode === 'usb' ? printer.name : null) && !dismissed(p.name); })[0];
    if (found) {
      return h('div', { class: 'ask', role: 'alert' }, [
        h('strong', { text: (printer.mode === 'usb' ? 'A different USB printer is connected: ' : 'USB printer found: ') + found.name + '. Use this printer?' }),
        widthPicker(),
        button('Use this printer', '', function () { choosePrinter('usb', found.name); }),
        button('No print', 'ghost', function () { choosePrinter('none'); }),
        button('Not now', 'ghost', function () { notNow(found.name); })
      ]);
    }
    if (printer.mode === 'ask' && printer.without_driver && !dismissed('(no driver)')) {
      return h('div', { class: 'ask', role: 'alert' }, [
        h('strong', { text: 'A USB printer is plugged in, but Windows has not set it up. Install the maker\'s driver on the store computer, then it will appear here.' }),
        button('No print', 'ghost', function () { choosePrinter('none'); }),
        button('Not now', 'ghost', function () { notNow('(no driver)'); })
      ]);
    }
    return null;
  }

  function printerTrouble() {
    if (printer.mode !== 'usb' || (!printer.problem && !printer.failed)) return null;
    var needsPerson = printer.stopped || printer.failed;
    var text = 'PRINTER PROBLEM: ' + (printer.problem || 'a slip did not print') + '. ' +
      (printer.failed ? printer.failed + ' slip(s) failed. Look at the paper before printing again. ' : '') +
      (needsPerson ? '' : 'Waiting slips will print by themselves once this is fixed.');
    return h('div', { class: 'alertline', role: 'alert' }, [h('span', { text: text }),
      needsPerson ? button('Try again', '', function () { printerStep('/printer/retry'); }) : null,
      printer.failed ? button('Clear failed slips', 'ghost', function () {
        if (confirm('Those slips will not be printed. Make sure the kitchen has the orders. Continue?')) printerStep('/printer/clear');
      }) : null]);
  }

  function printerPanel() {
    if (!panelOpen) return null;
    var box = h('section', { class: 'pbox', 'aria-label': 'Printer' }, [h('h2', { text: 'Printer' })]);
    if (!printer.supported) box.appendChild(h('p', { class: 'err', text: 'Printing works only when the store computer runs Windows.' }));
    if (printer.mode === 'none') box.appendChild(h('p', { text: 'No print is on: orders show on screen only and you will not be asked about printers.' }));
    else if (!printer.detected.length) box.appendChild(h('p', { text: 'No USB printer found on the store computer. Plug it in and switch it on. If it has never been used here, install its Windows driver first.' }));
    printer.detected.forEach(function (p) {
      var current = printer.mode === 'usb' && p.name === printer.name;
      box.appendChild(h('div', { class: 'inline' }, [h('b', { text: p.name }), h('span', { text: (p.connected ? (p.problem || 'connected') : 'not connected') + (current ? ' · in use' : '') }),
        button(current ? 'Save paper width' : 'Use this printer', '', function () { choosePrinter('usb', p.name); })]));
    });
    var row = h('div', { class: 'inline' }, [printer.detected.length ? widthPicker() : null,
      printer.mode === 'usb' ? button('Print test slip', 'ghost', testPrint) : null,
      printer.mode !== 'none' ? button('No print', 'ghost', function () { choosePrinter('none'); }) : null,
      printer.mode !== 'ask' ? button(printer.mode === 'none' ? 'Turn printing back on' : 'Stop using this printer', 'ghost', function () { session.drop('qro_notnow_' + slug); choosePrinter('ask'); }) : null,
      button('Close', 'ghost', function () { panelOpen = false; render(); })]);
    box.appendChild(row);
    if (testNote) box.appendChild(h('p', { role: 'status', text: testNote }));
    return box;
  }

  async function move(o, status) {
    var who = o.kind === 'takeaway' ? 'takeaway ' + o.name : 'table ' + o.table;
    if (status === 'cancelled') {
      var warn = (o.pay_method ? ' This order was PAID (' + o.pay_method + '): the money must be given back.' : '') +
        (o.kind === 'takeaway' ? '' : ' Their phone will NOT update, so please go and tell the table.');
      if (!confirm('Reject order ' + o.token + ' for ' + who + '?' + warn)) return;
    }
    try {
      var r = await api('/api/kitchen/' + slug + '/orders/' + o.public_id + '/status', { method: 'POST', token: token, body: { status: status } });
      if (status === 'cancelled') {
        notices.push(r.refund_due ? 'Order ' + o.token + ' rejected: GIVE THE MONEY BACK (' + r.pay_method + ') to ' + (o.name || 'table ' + o.table) +
              (r.phone_last4 ? ' (phone ending ' + r.phone_last4 + ')' : '') + '. Then press "Money returned" under Bills on the Counter screen.'
          : o.kind === 'dine_in' ? 'Order ' + o.token + ' rejected: go and tell table ' + o.table : 'Order ' + o.token + ' rejected: tell ' + o.name);
        render();
      }
    } catch (e) { alert(e.message); refresh(); }
  }

  async function setAuto(on) {
    try { await api('/api/kitchen/' + slug + '/settings', { method: 'PUT', token: token, body: { auto_accept: on } }); outlet.auto_accept = on; render(); }
    catch (e) { alert(e.message); }
  }

  var SLIP_STATE = { screen: 'on screen only', queued: 'waiting', sending: 'printing...', printed: 'printed', failed: 'FAILED' };
  function printedPanel() {
    if (printer.mode === 'none') return null;
    var row = h('div', { class: 'slips' });
    printed.forEach(function (s) {
      var again = printer.mode === 'usb' && (s.status === 'printed' || s.status === 'failed' || s.status === 'screen');
      row.appendChild(h('div', { class: 'paper ' + s.station }, [
        h('b', { text: (s.station === 'counter' ? 'COUNTER' : 'KITCHEN') + '  #' + String(s.token).padStart(3, '0') }),
        h('div', { text: s.kind === 'takeaway' ? 'TAKEAWAY - ' + s.name : 'TABLE ' + s.table })
      ].concat(s.items.map(function (i) { return h('div', { text: i.qty + ' x ' + i.name }); }), [
        h('div', { class: 'pstate ' + s.status, text: SLIP_STATE[s.status] || s.status }),
        again ? button('Reprint', 'ghost', function () { printerStep('/slips/' + s.id + '/reprint'); }) : null
      ])));
    });
    var title = printer.mode === 'usb' ? 'Latest slips' : 'Slip preview on screen (no printer chosen)';
    return h('section', { class: 'tester', 'aria-label': 'Slips' }, [h('div', { class: 'cap', text: title }), row]);
  }

  function ticket(o) {
    var lines = h('ul', {}, o.lines.map(function (l) { return h('li', {}, [h('b', { text: l.qty + 'x' }), document.createTextNode(l.kitchen_name)]); }));
    var acts = h('div', { class: 'acts' });
    var add = function (label, status, cls) {
      var b = h('button', { class: 'btn ' + (cls || ''), type: 'button', text: label });
      b.addEventListener('click', function () { move(o, status); });
      acts.appendChild(b);
    };
    if (o.status === 'new') { add('Accept', 'preparing'); add('Reject', 'cancelled', 'red'); }
    if (o.status === 'preparing') { add('Mark ready', 'ready'); add('Reject', 'cancelled', 'red'); }
    if (o.status === 'ready') add(o.kind === 'takeaway' ? 'Collected' : 'Served to table', 'served');
    return h('article', { class: 'ticket' + (o._fresh && o.status === 'new' ? ' fresh' : '') }, [
      h('div', { class: 'top' }, [h('span', { class: 'no', text: '#' + String(o.token).padStart(3, '0') }), h('span', { class: 'tbl' + (o.kind === 'takeaway' ? ' take' : ''), text: o.kind === 'takeaway' ? 'TAKEAWAY' : 'TABLE ' + o.table })]),
      h('div', { class: 'meta', text: ago(o.created_at) + (o.name ? ' · ' + o.name : '') + (o.pay_method ? ' · PAID ' + o.pay_method.toUpperCase() : '') + (o.phone_last4 ? ' · phone ..' + o.phone_last4 : '') }),
      o.slips_waiting ? h('div', { class: 'waiting', text: 'Slip waiting in the print queue' }) : null,
      lines,
      o.prefs ? h('div', { class: 'pref', text: 'Chai: ' + o.prefs.strength + ' strength, ' + o.prefs.sugar + ' sugar' }) : null,
      o.note ? h('div', { class: 'note', text: 'Note: ' + o.note }) : null,
      acts
    ]);
  }

  function outButton() {
    var b = h('button', { class: 'btn ghost', type: 'button', text: 'Sign out' });
    b.addEventListener('click', signOut);
    return b;
  }

  function autoButton() {
    var b = h('button', { class: 'tog off', type: 'button', 'aria-pressed': String(outlet.auto_accept), text: outlet.auto_accept ? 'Auto-accept ON' : 'Auto-accept OFF' });
    b.addEventListener('click', function () { setAuto(!outlet.auto_accept); });
    return b;
  }

  function render() {
    if (!outlet || !token) return;
    var app = $('app');
    if (app.querySelector('.login')) return;
    app.textContent = '';
    var dot = h('span', { class: 'dot ' + (state === 'live' ? 'live' : state === 'reconnecting' ? 'bad' : '') });
    var snd = h('button', { class: 'btn ghost', type: 'button', text: soundOn ? 'Sound on' : 'Sound off - tap to enable' });
    snd.addEventListener('click', function () { if (soundOn) soundOn = false; else { enableSound(); chime(); } render(); });
    var open = Object.keys(orders).length;
    app.appendChild(h('div', { class: 'bar' }, [
      h('h1', { text: 'Kitchen · ' + outlet.name }),
      h('span', { class: 'stat' }, [dot, document.createTextNode(state === 'live' ? 'Live' : state === 'reconnecting' ? 'Reconnecting...' : 'Connecting...')]),
      h('span', { class: 'grow' }),
      h('span', { class: 'stat' }, [document.createTextNode('Open '), h('b', { text: String(open) })]),
      h('span', { class: 'stat' }, [document.createTextNode('Served today '), h('b', { text: String(servedToday) })]),
      outlet.accepting ? null : h('span', { class: 'err', text: 'NOT ACCEPTING ORDERS' }),
      autoButton(),
      snd,
      button('Printer', 'ghost', function () { panelOpen = !panelOpen; testNote = ''; render(); }),
      h('a', { class: 'btn ghost', href: '/counter.html?outlet=' + slug, text: 'Counter' }),
      outButton()
    ]));
    app.appendChild(h('div', { id: 'pline', class: 'pline' }));
    drawPrinterLine();
    [printerPrompt(), printerTrouble(), printerPanel()].forEach(function (el) { if (el) app.appendChild(el); });
    notices.forEach(function (text, i) {
      var ok = h('button', { class: 'btn ghost', type: 'button', text: 'Done' });
      ok.addEventListener('click', function () { notices.splice(i, 1); render(); });
      app.appendChild(h('div', { class: 'alertline', role: 'alert' }, [h('span', { text: text }), ok]));
    });
    var slips = printedPanel();
    if (slips) app.appendChild(slips);
    var board = h('div', { class: 'board' });
    COLS.forEach(function (c) {
      var list = Object.keys(orders).map(function (k) { return orders[k]; }).filter(function (o) { return o.status === c[0]; }).sort(function (a, b) { return a.created_at - b.created_at; });
      var col = h('section', { class: 'col ' + c[0], 'aria-label': c[1] }, [h('h2', {}, [h('span', { text: c[1] }), h('span', { text: String(list.length) })])]);
      if (!list.length) col.appendChild(h('p', { class: 'none', text: 'Nothing here' }));
      list.forEach(function (o) { col.appendChild(ticket(o)); });
      board.appendChild(col);
    });
    app.appendChild(board);
  }

  boot();
})();

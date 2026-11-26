/* Staff home: links to the screens of each outlet. Sends a brand-new store to first-time setup. */
(function () {
  'use strict';
  var Q = window.QRO, h = Q.h, $ = Q.$, api = Q.api;
  function link(label, href, main) { return h('a', { class: 'btn' + (main ? '' : ' ghost'), href: href, text: label }); }
  async function boot() {
    var box = $('list');
    try {
      var s = await api('/api/store');
      if (s.setup_needed) { location.replace('/setup.html'); return; }
      $('name').textContent = s.name;
      document.title = s.name + ' - staff home';
      box.textContent = '';
      box.appendChild(h('div', { class: 'brandbox' }, [h('h3', { text: 'Owner' }), h('div', { class: 'outlet' }, [
        h('span', { class: 'nm', text: 'Menu, prices, table QR codes, security, backups' }), link('Owner panel', '/admin.html?brand=' + s.brand, true)])]));
      s.outlets.forEach(function (o) {
        box.appendChild(h('div', { class: 'brandbox' }, [h('h3', { text: o.name }), h('div', { class: 'outlet' }, [
          h('span', { class: 'nm', text: 'Staff screens' }), link('Kitchen screen', '/kitchen.html?outlet=' + o.slug, true),
          link('Counter', '/counter.html?outlet=' + o.slug, true), link('Token board', '/board.html?outlet=' + o.slug)])]));
      });
    } catch (e) { box.textContent = 'Could not reach the store server: ' + e.message; }
  }
  boot();
})();

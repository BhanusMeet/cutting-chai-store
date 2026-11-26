/* Token board at the counter: one screen per outlet replaces a live connection on every takeaway phone.
   It is public, so it only ever receives token numbers: no names, no phone numbers. */
(function () {
  'use strict';
  var Q = window.QRO, h = Q.h, $ = Q.$, api = Q.api;
  var slug = new URLSearchParams(location.search).get('outlet');
  var tokens = {}, was = 'connecting';

  function draw() {
    ['preparing', 'ready'].forEach(function (col) {
      var box = $(col);
      box.textContent = '';
      Object.keys(tokens).map(Number).sort(function (a, b) { return a - b; }).forEach(function (n) {
        if ((tokens[n] === 'ready') === (col === 'ready')) box.appendChild(h('span', { text: String(n).padStart(3, '0') }));
      });
    });
  }

  async function load() {
    try {
      var d = await api('/api/board/' + slug);
      $('title').textContent = 'Takeaway tokens · ' + d.name;
      tokens = {};
      d.orders.forEach(function (o) { tokens[o.token] = o.status; });
      draw();
    } catch (e) { $('title').textContent = 'Open this page as board.html?outlet=...'; }
  }

  load();
  Q.sse('/api/stream?board=' + encodeURIComponent(slug || ''), {
    board: function (o) {
      if (o.status === 'served' || o.status === 'cancelled') delete tokens[o.token]; else tokens[o.token] = o.status;
      draw();
    }
  }, function (s) {
    $('state').textContent = s === 'live' ? 'Live' : 'Reconnecting...';
    if (s === 'live' && was === 'reconnecting') load();  // catch up on anything missed while disconnected
    was = s;
  });
})();

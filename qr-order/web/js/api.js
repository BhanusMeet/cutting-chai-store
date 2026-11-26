/* Small shared helpers: DOM builder, fetch wrapper, live-update (SSE) wrapper, safe storage. */
(function () {
  'use strict';

  // Builds DOM nodes. Text always goes in as textContent, never as HTML.
  function h(tag, attrs, kids) {
    var e = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      var v = attrs[k];
      if (v === null || v === undefined || v === false) return;
      if (k === 'text') e.textContent = v;
      else if (k === 'class') e.className = v;
      else e.setAttribute(k, v === true ? '' : v);
    });
    (kids || []).forEach(function (c) { if (c) e.appendChild(c); });
    return e;
  }

  // For fixed, trusted SVG markup written in our own code (never user data).
  function svg(markup) {
    var t = document.createElement('template');
    t.innerHTML = markup.trim();
    return t.content.firstChild;
  }

  function $(id) { return document.getElementById(id); }

  async function api(path, opts) {
    opts = opts || {};
    var headers = {};
    var init = { method: opts.method || 'GET', headers: headers };
    if (opts.body !== undefined) {
      headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(opts.body);
    }
    if (opts.token) headers['Authorization'] = 'Bearer ' + opts.token;
    var res = await fetch(path, init);
    var data = {};
    try { data = await res.json(); } catch (e) { /* empty body */ }
    if (!res.ok) {
      var err = new Error(data.error || 'Request failed');
      err.status = res.status;
      throw err;
    }
    return data;
  }

  // EventSource with named handlers. The browser reconnects on its own.
  function sse(url, handlers, onState) {
    var es = new EventSource(url);
    Object.keys(handlers).forEach(function (name) {
      es.addEventListener(name, function (e) {
        try { handlers[name](JSON.parse(e.data)); } catch (err) { /* ignore bad frame */ }
      });
    });
    es.onopen = function () { if (onState) onState('live'); };
    es.onerror = function () { if (onState) onState('reconnecting'); };
    return es;
  }

  var store = {
    read: function (k, fallback) {
      try { var v = localStorage.getItem(k); return v ? JSON.parse(v) : fallback; } catch (e) { return fallback; }
    },
    write: function (k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* private mode */ } },
    drop: function (k) { try { localStorage.removeItem(k); } catch (e) { /* ignore */ } }
  };
  var session = {
    read: function (k) { try { return sessionStorage.getItem(k); } catch (e) { return null; } },
    write: function (k, v) { try { sessionStorage.setItem(k, v); } catch (e) { /* ignore */ } },
    drop: function (k) { try { sessionStorage.removeItem(k); } catch (e) { /* ignore */ } }
  };

  window.QRO = { h: h, svg: svg, $: $, api: api, sse: sse, store: store, session: session };
})();

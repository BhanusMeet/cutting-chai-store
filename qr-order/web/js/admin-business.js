/* Owner panel: stock, dish costs, and money reports with Excel order sheets. */
(function () {
  'use strict';

  var Q = window.QRO, h = Q.h, api = Q.api;
  var cache = {};            // data for the open tab, by name
  var period = null, reportOutlet = 'one', openDish = null;

  function drop() { cache = {}; openDish = null; }

  function load(ctx, pane, name, path, draw) {
    var key = name + '|' + path;
    if (cache[key]) { draw(cache[key]); return; }
    pane.appendChild(h('p', { class: 'hint', text: 'Loading...' }));
    ctx.call(path).then(function (d) { cache = {}; cache[key] = d; ctx.render(); }).catch(function (e) { ctx.toast(e.message); });
  }

  function button(label, cls, fn) {
    var b = h('button', { class: 'btn ' + cls, type: 'button', text: label });
    b.addEventListener('click', async function () { b.disabled = true; try { await fn(); } catch (e) { alert(e.message); } b.disabled = false; });
    return b;
  }
  function numberBox(label, value, width) {
    var i = h('input', { type: 'number', min: '0', step: 'any', 'aria-label': label, placeholder: label, style: 'width:' + (width || 110) + 'px' });
    if (value !== undefined && value !== null) i.value = String(value);
    return i;
  }
  function need(input, what) {
    if (input.value.trim() === '' || !isFinite(Number(input.value))) throw new Error('Enter ' + what);
    return Number(input.value);
  }
  function table(heads, rows) {
    var t = h('table', { class: 't' }, [h('tr', {}, heads.map(function (x) { return h('th', { text: x }); }))]);
    rows.forEach(function (r) {
      t.appendChild(h('tr', {}, r.map(function (c) { return typeof c === 'string' || typeof c === 'number' ? h('td', { text: String(c) }) : h('td', {}, [c]); })));
    });
    return h('div', { class: 'scroll' }, [t]);
  }
  function round(v) { return Math.round(v * 1000) / 1000; }

  /* ------------------------------------------------------------ stock */
  function stock(pane, ctx) {
    var o = ctx.outlet(), q = '?outlet=' + o.slug;
    pane.appendChild(h('h2', { text: 'Stock at ' + o.name }));
    pane.appendChild(h('p', { class: 'hint', text: 'Stock goes down by itself with every order, using each dish\'s ingredient list (tab "Dish costs"). Record what you buy and throw away, and count the shelf now and then.' }));
    load(ctx, pane, 'stock', '/stock' + q, function (d) {
      var again = async function (msg) { drop(); ctx.toast(msg); ctx.render(); };
      var name = h('input', { type: 'text', maxlength: '60', placeholder: 'Ingredient, e.g. Milk', 'aria-label': 'New ingredient name', style: 'max-width:260px' });
      var unit = h('select', { 'aria-label': 'Unit', style: 'width:auto' }, [h('option', { value: 'g', text: 'grams (g)' }), h('option', { value: 'ml', text: 'millilitres (ml)' }), h('option', { value: 'pcs', text: 'pieces (pcs)' })]);
      pane.appendChild(h('div', { class: 'inline' }, [name, unit, button('+ Add ingredient', '', async function () {
        await ctx.call('/ingredients', { method: 'POST', body: { name: name.value, unit: unit.value } }); await again('Added');
      })]));
      if (!d.ingredients.length) { pane.appendChild(h('p', { class: 'hint', text: 'No ingredients yet. Start with the few that cost you the most: milk, tea leaf, sugar, bread.' })); return; }

      var low = d.ingredients.filter(function (i) { return i.status !== 'OK' && (i.low_at > 0 || i.quantity < 0); });
      if (low.length) pane.appendChild(h('p', { class: 'err', role: 'alert', text: 'Buy soon: ' + low.map(function (i) { return i.name + ' (' + round(i.quantity) + ' ' + i.unit + ')'; }).join(', ') }));

      d.ingredients.forEach(function (i) {
        var buyQty = numberBox('Quantity bought (' + i.unit + ')', null, 190), buyPaid = numberBox('Total paid', null, 120);
        var other = numberBox('Quantity (' + i.unit + ')', null, 140);
        var lowAt = numberBox('Warn at (' + i.unit + ')', i.low_at || null, 130);
        var price = numberBox('Price', null, 90), per = numberBox('for how many ' + i.unit, null, 160);
        var move = async function (body, msg) { body.ingredient_id = i.id; await ctx.call('/stock' + q, { method: 'POST', body: body }); await again(msg); };
        pane.appendChild(h('details', { class: 'stockrow' }, [
          h('summary', {}, [h('b', { text: i.name }), h('span', { text: round(i.quantity) + ' ' + i.unit }),
            h('span', { class: 'tag ' + i.status, text: i.status === 'OK' ? 'OK' : i.status }),
            h('span', { class: 'muted', text: i.cost === null ? 'cost not set' : 'worth ' + ctx.money(i.value) })]),
          h('div', { class: 'inline' }, [h('span', { text: 'Bought:' }), buyQty, buyPaid, button('Add purchase', '', function () {
            var body = { action: 'purchase', qty: need(buyQty, 'the quantity bought') };
            if (buyPaid.value.trim() !== '') body.paid = need(buyPaid, 'the total paid');
            return move(body, 'Purchase recorded');
          })]),
          h('div', { class: 'inline' }, [h('span', { text: 'Shelf:' }), other,
            button('Thrown away', 'ghost', function () { return move({ action: 'waste', qty: need(other, 'how much was thrown away') }, 'Waste recorded'); }),
            button('I counted this much', 'ghost', function () { return move({ action: 'count', qty: need(other, 'what you counted') }, 'Stock corrected'); })]),
          h('div', { class: 'inline' }, [h('span', { text: 'Low-stock warning:' }), lowAt, button('Save warning', 'ghost', async function () {
            await ctx.call('/stock' + q, { method: 'PUT', body: { ingredient_id: i.id, low_at: need(lowAt, 'the warning level') } }); await again('Saved');
          })]),
          h('div', { class: 'inline' }, [h('span', { text: i.cost === null ? 'Set cost:' : 'Cost now ' + ctx.money(round(i.cost * (i.unit === 'pcs' ? 1 : 1000))) + (i.unit === 'pcs' ? ' each' : ' per 1000 ' + i.unit) + '. Change:' }),
            price, per, button('Save cost', 'ghost', async function () {
              await ctx.call('/stock' + q, { method: 'PUT', body: { ingredient_id: i.id, price: need(price, 'the price'), per: need(per, 'how much that price buys') } }); await again('Cost saved');
            })]),
          h('div', { class: 'inline' }, [button('Remove ingredient', 'red', async function () {
            if (!confirm('Remove ' + i.name + ' from the list?')) return;
            await ctx.call('/ingredients/' + i.id, { method: 'PUT', body: { archived: true } }); await again('Removed');
          })])
        ]));
      });
      pane.appendChild(h('h3', { style: 'margin-top:24px', text: 'Latest stock changes' }));
      var words = { sale: 'sold', cancel: 'order rejected, put back', purchase: 'bought', waste: 'thrown away', count: 'count correction' };
      pane.appendChild(table(['When', 'Ingredient', 'Change', 'Why', 'Note'], d.moves.map(function (m) {
        return [new Date(m.at * 1000).toLocaleString(), m.name, (m.change > 0 ? '+' : '') + round(m.change) + ' ' + m.unit,
          (words[m.kind] || m.kind) + (m.token ? ' (token ' + m.token + ')' : '') + (m.paid !== null ? ', paid ' + ctx.money(m.paid) : ''), m.note];
      })));
    });
  }

  /* ------------------------------------------------------------ dish costs (ingredient list of each dish) */
  function recipes(pane, ctx) {
    var o = ctx.outlet();
    pane.appendChild(h('h2', { text: 'Dish costs at ' + o.name }));
    pane.appendChild(h('p', { class: 'hint', text: 'For each dish, enter what ONE plate or glass uses. That gives its ingredient cost and margin, and takes the right amount out of stock. Ingredient lists are the same at every outlet. Changes apply to new orders only.' }));
    load(ctx, pane, 'recipes', '/stock?outlet=' + o.slug, function (d) {
      if (!d.ingredients.length) { pane.appendChild(h('p', { class: 'err', text: 'First add ingredients in the Stock tab.' })); return; }
      var missing = d.dishes.filter(function (x) { return x.cost === null && x.price > 0; }).length;
      if (missing) pane.appendChild(h('p', { class: 'err', text: missing + ' dish(es) have no known cost. Their sales are left OUT of the margin in reports.' }));
      d.dishes.forEach(function (dish) {
        var summary = h('summary', {}, [h('b', { text: dish.name }), h('span', { text: 'sells ' + ctx.money(dish.price) }),
          h('span', { class: 'muted', text: dish.cost === null ? (dish.recipe.length ? 'an ingredient has no cost yet' : 'no ingredient list') : 'costs ' + ctx.money(dish.cost) + ', margin ' + ctx.money(dish.margin) })]);
        var box = h('details', { class: 'stockrow' }, [summary]);
        if (openDish === dish.id) box.open = true;
        box.addEventListener('toggle', function () { if (box.open) openDish = dish.id; else if (openDish === dish.id) openDish = null; });
        var lines = h('div', {}), rows = [];
        var addRow = function (part) {
          var pick = h('select', { 'aria-label': 'Ingredient', style: 'width:auto' }, d.ingredients.map(function (i) { return h('option', { value: String(i.id), text: i.name + ' (' + i.unit + ')' }); }));
          if (part) pick.value = String(part.id);
          var qty = numberBox('Quantity per plate', part ? part.qty : null, 160);
          var row = { pick: pick, qty: qty, gone: false };
          var el = h('div', { class: 'inline' }, [pick, qty, button('Remove', 'ghost', function () { row.gone = true; el.remove(); })]);
          rows.push(row); lines.appendChild(el);
        };
        dish.recipe.forEach(addRow);
        box.appendChild(lines);
        box.appendChild(h('div', { class: 'inline' }, [button('+ Ingredient', 'ghost', function () { addRow(null); }), button('Save', '', async function () {
          var parts = rows.filter(function (r) { return !r.gone; }).map(function (r) { return { id: Number(r.pick.value), qty: need(r.qty, 'every quantity') }; });
          await ctx.call('/recipes/' + dish.id, { method: 'PUT', body: { ingredients: parts } });
          drop(); ctx.toast('Saved'); ctx.render();
        })]));
        pane.appendChild(box);
      });
    });
  }

  /* ------------------------------------------------------------ money and Excel */
  function iso(date) { return date.getFullYear() + '-' + ('0' + (date.getMonth() + 1)).slice(-2) + '-' + ('0' + date.getDate()).slice(-2); }
  function preset(name) {
    var n = new Date(), y = n.getFullYear(), m = n.getMonth(), d = n.getDate();
    if (name === 'yesterday') return { from: iso(new Date(y, m, d - 1)), to: iso(new Date(y, m, d - 1)) };
    if (name === 'month') return { from: iso(new Date(y, m, 1)), to: iso(n) };
    if (name === 'lastmonth') return { from: iso(new Date(y, m - 1, 1)), to: iso(new Date(y, m, 0)) };
    return { from: iso(n), to: iso(n) };
  }

  async function download(ctx, path, fallback) {
    var res = await fetch('/api/admin/' + ctx.brandSlug + path, { headers: { Authorization: 'Bearer ' + ctx.token() } });
    if (!res.ok) throw new Error((await res.json()).error || 'Download failed');
    var url = URL.createObjectURL(await res.blob());
    var a = h('a', { href: url, download: (res.headers.get('Content-Disposition') || '').split('"')[1] || fallback });
    document.body.appendChild(a); a.click(); a.remove(); setTimeout(function () { URL.revokeObjectURL(url); }, 5000);
  }

  function reports(pane, ctx) {
    var o = ctx.outlet();
    if (!period) period = preset('today');
    pane.appendChild(h('h2', { text: 'Money and order sheets' }));
    var from = h('input', { type: 'date', 'aria-label': 'From date', style: 'width:auto' }), to = h('input', { type: 'date', 'aria-label': 'To date', style: 'width:auto' });
    from.value = period.from; to.value = period.to;
    var change = function () { period = { from: from.value, to: to.value || from.value }; drop(); ctx.render(); };
    from.addEventListener('change', change); to.addEventListener('change', change);
    var scope = h('select', { 'aria-label': 'Which outlet', style: 'width:auto' }, [h('option', { value: 'one', text: o.name }), h('option', { value: 'all', text: 'All outlets' })]);
    scope.value = reportOutlet;
    scope.addEventListener('change', function () { reportOutlet = scope.value; drop(); ctx.render(); });
    pane.appendChild(h('div', { class: 'inline' }, [['Today', 'today'], ['Yesterday', 'yesterday'], ['This month', 'month'], ['Last month', 'lastmonth']].map(function (p) {
      return button(p[0], 'ghost', function () { period = preset(p[1]); drop(); ctx.render(); });
    })));
    pane.appendChild(h('div', { class: 'inline' }, [from, h('span', { text: 'to' }), to, scope]));
    var query = '?from=' + period.from + '&to=' + period.to + '&outlet=' + (reportOutlet === 'all' ? 'all' : o.slug);

    var holder = h('div', {});
    pane.appendChild(holder);
    load(ctx, holder, 'report', '/report' + query, function (d) {
      var s = d.summary, m = function (v) { return v === null ? 'not known' : ctx.money(v); };
      var cards = h('div', { class: 'cards' });
      [['Sales', m(s.sales), s.orders + ' orders, ' + s.cancelled + ' rejected'],
        ['Not paid yet', m(s.unpaid), 'cash ' + m(s.paid_cash) + ' · UPI ' + m(s.paid_upi) + ' · card ' + m(s.paid_card) + (s.paid_online ? ' · online ' + m(s.paid_online) : '')],
        ['Gross margin', m(s.margin), s.margin_percent === null ? 'add ingredient lists and costs' : (s.margin_percent * 100).toFixed(1) + '% on ' + m(s.costed_sales) + ' of sales'],
        ['Stock', m(s.purchases) + ' bought', 'wasted or rejected food ' + m(s.waste_cost)]
      ].forEach(function (c) { cards.appendChild(h('div', { class: 'card' }, [h('h3', { text: c[0] }), h('div', { class: 'big', text: c[1] }), h('div', { class: 'sub', text: c[2] })])); });
      holder.appendChild(cards);
      if (s.uncosted_sales > 0) holder.appendChild(h('p', { class: 'err', text: 'The margin does NOT cover ' + m(s.uncosted_sales) + ' of sales, because those dishes had no known cost when sold.' }));
      if (s.refunds_due > 0) holder.appendChild(h('p', { class: 'err', text: m(s.refunds_due) + ' was paid for rejected orders and has not been marked as returned.' }));
      holder.appendChild(h('p', { class: 'hint', text: 'Gross margin is sales minus ingredient cost. It is NOT profit: rent, wages, gas, power and taxes are not taken out. Money is counted on the day of the order.' }));
      if (d.dishes.length) holder.appendChild(table(['Dish', 'Sold', 'Sales', 'Cost', 'Margin', 'Margin %'], d.dishes.map(function (x) {
        return [x.name, x.qty, m(x.sales), m(x.cost), m(x.margin), x.margin_percent === null ? (x.note || '-') : (x.margin_percent * 100).toFixed(1) + '%'];
      })));
    });

    pane.appendChild(h('h3', { style: 'margin-top:24px', text: 'Excel order sheet for these dates' }));
    var buttons = h('div', { class: 'inline' }, [button('Download (standard sheet)', '', function () { return download(ctx, '/sheet' + query + '&layout=default', 'orders.xlsx'); })]);
    pane.appendChild(buttons);
    pane.appendChild(h('p', { class: 'hint', text: 'The store also saves each finished day and month by itself in the data\\reports folder on the store computer, using your layout if you uploaded one.' }));

    pane.appendChild(h('h3', { style: 'margin-top:24px', text: 'Your own sheet layout' }));
    pane.appendChild(h('p', { class: 'hint', text: 'Download the starting layout, change it in Excel (move columns, add your logo colours, add totals), keep the {{...}} words where you want the figures, then upload it. Its last page lists every word you can use.' }));
    var layoutBox = h('div', {});
    pane.appendChild(layoutBox);
    var file = h('input', { type: 'file', accept: '.xlsx', 'aria-label': 'Your layout file (.xlsx)' });
    pane.appendChild(h('div', { class: 'inline' }, [button('Download starting layout', 'ghost', function () { return download(ctx, '/sheet/default-layout', 'order-sheet-layout.xlsx'); }), file,
      button('Upload my layout', '', async function () {
        var f = file.files[0];
        if (!f) throw new Error('Choose your .xlsx file first');
        if (f.size > 2 * 1024 * 1024) throw new Error('The file is larger than 2 MB');
        var res = await fetch('/api/admin/' + ctx.brandSlug + '/sheet/layout', { method: 'POST', headers: { Authorization: 'Bearer ' + ctx.token(), 'X-File-Name': encodeURIComponent(f.name) }, body: f });
        var data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Upload failed');
        ctx.toast('Your layout is saved'); ctx.render();
      })]));
    ctx.call('/sheet/layout').then(function (d) {
      if (!d.layout) { layoutBox.appendChild(h('p', { class: 'hint', text: 'No layout of your own yet.' })); return; }
      layoutBox.appendChild(h('p', { text: 'Your layout: ' + d.layout.name + ' (uploaded ' + new Date(d.layout.uploaded_at * 1000).toLocaleDateString() + ')' }));
      layoutBox.appendChild(h('div', { class: 'inline' }, [button('Download with my layout', '', function () { return download(ctx, '/sheet' + query + '&layout=mine', 'orders.xlsx'); }),
        button('Remove my layout', 'ghost', async function () { await ctx.call('/sheet/layout/remove', { method: 'POST', body: {} }); ctx.toast('Removed'); ctx.render(); })]));
    }).catch(function () { /* sign-in screen already shown */ });

    pane.appendChild(h('h3', { style: 'margin-top:24px', text: 'Correct a payment (' + o.name + ')' }));
    pane.appendChild(h('p', { class: 'hint', text: 'Staff mark bills as paid on the Counter screen and cannot undo it. If one was marked by mistake, undo it here. It is written to the activity log.' }));
    var pays = h('div', {});
    pane.appendChild(pays);
    pays.appendChild(button('Show the latest payments', 'ghost', async function () {
      var d = await ctx.call('/payments?outlet=' + o.slug);
      pays.textContent = '';
      if (!d.paid.length) { pays.appendChild(h('p', { class: 'hint', text: 'No payments yet.' })); return; }
      pays.appendChild(table(['Paid at', 'Token', 'Amount', 'How', ''], d.paid.map(function (p) {
        return [new Date(p.paid_at * 1000).toLocaleString(), p.token, ctx.money(p.total), p.pay_method, p.pay_method === 'online' ? '' : button('Undo', 'ghost', async function () {
          if (!confirm('Mark token ' + p.token + ' (' + ctx.money(p.total) + ') as NOT paid?')) return;
          await ctx.call('/payments/undo?outlet=' + o.slug, { method: 'POST', body: { order: p.public_id } });
          drop(); ctx.toast('Undone'); ctx.render();
        })];
      })));
    }));
  }

  window.QROBusiness = { stock: stock, recipes: recipes, reports: reports, drop: drop };
})();

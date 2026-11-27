/* First-time setup: the owner creates their own restaurant, password and staff PIN. */
(function () {
  'use strict';
  var Q = window.QRO, h = Q.h, $ = Q.$, api = Q.api;
  var fields = {};

  function field(form, id, label, attrs, hint) {
    var input = h('input', Object.assign({ id: id, type: 'text' }, attrs || {}));
    form.appendChild(h('label', { class: 'f', for: id, text: label }));
    form.appendChild(input);
    if (hint) form.appendChild(h('p', { class: 'hint', text: hint }));
    fields[id] = input;
    return input;
  }
  function check(form, id, label, on) {
    var box = h('input', { type: 'checkbox', id: id });
    box.checked = on;
    form.appendChild(h('p', { class: 'inline' }, [box, h('label', { for: id, text: label })]));
    fields[id] = box;
  }

  async function boot() {
    var s = await api('/api/store');
    if (!s.setup_needed) { location.replace('/'); return; }
    var f = $('form');
    field(f, 'code', 'Setup code', { autocomplete: 'off', maxlength: '20' }, 'Shown in the window where the server was started. It proves you control this computer.');
    field(f, 'restaurant', 'Restaurant name', { maxlength: '60' });
    field(f, 'tagline', 'Tagline (optional)', { maxlength: '80' });
    field(f, 'outlet', 'Outlet name (for example Malad)', { maxlength: '40' });
    field(f, 'city', 'City', { maxlength: '40' });
    field(f, 'tables', 'Number of tables', { type: 'number', min: '1', max: '200' });
    var theme = h('select', { id: 'theme' }, [h('option', { value: 'bombay', text: '1990s Bombay' }), h('option', { value: 'darbar', text: 'Royal darbar' })]);
    f.appendChild(h('label', { class: 'f', for: 'theme', text: 'Look of the guest menu' })); f.appendChild(theme); fields.theme = theme;
    check(f, 'hi', 'Offer Hindi', true);
    check(f, 'mr', 'Offer Marathi', true);
    check(f, 'takeaway', 'Also sell takeaway (leave off for a sit-down, dine-in restaurant)', false);
    check(f, 'starter', 'Start with the sample chai menu (the prices are placeholders: change every one before opening)', false);
    field(f, 'owner_password', 'Owner password (at least 10 characters)', { type: 'password', autocomplete: 'new-password', maxlength: '128' }, 'Three unrelated words and a number work well. Only the owner should know it.');
    field(f, 'owner_again', 'Owner password again', { type: 'password', autocomplete: 'new-password', maxlength: '128' });
    field(f, 'staff_pin', 'Staff PIN for kitchen and counter (6 to 12 digits)', { type: 'password', inputmode: 'numeric', autocomplete: 'new-password', maxlength: '12' });
    var err = h('p', { class: 'err', role: 'alert' });
    var go = h('button', { class: 'btn big', type: 'submit', text: 'Create my store' });
    f.appendChild(err); f.appendChild(go);

    f.addEventListener('submit', async function (e) {
      e.preventDefault();
      err.textContent = '';
      if (fields.owner_password.value !== fields.owner_again.value) { err.textContent = 'The two owner passwords do not match.'; return; }
      go.disabled = true;
      var langs = ['en'];
      if (fields.hi.checked) langs.push('hi');
      if (fields.mr.checked) langs.push('mr');
      try {
        var r = await api('/api/setup', { method: 'POST', body: {
          code: fields.code.value, restaurant: fields.restaurant.value, tagline: fields.tagline.value, outlet: fields.outlet.value, city: fields.city.value,
          tables: Number(fields.tables.value), theme: fields.theme.value, langs: langs, starter_menu: fields.starter.checked, takeaway: fields.takeaway.checked,
          owner_password: fields.owner_password.value, staff_pin: fields.staff_pin.value } });
        location.replace('/admin.html?brand=' + r.brand + '&outlet=' + r.outlet + '&tab=menu');
      } catch (x) { err.textContent = x.message; go.disabled = false; }
    });
    fields.code.focus();
  }
  boot();
})();

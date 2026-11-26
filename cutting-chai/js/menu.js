/*
 * CUTTING CHAI CO. - menu data and cafe settings.
 *
 * This is the ONLY file you edit to change the menu. Both the menu board on
 * the home page and the order page read from it.
 *
 *   id     unique, lowercase, no spaces (used by the cart)
 *   name   what the customer sees
 *   price  whole rupees (0 = free)
 *   desc   one short line (optional)
 *   tag    small label like "Bestseller" (optional)
 */
window.CAFE = {
  name: 'Cutting Chai Co.',
  tables: 12,                  // how many table numbers to show on the order page
  // Demo timing for the order tracker, in seconds since the order was placed:
  // [order received, kettle on, pouring, at your table]. For a real kitchen,
  // make these minutes (for example [0, 60, 240, 480]).
  stageSeconds: [0, 8, 18, 30]
};

window.MENU = {
  categories: [
    {
      id: 'chai', title: 'Chai', special: true,
      items: [
        { id: 'cutting-chai', name: 'Cutting Chai', price: 10, desc: 'Half a glass, a full kick.', tag: 'Bestseller' },
        { id: 'full-chai', name: 'Full Chai', price: 18, desc: 'The whole glass, no sharing.' },
        { id: 'masala-chai', name: 'Masala Chai', price: 15, desc: 'Crushed elaichi and a pinch of the house masala.' },
        { id: 'adrak-chai', name: 'Adrak Chai', price: 15, desc: 'Fresh ginger, strong leaf.' },
        { id: 'irani-chai', name: 'Irani Chai', price: 20, desc: 'Mawa-rich, slow simmered, Irani cafe style.' },
        { id: 'sulaimani', name: 'Sulaimani', price: 15, desc: 'Black tea, lemon and a hint of spice.' }
      ]
    },
    {
      id: 'saath', title: 'Chai ke Saath',
      items: [
        { id: 'bun-maska', name: 'Bun Maska', price: 18, desc: 'Soft bun, thick slab of butter.', tag: 'Dunk it' },
        { id: 'maska-pav', name: 'Maska Pav', price: 20, desc: 'Toasted pav, butter melting in.' },
        { id: 'khari', name: 'Khari Biscuit', price: 12, desc: 'Flaky and made for dipping.' },
        { id: 'osmania', name: 'Osmania Biscuit', price: 12, desc: 'Salty-sweet Hyderabadi classic.' },
        { id: 'toast-butter', name: 'Toast & Butter', price: 25, desc: 'Two slices, golden and crisp.' },
        { id: 'bhaji-pav', name: 'Bhaji Pav', price: 45, desc: 'Buttery mashed bhaji with pav.' }
      ]
    },
    {
      id: 'more', title: 'Aur Kuch',
      items: [
        { id: 'vada-pav', name: 'Vada Pav', price: 15, desc: 'The city’s own, with dry garlic chutney.', tag: 'Bombay classic' },
        { id: 'egg-bhurji-pav', name: 'Egg Bhurji Pav', price: 40, desc: 'Spiced scrambled eggs, buttered pav.' },
        { id: 'omelette-pav', name: 'Masala Omelette Pav', price: 40, desc: 'Onion, chilli and coriander.' },
        { id: 'cold-coffee', name: 'Cold Coffee', price: 35, desc: 'Thick, cold, sweet.' },
        { id: 'nimbu-soda', name: 'Nimbu Soda', price: 20, desc: 'Sweet, salty or both.' },
        { id: 'garam-paani', name: 'Garam Paani', price: 0, desc: 'Warm water, on the house.' }
      ]
    }
  ]
};

/* helpers shared by the pages */
window.rs = function (n) { return n === 0 ? 'Free' : 'Rs. ' + n; };

window.renderBoard = function (target) {
  var root = document.getElementById(target);
  if (!root) return;
  window.MENU.categories.forEach(function (cat) {
    var sec = document.createElement('section');
    if (cat.special) sec.className = 'special';
    var h = document.createElement('h4');
    h.id = 'm-' + cat.id;
    h.textContent = cat.title;
    sec.setAttribute('aria-labelledby', h.id);
    sec.appendChild(h);
    var ul = document.createElement('ul');
    cat.items.forEach(function (it) {
      var li = document.createElement('li');
      var left = document.createElement('span');
      left.className = 'txt';
      var n = document.createElement('span');
      n.className = 'n';
      n.textContent = it.name;
      left.appendChild(n);
      if (it.tag) {
        var t = document.createElement('span');
        t.className = 'tag';
        t.textContent = it.tag;
        left.appendChild(t);
      }
      if (it.desc) {
        var d = document.createElement('em');
        d.textContent = it.desc;
        left.appendChild(d);
      }
      var dots = document.createElement('span');
      dots.className = 'd';
      var p = document.createElement('span');
      p.className = 'p';
      p.textContent = window.rs(it.price);
      li.appendChild(left); li.appendChild(dots); li.appendChild(p);
      ul.appendChild(li);
    });
    sec.appendChild(ul);
    root.appendChild(sec);
  });
};

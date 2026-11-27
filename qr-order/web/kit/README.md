# Making a restaurant's own guest website

Every restaurant shares one backend. A restaurant can have its own guest website; the kitchen, counter
and owner screens stay the same for all.

## Where it goes

```
web/brands/<brand-slug>/index.html   (plus its own .css and .js)
```

`<brand-slug>` is the restaurant's name in lower case with dashes (shown in the owner panel address,
`admin.html?brand=<brand-slug>`). When that folder exists, the table QR codes of that restaurant open it.
Every other restaurant gets the standard menu (`web/customer.html`). Nothing else needs changing.
`web/brands/cutting-chai-co/` is the worked example.

## Start from this

```html
<script src="/js/api.js"></script>
<script src="/kit/guest.js"></script>
<script src="/brands/<brand-slug>/site.js"></script>
```

```js
const s = await QROKit.open();
s.brand;        // name, tagline, langs
s.outlet;       // name, city, currency, tables, accepting
s.categories;   // [{slug, names:{en,..}, items:[{id, names, descs, price, veg, tag, available}]}]
s.table;        // table number, or null when browsing without a valid table code
s.canOrder;     // false: show "scan the QR on your table"

s.change(itemId, +1);   s.qty(itemId);   s.lines();   s.count();   s.total();
const order = await s.place({ name, note, prefs: { strength: 'Kadak', sugar: 'Normal' } });  // prefs optional
await s.lastOrder();    s.forgetOrder();   await s.reloadMenu();
```

`place()` returns the saved order (`token`, `table`, `lines`, `total`, `note`). Show "order received"
only after it returns. If it throws, show `error.message` when `error.status` is below 500; otherwise
say the order was not confirmed and let the guest try again.

## Rules

- **Never decide prices, tax or permissions in a design.** The server does that and checks every order.
- Put no passwords or secret keys in these files: guests can read them all.
- No inline `<script>` and no `onclick="..."`: the security headers block them.
- Show names with `textContent`, never by building HTML from menu text.
- Only publish design files you have read. Their code runs on every guest's phone.

## What can still change

This kit and the addresses behind it are not yet versioned. If they change, check every restaurant's
design. Versioning belongs to the later online platform.

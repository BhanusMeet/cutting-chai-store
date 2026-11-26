/* Brand themes for the customer app. A brand picks one with its `theme` field.
   Each theme = fonts + a stylesheet + a little header decoration + a traveler
   drawing for the order tracker. Adding a theme means adding an entry here and
   a css/theme-<name>.css file. */
(function () {
  'use strict';
  var svg = window.QRO.svg, h = window.QRO.h;

  window.THEMES = {
    bombay: {
      fonts: 'https://fonts.googleapis.com/css2?family=Archivo+Black&family=Bebas+Neue&family=Oswald:wght@500;700&family=Courier+Prime:wght@400;700&family=Lora:ital,wght@0,400;0,700;1,400&family=Mukta:wght@400;700&family=Yatra+One&display=swap',
      css: '/css/theme-bombay.css',
      top: function () {
        var bar = h('div', { class: 'vhs', role: 'presentation' }, [
          h('span', { class: 'rec', text: 'REC' }), h('span', { text: 'PLAY ▶  SP' }), h('span', { text: '04:17 PM  12 NOV 1994' })
        ]);
        return [bar, h('div', { class: 'checker', 'aria-hidden': 'true' })];
      },
      headerExtra: function () { return null; },
      traveler: function () {
        return svg('<svg viewBox="0 0 120 64" role="img" aria-label="Kaali-Peeli taxi">' +
          '<polygon points="30,30 42,12 82,12 94,30" fill="#F4C430" stroke="#141414" stroke-width="3"/>' +
          '<polygon points="40,28 48,16 78,16 87,28" fill="#141414"/>' +
          '<rect x="50" y="3" width="22" height="9" fill="#141414"/><rect x="53" y="6" width="16" height="3" fill="#F4C430"/>' +
          '<rect x="6" y="30" width="108" height="12" fill="#F4C430" stroke="#141414" stroke-width="3"/>' +
          '<rect x="6" y="42" width="108" height="12" fill="#141414"/><rect x="108" y="33" width="6" height="6" fill="#FFF3D6"/>' +
          '<circle cx="28" cy="54" r="9" fill="#141414"/><circle cx="28" cy="54" r="3" fill="#FFF3D6"/>' +
          '<circle cx="92" cy="54" r="9" fill="#141414"/><circle cx="92" cy="54" r="3" fill="#FFF3D6"/></svg>');
      }
    },
    darbar: {
      fonts: 'https://fonts.googleapis.com/css2?family=Cinzel+Decorative:wght@400;700&family=Rozha+One&family=Yatra+One&family=Cormorant+Garamond:ital,wght@0,500;0,700;1,500&family=Tiro+Devanagari+Hindi&family=Tiro+Devanagari+Marathi&display=swap',
      css: '/css/theme-darbar.css',
      top: function () { return []; },
      headerExtra: function () {
        // jali lattice strip under the brand name
        return svg('<svg class="jali" aria-hidden="true" focusable="false" xmlns="http://www.w3.org/2000/svg"><defs>' +
          '<pattern id="jali" width="28" height="34" patternUnits="userSpaceOnUse"><rect width="28" height="34" fill="#1B365D"/>' +
          '<path d="M14 3 L26 17 L14 31 L2 17 Z" fill="none" stroke="#D4AF37" stroke-width="1.6"/>' +
          '<path d="M14 10 L20 17 L14 24 L8 17 Z" fill="none" stroke="#D4AF37" stroke-width="1.2"/><circle cx="14" cy="17" r="2.2" fill="#D4AF37"/>' +
          '<circle cx="0" cy="0" r="2" fill="#D4AF37"/><circle cx="28" cy="0" r="2" fill="#D4AF37"/><circle cx="0" cy="34" r="2" fill="#D4AF37"/><circle cx="28" cy="34" r="2" fill="#D4AF37"/></pattern></defs>' +
          '<rect width="100%" height="100%" fill="url(#jali)"/></svg>');
      },
      traveler: function () {
        // a small gilded chhatri (domed pavilion) carries the order to the table
        return svg('<svg viewBox="0 0 60 70" role="img" aria-label="Royal pavilion carrying your order">' +
          '<circle cx="30" cy="4" r="3" fill="#6E0D16"/><path d="M30 7 V12 M10 34 Q10 14 30 11 Q50 14 50 34 Z" fill="#D4AF37" stroke="#6E0D16" stroke-width="2"/>' +
          '<rect x="8" y="34" width="44" height="4" fill="#6E0D16"/><rect x="11" y="38" width="6" height="22" fill="#6E0D16"/>' +
          '<rect x="27" y="38" width="6" height="22" fill="#6E0D16"/><rect x="43" y="38" width="6" height="22" fill="#6E0D16"/>' +
          '<rect x="4" y="60" width="52" height="8" fill="#D4AF37" stroke="#6E0D16" stroke-width="2"/></svg>');
      }
    }
  };
})();

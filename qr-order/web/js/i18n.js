/* Languages for the customer app. Add a language by adding one object here (and
   a label in NAMES). Menu item names are translated separately, per item, in the
   admin panel. Hindi and Marathi below are first drafts: have a native speaker
   review them before showing a client in that language. */
(function () {
  'use strict';

  var NAMES = { en: 'English', hi: 'हिन्दी', mr: 'मराठी' };

  var S = {
    en: {
      order_at_table: 'Order at your table', table: 'Table {n}', pick_table: 'Pick your table', change_table: 'Change table',
      your_table: 'Your table no.', ticket: 'Your Ticket', nothing: 'Nothing on the ticket yet. Tap Add on a dish.',
      empty_sub: 'Empty', item_one: '{n} item', item_many: '{n} items', add: 'Add', everything: 'Everything',
      total: 'Total', place: 'Place order', place_total: 'Place order - {total}', add_first: 'Add something first',
      name_opt: 'Name (optional)', pref_head: 'Chai ka mizaaz', strength: 'Strength', sugar: 'Sugar',
      Halka: 'Light', Normal: 'Normal', Kadak: 'Strong', Kam: 'Less', Zyada: 'More',
      no_payment: 'No payment needed. Settle at the counter on your way out.',
      unavailable: 'Not available', free: 'Free', view_ticket: 'View ticket', language: 'Language',
      coming: 'Your order is coming right up to your table!', reached: 'Your order has reached your table!',
      cancelled: 'This order was cancelled. Please ask at the counter.',
      token_table: 'Token {token} - Table {n}', more: 'Order something more',
      closed: 'This restaurant is not taking orders right now.',
      st_new: 'Order received', st_preparing: 'Being prepared', st_ready: 'Ready, on its way', st_served: 'At your table',
      stop_new: 'Received', stop_preparing: 'Preparing', stop_ready: 'Ready', stop_served: 'At your table',
      slip: 'Order Slip', pay_counter: 'Pay at the counter. Keep this token number handy.',
      err_place: 'Could not place the order. Please try again.', no_link: 'This link has no restaurant in it.',
      not_found: 'We could not find this restaurant.', added: '{name} added', removed: '{name} removed',
      status_now: 'Your order: {s}', live: 'Live', reconnecting: 'Reconnecting',
      how_head: 'How would you like it?', dine_in: 'Dine in', takeaway: 'Takeaway', pickup_name: 'Your name (we call it out)', enter_name: 'Enter your name',
      token_takeaway: 'Token {token} - Takeaway', tk_coming: 'We are preparing your takeaway!', tk_ready: 'Your takeaway is ready. Please collect it at the counter.',
      tk_done: 'Collected. Thank you!', st_ready_tk: 'Ready for pickup', st_served_tk: 'Collected', stop_ready_tk: 'Ready for pickup', stop_served_tk: 'Collected',
      note_label: 'Special request (optional)', note_short: 'Request', note_hint: 'e.g. less spicy, no onion',
      scan_qr: 'To order, scan the QR code on your table. You can read the menu here.', scan_first: 'Scan your table QR to order',
      takeaway_counter: 'For takeaway, please order and pay at the counter.', phone: 'Mobile number', enter_phone: 'Enter your mobile number', pay_place: 'Pay online - {total}', pay_title: 'Test payment',
      pay_note: 'This is a test screen. No real money is taken.', pay_ok: 'Simulate successful payment', pay_fail: 'Simulate failed payment', pay_back: 'Back',
      pay_failed: 'The payment did not go through. Your order has not been sent.', pay_unavailable: 'Online payment is not set up yet. Please order at the counter.',
      counter_note: 'Your order goes to the kitchen after payment. Prefer to pay at the counter? Please order there.', phone_privacy: 'We use your number only for this order.',
      paid_online: 'Paid online. Keep this token number handy.', confirm_title: 'Order received!', confirm_text: 'We will bring it to table {n}.',
      eta_about: 'Ready in about {a}-{b} min', eta_left: 'estimate: {t} left', eta_late: 'It is taking a little longer than expected'
    },
    hi: {
      order_at_table: 'अपनी टेबल से ऑर्डर करें', table: 'टेबल {n}', pick_table: 'अपनी टेबल चुनें', change_table: 'टेबल बदलें',
      your_table: 'आपकी टेबल', ticket: 'आपका टिकट', nothing: 'टिकट में अभी कुछ नहीं है। किसी डिश पर ‘जोड़ें’ दबाएँ।',
      empty_sub: 'खाली', item_one: '{n} आइटम', item_many: '{n} आइटम', add: 'जोड़ें', everything: 'सब कुछ',
      total: 'कुल', place: 'ऑर्डर दें', place_total: 'ऑर्डर दें - {total}', add_first: 'पहले कुछ जोड़ें',
      name_opt: 'नाम (वैकल्पिक)', pref_head: 'चाय का मिज़ाज', strength: 'कड़कपन', sugar: 'चीनी',
      Halka: 'हल्की', Normal: 'सामान्य', Kadak: 'कड़क', Kam: 'कम', Zyada: 'ज़्यादा',
      no_payment: 'अभी भुगतान की ज़रूरत नहीं। जाते समय काउंटर पर चुकाएँ।',
      unavailable: 'उपलब्ध नहीं', free: 'मुफ़्त', view_ticket: 'टिकट देखें', language: 'भाषा',
      coming: 'आपका ऑर्डर बस आपकी टेबल पर आ रहा है!', reached: 'आपका ऑर्डर आपकी टेबल पर पहुँच गया!',
      cancelled: 'यह ऑर्डर रद्द हो गया। कृपया काउंटर पर पूछें।',
      token_table: 'टोकन {token} · टेबल {n}', more: 'और ऑर्डर करें',
      closed: 'यह रेस्टोरेंट अभी ऑर्डर नहीं ले रहा।',
      st_new: 'ऑर्डर मिल गया', st_preparing: 'तैयार हो रहा है', st_ready: 'तैयार है, आ रहा है', st_served: 'आपकी टेबल पर',
      stop_new: 'मिल गया', stop_preparing: 'तैयारी', stop_ready: 'तैयार', stop_served: 'आपकी टेबल पर',
      slip: 'ऑर्डर पर्ची', pay_counter: 'काउंटर पर भुगतान करें। टोकन नंबर संभालकर रखें।',
      err_place: 'ऑर्डर नहीं हो सका। कृपया फिर कोशिश करें।', no_link: 'इस लिंक में कोई रेस्टोरेंट नहीं है।',
      not_found: 'यह रेस्टोरेंट नहीं मिला।', added: '{name} जोड़ा गया', removed: '{name} हटाया गया',
      status_now: 'आपका ऑर्डर: {s}', live: 'लाइव', reconnecting: 'फिर से जुड़ रहे हैं',
      how_head: 'आप कैसे लेना चाहेंगे?', dine_in: 'यहीं बैठकर', takeaway: 'टेकअवे', pickup_name: 'आपका नाम (हम पुकारेंगे)', enter_name: 'अपना नाम लिखें',
      token_takeaway: 'टोकन {token} · टेकअवे', tk_coming: 'हम आपका टेकअवे तैयार कर रहे हैं!', tk_ready: 'आपका टेकअवे तैयार है। कृपया काउंटर से ले लें।',
      tk_done: 'ले लिया गया। धन्यवाद!', st_ready_tk: 'पिकअप के लिए तैयार', st_served_tk: 'ले लिया गया', stop_ready_tk: 'पिकअप के लिए तैयार', stop_served_tk: 'ले लिया गया',
      note_label: 'खास निर्देश (वैकल्पिक)', note_short: 'निर्देश', note_hint: 'जैसे कम तीखा, बिना प्याज़',
      scan_qr: 'ऑर्डर करने के लिए अपनी टेबल का QR कोड स्कैन करें। मेन्यू यहाँ पढ़ सकते हैं।', scan_first: 'ऑर्डर के लिए टेबल का QR स्कैन करें',
      takeaway_counter: 'टेकअवे के लिए कृपया काउंटर पर ऑर्डर और भुगतान करें।', phone: 'मोबाइल नंबर', enter_phone: 'मोबाइल नंबर लिखें', pay_place: 'ऑनलाइन भुगतान करें - {total}', pay_title: 'टेस्ट भुगतान',
      pay_note: 'यह सिर्फ़ टेस्ट स्क्रीन है। कोई असली पैसा नहीं कटेगा।', pay_ok: 'सफल भुगतान आज़माएँ', pay_fail: 'असफल भुगतान आज़माएँ', pay_back: 'वापस',
      pay_failed: 'भुगतान नहीं हुआ। आपका ऑर्डर नहीं भेजा गया।', pay_unavailable: 'ऑनलाइन भुगतान अभी चालू नहीं है। कृपया काउंटर पर ऑर्डर करें।',
      counter_note: 'भुगतान के बाद ही ऑर्डर रसोई में जाता है। काउंटर पर भुगतान करना है? वहीं ऑर्डर करें।', phone_privacy: 'आपका नंबर सिर्फ़ इस ऑर्डर के लिए है।',
      paid_online: 'ऑनलाइन भुगतान हो गया। टोकन नंबर संभालकर रखें।', confirm_title: 'ऑर्डर मिल गया!', confirm_text: 'हम इसे टेबल {n} पर ले आएँगे।',
      eta_about: 'लगभग {a}-{b} मिनट में तैयार', eta_left: 'अनुमान: {t} बाकी', eta_late: 'उम्मीद से थोड़ा ज़्यादा समय लग रहा है'
    },
    mr: {
      order_at_table: 'तुमच्या टेबलवरून ऑर्डर करा', table: 'टेबल {n}', pick_table: 'तुमचा टेबल निवडा', change_table: 'टेबल बदला',
      your_table: 'तुमचा टेबल क्र.', ticket: 'तुमचे तिकीट', nothing: 'तिकिटात अजून काही नाही. एखाद्या पदार्थावर ‘जोडा’ दाबा.',
      empty_sub: 'रिकामे', item_one: '{n} पदार्थ', item_many: '{n} पदार्थ', add: 'जोडा', everything: 'सर्व',
      total: 'एकूण', place: 'ऑर्डर द्या', place_total: 'ऑर्डर द्या - {total}', add_first: 'आधी काहीतरी जोडा',
      name_opt: 'नाव (ऐच्छिक)', pref_head: 'चहाचा मिजाज', strength: 'कडकपणा', sugar: 'साखर',
      Halka: 'हलका', Normal: 'सामान्य', Kadak: 'कडक', Kam: 'कमी', Zyada: 'जास्त',
      no_payment: 'आता पैसे द्यायचे नाहीत. जाताना काउंटरवर द्या.',
      unavailable: 'उपलब्ध नाही', free: 'मोफत', view_ticket: 'तिकीट पहा', language: 'भाषा',
      coming: 'तुमची ऑर्डर लवकरच तुमच्या टेबलवर येत आहे!', reached: 'तुमची ऑर्डर तुमच्या टेबलवर पोहोचली!',
      cancelled: 'ही ऑर्डर रद्द झाली. कृपया काउंटरवर विचारा.',
      token_table: 'टोकन {token} · टेबल {n}', more: 'आणखी ऑर्डर करा',
      closed: 'हे रेस्टॉरंट सध्या ऑर्डर घेत नाही.',
      st_new: 'ऑर्डर मिळाली', st_preparing: 'तयार होत आहे', st_ready: 'तयार आहे, येत आहे', st_served: 'तुमच्या टेबलवर',
      stop_new: 'मिळाली', stop_preparing: 'तयारी', stop_ready: 'तयार', stop_served: 'तुमच्या टेबलवर',
      slip: 'ऑर्डर पावती', pay_counter: 'काउंटरवर पैसे द्या. टोकन क्रमांक जपून ठेवा.',
      err_place: 'ऑर्डर देता आली नाही. कृपया पुन्हा प्रयत्न करा.', no_link: 'या लिंकमध्ये रेस्टॉरंट नाही.',
      not_found: 'हे रेस्टॉरंट सापडले नाही.', added: '{name} जोडले', removed: '{name} काढले',
      status_now: 'तुमची ऑर्डर: {s}', live: 'लाइव्ह', reconnecting: 'पुन्हा जोडत आहे',
      how_head: 'तुम्हाला कसे हवे आहे?', dine_in: 'येथे बसून', takeaway: 'टेकअवे', pickup_name: 'तुमचे नाव (आम्ही पुकारू)', enter_name: 'तुमचे नाव लिहा',
      token_takeaway: 'टोकन {token} · टेकअवे', tk_coming: 'आम्ही तुमचा टेकअवे तयार करत आहोत!', tk_ready: 'तुमचा टेकअवे तयार आहे. कृपया काउंटरवरून घ्या.',
      tk_done: 'घेतले. धन्यवाद!', st_ready_tk: 'घेण्यासाठी तयार', st_served_tk: 'घेतले', stop_ready_tk: 'घेण्यासाठी तयार', stop_served_tk: 'घेतले',
      note_label: 'विशेष सूचना (ऐच्छिक)', note_short: 'सूचना', note_hint: 'उदा. कमी तिखट, कांदा नको',
      scan_qr: 'ऑर्डर करण्यासाठी तुमच्या टेबलवरील QR कोड स्कॅन करा. मेनू येथे वाचू शकता.', scan_first: 'ऑर्डरसाठी टेबलचा QR स्कॅन करा',
      takeaway_counter: 'टेकअवेसाठी कृपया काउंटरवर ऑर्डर द्या आणि पैसे भरा.', phone: 'मोबाइल क्रमांक', enter_phone: 'मोबाइल क्रमांक लिहा', pay_place: 'ऑनलाइन पैसे द्या - {total}', pay_title: 'टेस्ट पेमेंट',
      pay_note: 'ही फक्त टेस्ट स्क्रीन आहे. खरे पैसे कापले जाणार नाहीत.', pay_ok: 'यशस्वी पेमेंट करून पहा', pay_fail: 'अयशस्वी पेमेंट करून पहा', pay_back: 'मागे',
      pay_failed: 'पेमेंट झाले नाही. तुमची ऑर्डर पाठवलेली नाही.', pay_unavailable: 'ऑनलाइन पेमेंट सध्या सुरू नाही. कृपया काउंटरवर ऑर्डर करा.',
      counter_note: 'पेमेंट झाल्यावरच ऑर्डर स्वयंपाकघरात जाते. काउंटरवर पैसे द्यायचे आहेत? तिथेच ऑर्डर करा.', phone_privacy: 'तुमचा क्रमांक फक्त या ऑर्डरसाठी आहे.',
      paid_online: 'ऑनलाइन पैसे मिळाले. टोकन क्रमांक जपून ठेवा.', confirm_title: 'ऑर्डर मिळाली!', confirm_text: 'आम्ही ती टेबल {n} वर आणून देऊ.',
      eta_about: 'सुमारे {a}-{b} मिनिटांत तयार', eta_left: 'अंदाज: {t} बाकी', eta_late: 'अपेक्षेपेक्षा थोडा जास्त वेळ लागत आहे'
    }
  };

  var cur = 'en';
  var defaultLang = 'en';

  window.I18N = {
    NAMES: NAMES,
    setLang: function (l, def) { cur = S[l] ? l : 'en'; defaultLang = def || 'en'; document.documentElement.lang = cur; return cur; },
    lang: function () { return cur; },
    t: function (key, vars) {
      var s = (S[cur] && S[cur][key]) || S.en[key] || key;
      Object.keys(vars || {}).forEach(function (k) { s = s.split('{' + k + '}').join(vars[k]); });
      return s;
    },
    // Pick the text for the current language, falling back to the brand's default, then English.
    pick: function (map) {
      if (!map) return '';
      return map[cur] || map[defaultLang] || map.en || map[Object.keys(map)[0]] || '';
    },
    money: function (currency, n) {
      if (n === 0) return window.I18N.t('free');
      return (currency === 'INR' ? 'Rs. ' : currency + ' ') + n;
    }
  };
})();

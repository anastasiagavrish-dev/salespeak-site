(function () {
  var body = document.body;
  var METRIKA = body.getAttribute('data-metrika') || '';
  var metrikaLoaded = false;

  function store(k, v) { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } }

  // ---------- Яндекс Метрика, только после согласия ----------
  function loadMetrika() {
    if (metrikaLoaded || !METRIKA) return;
    metrikaLoaded = true;
    (function (m, e, t, r, i, k, a) { m[i] = m[i] || function () { (m[i].a = m[i].a || []).push(arguments) }; m[i].l = 1 * new Date();
      k = e.createElement(t), a = e.getElementsByTagName(t)[0], k.async = 1, k.src = r, a.parentNode.insertBefore(k, a) })
    (window, document, 'script', 'https://mc.yandex.ru/metrika/tag.js', 'ym');
    window.ym(+METRIKA, 'init', { clickmap: true, trackLinks: true, accurateTrackBounce: true, webvisor: false });
  }
  function goal(name) { if (metrikaLoaded && window.ym) window.ym(+METRIKA, 'reachGoal', name); }

  // ---------- cookie-баннер ----------
  var banner = document.getElementById('cookie');
  var choice = store('sp_cookie');
  if (choice === 'yes') loadMetrika();
  else if (choice !== 'no' && banner) banner.hidden = false;
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-cookie]');
    if (b) {
      store('sp_cookie', b.getAttribute('data-cookie'));
      banner.hidden = true;
      if (b.getAttribute('data-cookie') === 'yes') loadMetrika();
    }
    if (e.target.closest('[data-cookie-settings]') && banner) banner.hidden = false;
    var m = e.target.closest('a[href^="https://t.me"],a[href^="https://wa.me"]');
    if (m) goal('messenger');
  });

  // ---------- фильтр кейсов ----------
  var chips = document.querySelectorAll('.chip[data-filter]');
  chips.forEach(function (c) {
    c.addEventListener('click', function () {
      var f = c.getAttribute('data-filter'), shown = 0;
      chips.forEach(function (x) { var on = x === c; x.classList.toggle('on', on); x.setAttribute('aria-pressed', on ? 'true' : 'false'); });
      document.querySelectorAll('.case-row').forEach(function (r) {
        var ok = f === 'all' || (' ' + r.getAttribute('data-tags') + ' ').indexOf(' ' + f + ' ') >= 0;
        r.hidden = !ok; if (ok) shown++;
      });
      var empty = document.querySelector('.cases-cat .empty'); if (empty) empty.hidden = shown > 0;
    });
  });

  // ---------- форма заявки ----------
  var form = document.querySelector('form.form');
  if (!form) return;
  var $ = function (s) { return form.querySelector(s); };
  var nameI = $('[name=name]'), contactI = $('[name=contact]'), pdI = $('[name=consent_pd]'), adsI = $('[name=consent_ads]');
  var countryBox = $('.country'), btn = $('button[type=submit]'), ok = $('.form-ok'), formErr = $('.form-err');
  var preview = form.getAttribute('data-preview') === '1';
  var kzApi = form.getAttribute('data-kz-api') || '';

  function setErr(el, msg) {
    var f = el.closest('.field'); if (!f) return;
    var p = f.querySelector('.err');
    f.classList.toggle('bad', !!msg);
    if (p) { p.textContent = msg || ''; p.hidden = !msg; }
  }
  function digits(v) { return (v || '').replace(/\D/g, ''); }
  function isPhone(v) { return digits(v).length >= 10; }
  function isTg(v) { return /^@?[A-Za-z0-9_]{5,32}$/.test((v || '').trim()); }
  // Казахстанские номера: +7 7xx… или 8 7xx…
  function phoneCountry(v) {
    var d = digits(v);
    if (d.length === 11 && (d[0] === '7' || d[0] === '8')) return d[1] === '7' ? 'kz' : 'ru';
    return '';
  }
  function checkName() { var m = nameI.value.trim() ? '' : 'Напишите, как к вам обращаться'; setErr(nameI, m); return !m; }
  function checkContact() {
    var v = contactI.value.trim();
    var m = !v ? 'Оставьте телефон или ник в Telegram' : (isPhone(v) || isTg(v) ? '' : 'Нужен телефон, например +7 701 123 45 67, или ник в Telegram, например @ivanova');
    setErr(contactI, m);
    var needCountry = !m && !phoneCountry(v);
    countryBox.hidden = !needCountry;
    return !m;
  }
  function country() {
    var pc = phoneCountry(contactI.value);
    if (pc) return pc;
    var r = form.querySelector('[name=country]:checked');
    return r ? r.value : '';
  }
  nameI.addEventListener('blur', checkName);
  contactI.addEventListener('blur', checkContact);
  // Вопрос о стране показываем сразу при вводе, чтобы форма не прыгала в момент нажатия на галочку
  contactI.addEventListener('input', function () {
    var v = contactI.value.trim(), d = digits(v);
    var foreignPhone = d.length >= 12 || (d.length >= 10 && d[0] !== '7' && d[0] !== '8');
    countryBox.hidden = !v || !!phoneCountry(v) || !(/[A-Za-z@_]/.test(v) || foreignPhone);
  });
  pdI.addEventListener('change', function () { if (pdI.checked) setErr(pdI, ''); });

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    formErr.hidden = true;
    var a = checkName(), b = checkContact(), c = pdI.checked;
    setErr(pdI, c ? '' : 'Без согласия на обработку данных заявку отправить нельзя');
    var cn = country();
    var needC = !countryBox.hidden && !cn;
    setErr(countryBox.querySelector('input'), needC ? 'Выберите страну, чтобы заявка сохранилась по законам вашей страны' : '');
    if (!(a && b && c) || needC) { var bad = form.querySelector('.field.bad input, .field.bad textarea'); if (bad) bad.focus(); return; }

    btn.disabled = true; var label = btn.textContent; btn.textContent = 'Отправляем…';
    var data = { name: nameI.value.trim(), contact: contactI.value.trim(), pain: $('[name=pain]').value.trim(), country: cn,
      consent_pd: true, consent_ads: adsI.checked, website: $('[name=website]').value, page: location.pathname };
    function done() { btn.hidden = true; ok.hidden = false; ok.focus(); goal('lead'); }
    function fail(msg) { btn.disabled = false; btn.textContent = label; formErr.textContent = msg; formErr.hidden = false; }
    if (preview) { setTimeout(done, 700); return; }
    var url = cn === 'kz' && kzApi ? kzApi : '/api/lead';
    fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) })
      .then(function (r) { return r.json().then(function (j) { return { s: r.status, j: j }; }); })
      .then(function (res) {
        if (res.j && res.j.ok) return done();
        if (res.j && res.j.errors) {
          if (res.j.errors.name) setErr(nameI, res.j.errors.name);
          if (res.j.errors.contact) setErr(contactI, res.j.errors.contact);
          if (res.j.errors.consent_pd) setErr(pdI, res.j.errors.consent_pd);
          return fail('Проверьте поля формы.');
        }
        fail((res.j && res.j.error) || 'Заявка не отправилась. Попробуйте еще раз или напишите в Telegram @gavrish_anastasiya.');
      })
      .catch(function () { fail('Нет связи с сервером. Проверьте интернет и попробуйте еще раз или напишите в Telegram @gavrish_anastasiya.'); });
  });
})();

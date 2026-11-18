/* Own signed partner reads. Stored economics and unknown source states stay explicit. */
(function () {
  'use strict';
  var bridge = window.__umcAppBridge;
  var screen = document.getElementById('screen-partner');
  if (!bridge || !screen) return;
  var copy = {
    ru: { title:'Партнёрский кабинет', entry:'Партнёрская программа', link:'Ваша ссылка', copy:'Скопировать ссылку', copied:'Ссылка скопирована.', manual:'Ссылка выделена. Скопируйте её вручную.', noLink:'Реферальная ссылка пока недоступна.', grade:'Ваш уровень', verified:'Уникальные подтверждённые авторы', next:'До следующего уровня', top:'Достигнут максимальный стандартный уровень.', rules:'Ставка автора в первый год: 10 / 12 / 15 / 20% при 0 / 100 / 200 / 400 подтверждённых Instagram-профилях. Клиент: 10%. После первого года от регистрации каждого приглашённого — 3% с новых операций. История сохраняет ставку на момент оплаты.', overrides:'Индивидуальные ставки по правилам операции', noOverrides:'Действующих индивидуальных ставок не найдено.', unavailable:'Данные источника временно недоступны.', network:'Ваша зарегистрированная сеть', emptyNetwork:'Зарегистрированных приглашённых пока нет.', registered:'Регистрация', followers:'Подписчики', unknown:'Неизвестно', source:'Источник', checked:'Наблюдение', badge:'Подтверждено', unverified:'Не подтверждено', client:'Клиент', creator:'Креатор', manager:'Менеджер', active:'Активен', pause:'На паузе', blocked:'Ограничен', new:'Новый', bot_blocked:'Бот недоступен', deleted:'Удалён', finance:'Начисления по журналу', ready:'Журнал и остатки сверены. Суммы указаны до индивидуальных налогов и удержаний.', mismatch:'Обнаружено расхождение учёта. Суммы журнала не подтверждают доступность выплаты; требуется сверка.', uninitialized:'Начислений в новом журнале пока нет.', paused:'Финансовые операции приостановлены. Доступен просмотр сохранённых данных.', client_referral:'За приглашённых клиентов', creator_referral:'За приглашённых авторов', management:'За сопровождение', pending:'Ожидает результата', hold:'Удержание', available:'Доступно по журналу', reserved:'Зарезервировано', paid:'Выплачено', cancelled:'Отменено', debt:'Задолженность', history:'История операций', emptyHistory:'Записей пока нет.', base:'База', rate:'Ставка при оплате', snapshot:'Снимок условий', policy:'Правила', standard:'Стандартная', override:'Индивидуальная', fixed:'Фиксированное вознаграждение', issuance:'Начисление', transfer:'Перемещение', reversal:'Отмена начисления', recovery:'Возмещение', assignments:'Ваши текущие назначения', emptyAssignments:'Текущих назначений нет.', openWork:'Открыть сотрудничество', due:'Срок', reload:'Обновить', back:'Назад', previous:'Предыдущие', more:'Следующие', loading:'Загружаем кабинет…', error:'Не удалось загрузить кабинет. Попробуйте обновить.', session:'Откройте приложение заново.', forbidden:'Кабинет недоступен для текущего аккаунта.' },
    en: { title:'Partner cabinet', entry:'Partner program', link:'Your referral link', copy:'Copy link', copied:'Link copied.', manual:'Link selected. Copy it manually.', noLink:'Referral link is currently unavailable.', grade:'Your level', verified:'Unique verified creators', next:'Creators to the next level', top:'Highest standard level reached.', rules:'Creator first-year rates: 10 / 12 / 15 / 20% at 0 / 100 / 200 / 400 verified Instagram profiles. Client: 10%. After each invited user’s first registration anniversary: 3% on new operations. History keeps the rate recorded at payment.', overrides:'Individual rates by operation policy', noOverrides:'No active individual rates found.', unavailable:'Source data is temporarily unavailable.', network:'Your registered network', emptyNetwork:'No registered referrals yet.', registered:'Registered', followers:'Followers', unknown:'Unknown', source:'Source', checked:'Observed', badge:'Verified', unverified:'Unverified', client:'Client', creator:'Creator', manager:'Manager', active:'Active', pause:'Paused', blocked:'Restricted', new:'New', bot_blocked:'Bot unreachable', deleted:'Deleted', finance:'Journal earnings', ready:'Journal and stored balances match. Amounts are before individual taxes or deductions.', mismatch:'Accounting mismatch. Journal amounts do not establish payout availability; reconciliation is required.', uninitialized:'No earnings recorded in the new journal yet.', paused:'Financial operations are paused. Stored data remains readable.', client_referral:'Client referrals', creator_referral:'Creator referrals', management:'Management work', pending:'Pending outcome', hold:'On hold', available:'Available in journal', reserved:'Reserved', paid:'Paid', cancelled:'Cancelled', debt:'Debt', history:'Operation history', emptyHistory:'No entries yet.', base:'Base', rate:'Rate at payment', snapshot:'Terms snapshot', policy:'Policy', standard:'Standard', override:'Individual', fixed:'Fixed reward', issuance:'Issuance', transfer:'Transfer', reversal:'Reversal', recovery:'Recovery', assignments:'Your current assignments', emptyAssignments:'No current assignments.', openWork:'Open collaboration', due:'Due', reload:'Refresh', back:'Back', previous:'Previous', more:'Next', loading:'Loading your cabinet…', error:'Could not load the cabinet. Try refreshing.', session:'Reopen the app to continue.', forbidden:'The cabinet is unavailable for this account.' },
    kk: { title:'Серіктес кабинеті', entry:'Серіктестік бағдарлама', link:'Сіздің сілтемеңіз', copy:'Сілтемені көшіру', copied:'Сілтеме көшірілді.', manual:'Сілтеме таңдалды. Қолмен көшіріңіз.', noLink:'Реферал сілтемесі қазір қолжетімсіз.', grade:'Сіздің деңгейіңіз', verified:'Бірегей расталған креаторлар', next:'Келесі деңгейге дейін', top:'Ең жоғары стандартты деңгейге жеттіңіз.', rules:'Автор үшін алғашқы жылы: 0 / 100 / 200 / 400 расталған Instagram профиліне 10 / 12 / 15 / 20%. Клиент: 10%. Әр шақырылған пайдаланушы тіркелгеннен бір жыл өткен соң жаңа операцияларға 3%. Тарихта төлем кезіндегі мөлшерлеме сақталады.', overrides:'Операция ережелері бойынша жеке мөлшерлемелер', noOverrides:'Белсенді жеке мөлшерлемелер жоқ.', unavailable:'Дереккөз уақытша қолжетімсіз.', network:'Тіркелген желіңіз', emptyNetwork:'Тіркелген шақырылғандар әлі жоқ.', registered:'Тіркелу', followers:'Жазылушылар', unknown:'Белгісіз', source:'Дереккөз', checked:'Бақыланған уақыт', badge:'Расталған', unverified:'Расталмаған', client:'Клиент', creator:'Креатор', manager:'Менеджер', active:'Белсенді', pause:'Үзілісте', blocked:'Шектелген', new:'Жаңа', bot_blocked:'Бот қолжетімсіз', deleted:'Жойылған', finance:'Журнал бойынша есептеулер', ready:'Журнал мен қалдықтар сәйкес. Жеке салықтар мен ұсталымдарға дейінгі сомалар.', mismatch:'Есепте сәйкессіздік бар. Журнал сомалары төлемге рұқсат бермейді; салыстыру қажет.', uninitialized:'Жаңа журналда есептеулер әлі жоқ.', paused:'Қаржылық операциялар тоқтатылған. Сақталған деректерді қарауға болады.', client_referral:'Шақырылған клиенттер үшін', creator_referral:'Шақырылған авторлар үшін', management:'Сүйемелдеу үшін', pending:'Нәтижені күтуде', hold:'Ұсталымда', available:'Журналда қолжетімді', reserved:'Резервте', paid:'Төленген', cancelled:'Жойылған', debt:'Берешек', history:'Операциялар тарихы', emptyHistory:'Жазбалар әлі жоқ.', base:'База', rate:'Төлем кезіндегі мөлшерлеме', snapshot:'Шарттар кескіні', policy:'Ережелер', standard:'Стандартты', override:'Жеке', fixed:'Тұрақты сыйақы', issuance:'Есептеу', transfer:'Ауыстыру', reversal:'Есептеуді жою', recovery:'Өтеу', assignments:'Ағымдағы тапсырмаларыңыз', emptyAssignments:'Ағымдағы тапсырмалар жоқ.', openWork:'Ынтымақтастықты ашу', due:'Мерзім', reload:'Жаңарту', back:'Артқа', previous:'Алдыңғы', more:'Келесі', loading:'Кабинет жүктелуде…', error:'Кабинет жүктелмеді. Жаңартып көріңіз.', session:'Жалғастыру үшін қолданбаны қайта ашыңыз.', forbidden:'Бұл аккаунтқа кабинет қолжетімсіз.' },
    be: { title:'Партнёрскі кабінет', entry:'Партнёрская праграма', link:'Ваша спасылка', copy:'Скапіяваць спасылку', copied:'Спасылка скапіявана.', manual:'Спасылка вылучана. Скапіюйце ўручную.', noLink:'Рэферальная спасылка пакуль недаступная.', grade:'Ваш узровень', verified:'Унікальныя пацверджаныя аўтары', next:'Да наступнага ўзроўню', top:'Дасягнуты найвышэйшы стандартны ўзровень.', rules:'За аўтара ў першы год: 10 / 12 / 15 / 20% пры 0 / 100 / 200 / 400 пацверджаных Instagram-профілях. За кліента: 10%. Праз год пасля рэгістрацыі кожнага запрошанага — 3% з новых аперацый. Гісторыя захоўвае стаўку пры аплаце.', network:'Ваша зарэгістраваная сетка', emptyNetwork:'Зарэгістраваных запрошаных пакуль няма.', followers:'Падпісчыкі', unknown:'Невядома', badge:'Пацверджана', finance:'Налічэнні па журнале', paused:'Фінансавыя аперацыі прыпыненыя. Захаваныя даныя даступныя для прагляду.', history:'Гісторыя аперацый', reload:'Абнавіць', back:'Назад', loading:'Загружаем кабінет…' },
    uz: { title:'Hamkor kabineti', entry:'Hamkorlik dasturi', link:'Sizning havolangiz', copy:'Havolani nusxalash', copied:'Havola nusxalandi.', manual:'Havola tanlandi. Qo‘lda nusxalang.', noLink:'Referal havolasi hozir mavjud emas.', grade:'Darajangiz', verified:'Noyob tasdiqlangan kreatorlar', next:'Keyingi darajagacha', top:'Eng yuqori standart darajaga yetdingiz.', rules:'Muallif uchun birinchi yil: 0 / 100 / 200 / 400 tasdiqlangan Instagram profilida 10 / 12 / 15 / 20%. Mijoz: 10%. Har bir taklif qilingan foydalanuvchi ro‘yxatdan o‘tganidan bir yil keyin yangi operatsiyalar uchun 3%. Tarix to‘lov paytidagi stavkani saqlaydi.', network:'Ro‘yxatdan o‘tgan tarmog‘ingiz', emptyNetwork:'Ro‘yxatdan o‘tgan takliflar hali yo‘q.', followers:'Obunachilar', unknown:'Noma’lum', badge:'Tasdiqlangan', finance:'Jurnaldagi hisoblashlar', paused:'Moliyaviy operatsiyalar to‘xtatilgan. Saqlangan ma’lumotlarni ko‘rish mumkin.', history:'Operatsiyalar tarixi', reload:'Yangilash', back:'Orqaga', loading:'Kabinet yuklanmoqda…' }
  };
  Object.assign(copy.be, { overrides:'Індывідуальныя стаўкі паводле правілаў аперацыі', noOverrides:'Дзейных індывідуальных ставак няма.', unavailable:'Даныя крыніцы часова недаступныя.', registered:'Рэгістрацыя', source:'Крыніца', checked:'Назіранне', unverified:'Не пацверджана', client:'Кліент', creator:'Крэатар', manager:'Менеджар', active:'Актыўны', pause:'На паўзе', blocked:'Абмежаваны', new:'Новы', bot_blocked:'Бот недаступны', deleted:'Выдалены', ready:'Журнал і рэшткі звереныя. Сумы да індывідуальных падаткаў і ўтрыманняў.', mismatch:'Выяўлена разыходжанне ўліку. Сумы журнала не пацвярджаюць магчымасць выплаты; патрэбная зверка.', uninitialized:'У новым журнале налічэнняў пакуль няма.', client_referral:'За запрошаных кліентаў', creator_referral:'За запрошаных аўтараў', management:'За суправаджэнне', pending:'Чакае выніку', hold:'Утрыманне', available:'Даступна паводле журнала', reserved:'Зарэзервавана', paid:'Выплачана', cancelled:'Скасавана', debt:'Запазычанасць', emptyHistory:'Запісаў пакуль няма.', base:'База', rate:'Стаўка пры аплаце', snapshot:'Здымак умоў', policy:'Правілы', standard:'Стандартная', override:'Індывідуальная', fixed:'Фіксаванае ўзнагароджанне', issuance:'Налічэнне', transfer:'Перамяшчэнне', reversal:'Скасаванне налічэння', recovery:'Вяртанне', assignments:'Вашы бягучыя прызначэнні', emptyAssignments:'Бягучых прызначэнняў няма.', openWork:'Адкрыць супрацоўніцтва', due:'Тэрмін', previous:'Папярэднія', more:'Наступныя', error:'Не ўдалося загрузіць кабінет. Паспрабуйце абнавіць.', session:'Адкрыйце праграму нанова.', forbidden:'Кабінет недаступны для гэтага акаўнта.' });
  Object.assign(copy.uz, { overrides:'Operatsiya qoidalari bo‘yicha individual stavkalar', noOverrides:'Faol individual stavkalar yo‘q.', unavailable:'Manba ma’lumotlari vaqtincha mavjud emas.', registered:'Ro‘yxatdan o‘tish', source:'Manba', checked:'Kuzatilgan vaqt', unverified:'Tasdiqlanmagan', client:'Mijoz', creator:'Kreator', manager:'Menejer', active:'Faol', pause:'Tanaffusda', blocked:'Cheklangan', new:'Yangi', bot_blocked:'Bot mavjud emas', deleted:'O‘chirilgan', ready:'Jurnal va qoldiqlar mos. Summalar individual soliqlar va ushlanmalardan oldin.', mismatch:'Hisobda nomuvofiqlik bor. Jurnal summalari to‘lovga ruxsat bermaydi; solishtirish kerak.', uninitialized:'Yangi jurnalda hali hisoblashlar yo‘q.', client_referral:'Taklif qilingan mijozlar uchun', creator_referral:'Taklif qilingan mualliflar uchun', management:'Hamrohlik uchun', pending:'Natijani kutmoqda', hold:'Ushlab turilgan', available:'Jurnalda mavjud', reserved:'Zaxiralangan', paid:'To‘langan', cancelled:'Bekor qilingan', debt:'Qarzdorlik', emptyHistory:'Hali yozuvlar yo‘q.', base:'Baza', rate:'To‘lov paytidagi stavka', snapshot:'Shartlar nusxasi', policy:'Qoidalar', standard:'Standart', override:'Individual', fixed:'Belgilangan mukofot', issuance:'Hisoblash', transfer:'O‘tkazish', reversal:'Hisoblashni bekor qilish', recovery:'Qoplash', assignments:'Joriy topshiriqlaringiz', emptyAssignments:'Joriy topshiriqlar yo‘q.', openWork:'Hamkorlikni ochish', due:'Muddat', previous:'Oldingi', more:'Keyingi', error:'Kabinet yuklanmadi. Yangilab ko‘ring.', session:'Davom etish uchun ilovani qayta oching.', forbidden:'Bu hisob uchun kabinet mavjud emas.' });
  copy.ru.instagramVerification='Проверка Instagram в UMC'; copy.en.instagramVerification='Instagram verification in UMC'; copy.kk.instagramVerification='UMC жүйесіндегі Instagram растауы'; copy.be.instagramVerification='Праверка Instagram у UMC'; copy.uz.instagramVerification='UMC orqali Instagram tasdig‘i';
  var reportedLabels = {ru:'Со слов креатора',en:'Reported by creator',kk:'Креатор көрсеткен',be:'Са слоў крэатара',uz:'Ijodkor ko‘rsatgan'};
  Object.keys(reportedLabels).forEach(function (lang) { copy[lang].selfReported = reportedLabels[lang]; });
  var workStates = {
    ru:{assigned:'Назначено',in_progress:'В работе',success_claimed:'Заявлен успех',disputed:'Есть возражение',success_final:'Успех подтверждён',unconfirmed_expired:'Срок подтверждения истёк',available:'Удержание завершено'},
    en:{assigned:'Assigned',in_progress:'In progress',success_claimed:'Success claimed',disputed:'Disputed',success_final:'Success confirmed',unconfirmed_expired:'Confirmation expired',available:'Hold finished'},
    kk:{assigned:'Тағайындалған',in_progress:'Жұмыста',success_claimed:'Сәтті аяқталу мәлімделді',disputed:'Қарсылық бар',success_final:'Сәтті аяқталу расталды',unconfirmed_expired:'Растау мерзімі өтті',available:'Ұсталым аяқталды'},
    be:{assigned:'Прызначана',in_progress:'У працы',success_claimed:'Заяўлены поспех',disputed:'Ёсць пярэчанне',success_final:'Поспех пацверджаны',unconfirmed_expired:'Тэрмін пацверджання мінуў',available:'Утрыманне скончылася'},
    uz:{assigned:'Tayinlangan',in_progress:'Jarayonda',success_claimed:'Muvaffaqiyat bildirildi',disputed:'E’tiroz bor',success_final:'Muvaffaqiyat tasdiqlandi',unconfirmed_expired:'Tasdiqlash muddati o‘tdi',available:'Ushlab turish tugadi'}
  };
  var state = { busy:false, opened:false, returnScreen:'screen-role-choice', network_page:0, history_page:0, assignment_page:0, bound:null, actor:null, data:null, requestId:0, focusAchievements:false };
  function id(value) { return document.getElementById(value); }
  function words() { return Object.assign({}, copy.ru, copy[(window._me || {}).locale] || {}); }
  function text(key, value) { id(key).textContent = value == null ? '' : String(value); }
  function node(tag, content, className) { var result = document.createElement(tag); result.textContent = content == null ? '' : String(content); if (className) result.className = className; return result; }
  function safeUrl(value) { try { var url = new URL(value); return url.protocol === 'https:' && !url.username && !url.password ? url.href : null; } catch (_) { return null; } }
  function date(value) { var parsed = new Date(value); return value && !isNaN(parsed.getTime()) ? parsed.toISOString().replace('T', ' ').slice(0,16) + ' UTC' : words().unknown; }
  function money(value, currency) { var raw = String(value); if (!/^\d+$/.test(raw)) return words().unknown; raw = raw.padStart(3,'0'); return raw.slice(0,-2).replace(/\B(?=(\d{3})+(?!\d))/g,'\u00a0') + ',' + raw.slice(-2) + '\u00a0' + currency; }
  Object.assign(copy.ru,{manual_adjustment:'Ручное доначисление',manualRate:'Ставка не применяется'});
  Object.assign(copy.en,{manual_adjustment:'Manual grant',manualRate:'Rate does not apply'});
  Object.assign(copy.kk,{manual_adjustment:'Қолмен қосымша есептеу',manualRate:'Мөлшерлеме қолданылмайды'});
  Object.assign(copy.be,{manual_adjustment:'Ручное даналічэнне',manualRate:'Стаўка не ўжываецца'});
  Object.assign(copy.uz,{manual_adjustment:'Qo‘lda qo‘shimcha hisoblash',manualRate:'Stavka qo‘llanilmaydi'});
  function percentage(value) { return typeof value === 'number' ? String(value / 100) + '%' : words().unknown; }
  function localize() {
    var c = words();
    ['network','finance','history','assignments','overrides'].forEach(function (key) {
      text('partner-' + key + '-title',c[key]);
    });
    text('partner-title',c.title);
    text('btn-partner-reload',c.reload);
    text('btn-partner-back',c.back);
  }
  function busy(value) { state.busy = value; screen.setAttribute('aria-busy',String(value)); text('partner-loading',value ? words().loading : ''); screen.querySelectorAll('button:not([data-payouts-open])').forEach(function (button) { button.disabled = value; }); }
  function definition(parent, key, value) { var row = node('div','', 'umc-partner-pair'); row.appendChild(node('dt',key)); row.appendChild(node('dd',value)); parent.appendChild(row); }
  function listEmpty(parent, message) { parent.appendChild(node('p',message,'hint')); }
  function pages(parent, key, page, more) { var c = words(); var controls = node('div','','pagination-btns'); [[c.previous,page-1,page>0],[c.more,page+1,more]].forEach(function (item) { if (!item[2]) return; var button = node('button',item[0],'btn btn-secondary'); button.type='button'; button.addEventListener('click',function () { state[key]=item[1]; load(); }); controls.appendChild(button); }); parent.appendChild(controls); }
  function network(data) { var c=words(), parent=id('partner-network'); parent.replaceChildren(); if (!data.members.length) listEmpty(parent,c.emptyNetwork); data.members.forEach(function (member) { var article=node('article','','umc-partner-row'); article.appendChild(node('h3',member.roles.map(function (role) { return c[role] || role; }).join(' / ') || c.registered)); article.appendChild(node('p',c.registered + ': ' + date(member.registered_at) + ' · ' + (c[member.status] || member.status),'hint')); member.socials.forEach(function (social) { var url=safeUrl(social.url), line=node('div','','umc-partner-social'); var link=node(url ? 'a' : 'span',social.url); if (url) { link.href=url; link.target='_blank'; link.rel='noopener noreferrer'; } line.appendChild(link); line.appendChild(node('span',social.verified ? c.badge : c.unverified,'umc-partner-badge')); line.appendChild(node('p',c.followers + ': ' + (social.followers_count == null ? c.unknown : String(social.followers_count)),'hint')); if (social.metrics_source && social.metrics_fetched_at) line.appendChild(node('p',c.source + ': ' + (social.metrics_source === 'creator_self_reported' ? c.selfReported + ' · ' : social.metrics_source + ' · ' + c.checked + ': ') + date(social.metrics_fetched_at),'hint')); if (social.verification_source) line.appendChild(node('p',c.badge + ': ' + (['canonical_profile','canonical_verification','instagram_verification'].indexOf(social.verification_source)>=0 ? c.instagramVerification : social.verification_source),'hint')); article.appendChild(line); }); parent.appendChild(article); }); pages(parent,'network_page',data.page,data.has_more); }
  function balances(parent, values, currency) { var c=words(), list=node('dl','','umc-partner-balances'); ['pending','hold','available','reserved','paid','blocked','cancelled','debt'].forEach(function (key) { if (values[key] == null || (['blocked','cancelled','debt'].indexOf(key) >= 0 && values[key] === '0')) return; var row=node('div'); row.dataset.bucket=key; row.appendChild(node('dt',c[key])); var value=node('dd',money(values[key],currency)); value.dataset.money=values[key]; row.appendChild(value); list.appendChild(row); }); parent.appendChild(list); }
  function finance(data) { var c=words(), parent=id('partner-balances'), history=id('partner-history'); parent.replaceChildren(); history.replaceChildren(); id('partner-financial-status').dataset.state=data.state; text('partner-financial-status',c[data.state] || c.unavailable); if (data.balances) { balances(parent,data.balances,data.currency); data.groups.forEach(function (group) { var section=node('details','','umc-partner-kind'); section.appendChild(node('summary',c[group.kind] || group.kind)); balances(section,group.balances,data.currency); parent.appendChild(section); }); } if (!data.history.entries.length) listEmpty(history,c.emptyHistory); data.history.entries.forEach(function (entry) { var row=node('article','','umc-partner-row'); row.appendChild(node('h3',(c[entry.kind] || entry.kind) + ' · ' + money(entry.amount_minor,data.currency))); row.appendChild(node('p',entry.order_id,'umc-partner-reference')); var details=node('dl'); definition(details,c.snapshot,date(entry.snapshot_at)); definition(details,c.base,money(entry.base_minor,data.currency)); definition(details,c.rate,entry.kind === 'manual_adjustment' ? c.manualRate : entry.kind === 'management' ? c.fixed : percentage(entry.rate_bps) + ' · ' + (c[entry.rate_source] || entry.rate_source)); definition(details,c.policy,entry.policy_version); definition(details,c[entry.movement_type] || entry.movement_type,(entry.bucket_from ? c[entry.bucket_from] + ' → ' : '') + (c[entry.bucket_to] || '') + ' · ' + date(entry.effective_at)); row.appendChild(details); history.appendChild(row); }); pages(history,'history_page',data.history.page,data.history.has_more); }
  function overrides(data) { var c=words(), parent=id('partner-overrides'); parent.replaceChildren(); if (data.state !== 'available') { listEmpty(parent,c.unavailable); return; } if (!data.entries.length) listEmpty(parent,c.noOverrides); data.entries.forEach(function (entry) { var row=node('article','','umc-partner-row'); row.appendChild(node('h3',(c[entry.side] || entry.side) + ' ' + percentage(entry.rate_bps))); row.appendChild(node('p',c.policy + ': ' + entry.policy_version)); row.appendChild(node('p',date(entry.effective_from) + ' — ' + date(entry.effective_until),'hint')); parent.appendChild(row); }); }
  function assignments(data) { var c=words(), parent=id('partner-assignments'); parent.replaceChildren(); if (data.state !== 'available') { listEmpty(parent,c.unavailable); return; } if (!data.entries.length) listEmpty(parent,c.emptyAssignments); data.entries.forEach(function (entry) { var row=node('article','','umc-partner-row'); row.appendChild(node('p',entry.order_id,'umc-partner-reference')); row.appendChild(node('p',((workStates[(window._me || {}).locale] || workStates.ru)[entry.state] || c.unknown) + ' · ' + c.due + ': ' + date(entry.due_at),'hint')); if (window.UMCCollaboration) { var button=node('button',c.openWork,'btn btn-secondary'); button.type='button'; button.addEventListener('click',function () { window.UMCCollaboration.open(entry.assignment_id); }); row.appendChild(button); } parent.appendChild(row); }); pages(parent,'assignment_page',data.page,data.has_more); }
  function render(data) {
    var c = words();
    renderOverview(id('partner-overview'),data,c);
    renderLevel(id('partner-grade'),data,false);
    renderAchievements(id('partner-achievements'),data);
    text('partner-paused',data.writes_paused ? c.paused : '');
    network(data.network);
    finance(data.financial);
    overrides(data.overrides);
    assignments(data.assignments);
    id('partner-content').hidden = false;
  }

  Object.assign(copy.ru, {activeOrders:'Активные заказы', completedWorks:'Завершённые работы', waiting:'Что ожидается', successful:'Успешно завершено', beforeAdjustments:'До корректировок; выплата зависит от состояния журнала', awaiting_confirmation:'Успех не подтверждён', awaiting_counterparty:'Ожидается ответ второй стороны', confirmation_notice_pending:'Ожидается доставка запроса подтверждения', expiry_processing:'Срок подтверждения истёк; отмена обрабатывается', dispute_review:'Требуется рассмотрение спора', financial_processing:'Подтверждено; финансовая обработка', selection_completion:'Ожидается закрытие подбора и окончание периода возврата', assessment_pending:'Уточняется основание начисления'});
  Object.assign(copy.en, {activeOrders:'Active orders', completedWorks:'Completed works', waiting:'Pending requirements', successful:'Successfully completed', beforeAdjustments:'Before adjustments; payout depends on journal status', awaiting_confirmation:'Success has not been confirmed', awaiting_counterparty:'Awaiting the other party', confirmation_notice_pending:'Awaiting confirmation notice delivery', expiry_processing:'Confirmation expired; cancellation is being processed', dispute_review:'Dispute requires review', financial_processing:'Confirmed; financial processing', selection_completion:'Awaiting selection closure and refund period', assessment_pending:'Earning basis is being assessed'});
  var homes=[];
  function clearPrivate() {
    if(state.bound) state.bound.dispose();
    state.bound=null; state.actor=null; state.data=null; adminState={pending:null,review:null,busy:false};
    state.focusAchievements=false;
    id('partner-content').hidden=true;
    id('partner-overview').replaceChildren();
    id('partner-grade').replaceChildren();
    id('partner-achievements').replaceChildren();
    showHomes(null, words().session);
    var admin=id('partner-override-admin'); if(admin) admin.remove();
  }
  function current() {
    if(!state.bound || !state.bound.isCurrent()) { clearPrivate(); return false; }
    return true;
  }
  function bind() {
    if(!state.bound) state.bound=bridge.createRequestContext();
    return current();
  }
  var overviewCopy = {
    ru: {
      copyShort:'Копировать', copiedShort:'Скопировано', openCabinet:'Открыть кабинет',
      account:'Статус аккаунта', invited:'Приглашённые', managers:'Подключённые менеджеры',
      referralEarned:'Доход за приглашения', managementEarned:'Доход за сопровождение',
      legacy:'Начислено по прежним заказам', earningsUnavailable:'Начисления уточняются',
      how:'Делитесь ссылкой и получайте процент с оплаченных заказов приглашённых клиентов и авторов.',
      terms:'Условия программы', managerProgram:'Работа менеджером'
    },
    en: {
      copyShort:'Copy', copiedShort:'Copied', openCabinet:'Open cabinet',
      account:'Account status', invited:'Invited users', managers:'Connected managers',
      referralEarned:'Referral earnings', managementEarned:'Management earnings',
      legacy:'Earned on earlier orders', earningsUnavailable:'Earnings unavailable',
      how:'Invite clients and creators with your link and earn a share of their paid orders under the program terms.',
      terms:'Program terms', managerProgram:'Work as a manager'
    },
    kk: {
      copyShort:'Көшіру', copiedShort:'Көшірілді', openCabinet:'Кабинетті ашу',
      account:'Аккаунт күйі', invited:'Шақырылғандар', managers:'Қосылған менеджерлер',
      referralEarned:'Шақырудан табыс', managementEarned:'Сүйемелдеуден табыс',
      legacy:'Бұрынғы тапсырыстардан табыс', earningsUnavailable:'Табыс нақтылануда',
      how:'Клиенттер мен авторларды сілтемеңіз арқылы шақырыңыз. Бағдарлама шарттарына сай олардың ақылы тапсырыстарынан пайыз аласыз.',
      terms:'Бағдарлама шарттары', managerProgram:'Менеджер жұмысы'
    },
    be: {
      copyShort:'Скапіяваць', copiedShort:'Скапіявана', openCabinet:'Адкрыць кабінет',
      account:'Статус акаўнта', invited:'Запрошаныя', managers:'Падключаныя менеджары',
      referralEarned:'Даход за запрашэнні', managementEarned:'Даход за суправаджэнне',
      legacy:'Налічана за ранейшыя заказы', earningsUnavailable:'Налічэнні ўдакладняюцца',
      how:'Запрашайце кліентаў і аўтараў па сваёй спасылцы і атрымлівайце працэнт з іх аплачаных заказаў паводле ўмоў праграмы.',
      terms:'Умовы праграмы', managerProgram:'Праца менеджарам'
    },
    uz: {
      copyShort:'Nusxalash', copiedShort:'Nusxalandi', openCabinet:'Kabinetni ochish',
      account:'Hisob holati', invited:'Taklif qilinganlar', managers:'Ulangan menejerlar',
      referralEarned:'Takliflar uchun', managementEarned:'Hamrohlik uchun',
      legacy:'Avvalgi buyurtmalardan daromad', earningsUnavailable:'Daromad aniqlanmoqda',
      how:'Mijozlar va ijodkorlarni havolangiz orqali taklif qiling. Dastur shartlariga ko‘ra ularning to‘langan buyurtmalaridan foiz oling.',
      terms:'Dastur shartlari', managerProgram:'Menejer bo‘lib ishlash'
    }
  };
  Object.keys(overviewCopy).forEach(function (lang) { Object.assign(copy[lang], overviewCopy[lang]); });

  var levelCopy = {
    ru: {
      levelNames: {0:'Старт',100:'Бронза',200:'Серебро',400:'Золото'},
      partnerLevel:'Ваш партнёрский уровень', confirmedAuthors:'Подтверждённые авторы',
      towardLevel:'До уровня «{level}»', remainingAuthors:'Осталось подтвердить {count}',
      standardCreatorRate:'Стандартная ставка за автора в первый год после его регистрации',
      inviteAuthor:'Пригласить автора', achievements:'Достижения', firstAuthor:'Первый автор',
      authorMilestone:'{count} авторов', achievementCount:'{count} из {total}',
      achieved:'Достигнуто', allAchievements:'Все достижения',
      levelRules:'Как считаются уровень и ставка',
      levelHelp:'Для уровня учитываются уникальные подтверждённые Instagram-профили лично приглашённых авторов.'
    },
    en: {
      levelNames: {0:'Start',100:'Bronze',200:'Silver',400:'Gold'},
      partnerLevel:'Your partner level', confirmedAuthors:'Verified creators',
      towardLevel:'Next level: {level}', remainingAuthors:'Creators to verify: {count}',
      standardCreatorRate:'Standard creator rate in the first year after their registration',
      inviteAuthor:'Invite a creator', achievements:'Achievements', firstAuthor:'First creator',
      authorMilestone:'{count} creators', achievementCount:'{count} of {total}',
      achieved:'Achieved', allAchievements:'All achievements',
      levelRules:'How levels and rates work',
      levelHelp:'Levels count unique verified Instagram profiles of creators you invited directly.'
    },
    kk: {
      levelNames: {0:'Бастау',100:'Қола',200:'Күміс',400:'Алтын'},
      partnerLevel:'Серіктестік деңгейіңіз', confirmedAuthors:'Расталған авторлар',
      towardLevel:'Келесі деңгей: {level}', remainingAuthors:'Тағы {count} авторды растау керек',
      standardCreatorRate:'Автор тіркелгеннен кейінгі алғашқы жылдағы стандартты мөлшерлеме',
      inviteAuthor:'Авторды шақыру', achievements:'Жетістіктер', firstAuthor:'Алғашқы автор',
      authorMilestone:'{count} автор', achievementCount:'{total} ішінен {count}',
      achieved:'Орындалды', allAchievements:'Барлық жетістіктер',
      levelRules:'Деңгей мен мөлшерлеме қалай есептеледі',
      levelHelp:'Деңгейге тікелей шақырған авторлардың бірегей расталған Instagram профильдері есептеледі.'
    },
    be: {
      levelNames: {0:'Старт',100:'Бронза',200:'Срэбра',400:'Золата'},
      partnerLevel:'Ваш партнёрскі ўзровень', confirmedAuthors:'Пацверджаныя аўтары',
      towardLevel:'Да ўзроўню «{level}»', remainingAuthors:'Засталося пацвердзіць {count}',
      standardCreatorRate:'Стандартная стаўка за аўтара ў першы год пасля яго рэгістрацыі',
      inviteAuthor:'Запрасіць аўтара', achievements:'Дасягненні', firstAuthor:'Першы аўтар',
      authorMilestone:'{count} аўтараў', achievementCount:'{count} з {total}',
      achieved:'Дасягнута', allAchievements:'Усе дасягненні',
      levelRules:'Як лічацца ўзровень і стаўка',
      levelHelp:'Для ўзроўню ўлічваюцца ўнікальныя пацверджаныя Instagram-профілі асабіста запрошаных аўтараў.'
    },
    uz: {
      levelNames: {0:'Boshlanish',100:'Bronza',200:'Kumush',400:'Oltin'},
      partnerLevel:'Hamkorlik darajangiz', confirmedAuthors:'Tasdiqlangan mualliflar',
      towardLevel:'Keyingi daraja: {level}', remainingAuthors:'Yana {count} muallifni tasdiqlash kerak',
      standardCreatorRate:'Muallif ro‘yxatdan o‘tganidan keyingi birinchi yildagi standart stavka',
      inviteAuthor:'Muallifni taklif qilish', achievements:'Yutuqlar', firstAuthor:'Birinchi muallif',
      authorMilestone:'{count} muallif', achievementCount:'{total} dan {count}',
      achieved:'Erishildi', allAchievements:'Barcha yutuqlar',
      levelRules:'Daraja va stavka qanday hisoblanadi',
      levelHelp:'Daraja uchun bevosita taklif qilingan mualliflarning noyob tasdiqlangan Instagram profillari hisoblanadi.'
    }
  };
  Object.keys(levelCopy).forEach(function (lang) { Object.assign(copy[lang],levelCopy[lang]); });

  function levelText(template, values) {
    return template.replace(/\{(\w+)\}/g,function (_, key) { return String(values[key]); });
  }

  function levelName(threshold, c) {
    return c.levelNames[threshold] || levelText(c.authorMilestone,{count:threshold});
  }

  function levelData(data) {
    var grade = data.grade;
    if (!grade || !Number.isSafeInteger(grade.verified_creators) || grade.verified_creators < 0) return null;
    var next = grade.next_threshold;
    var progress = next == null ? 100 : (grade.verified_creators - grade.threshold) / (next - grade.threshold) * 100;
    return {
      count:grade.verified_creators,
      threshold:grade.threshold,
      next:next,
      remaining:grade.remaining,
      progress:Math.max(0,Math.min(100,progress)),
      rate:grade.tier_rate_bps
    };
  }

  function achievementMilestones(data) {
    var thresholds = [1,10,25,50];
    data.standards.creator_tiers.forEach(function (tier) {
      if (tier.threshold > 0 && thresholds.indexOf(tier.threshold) < 0) thresholds.push(tier.threshold);
    });
    return thresholds.sort(function (a,b) { return a-b; });
  }

  function achievementName(threshold, c) {
    return threshold === 1 ? c.firstAuthor : levelName(threshold,c);
  }

  function renderLevel(parent, data, compact) {
    var c = words();
    var level = levelData(data);
    parent.replaceChildren();
    if (!level) {
      parent.appendChild(node('p',c.unavailable,'umc-partner-note'));
      return;
    }
    var heading = node('div','','umc-partner-level-heading');
    var title = node('h2',c.partnerLevel,'umc-partner-level-label');
    var name = node('p',levelName(level.threshold,c),'umc-display umc-partner-level-name');
    var count = node('p',c.confirmedAuthors + ' · ' + level.count,'umc-partner-level-count');
    if (!compact) {
      title.id = 'partner-grade-title';
      count.id = 'partner-grade-count';
    }
    var identity = node('div');
    identity.append(title,name,count);
    var emblem = node('span','★','umc-partner-level-emblem');
    emblem.setAttribute('aria-hidden','true');
    heading.append(identity,emblem);
    parent.appendChild(heading);

    var progress = node('div','','umc-partner-level-progress');
    var progressTitle = node('p',level.next == null ? c.top : levelText(c.towardLevel,{level:levelName(level.next,c)}));
    var remaining = node('p',level.next == null ? '' : levelText(c.remainingAuthors,{count:level.remaining}),'umc-partner-level-remaining');
    if (!compact) remaining.id = 'partner-grade-next';
    var track = node('div','','umc-partner-level-track');
    track.setAttribute('role','progressbar');
    track.setAttribute('aria-label',c.partnerLevel);
    track.setAttribute('aria-valuemin','0');
    track.setAttribute('aria-valuemax','100');
    track.setAttribute('aria-valuenow',String(level.progress));
    track.setAttribute('aria-valuetext',progressTitle.textContent + ' · ' + (remaining.textContent || count.textContent));
    var fill = node('span','','umc-partner-level-fill');
    fill.style.width = level.progress + '%';
    track.appendChild(fill);
    var endpoints = node('div','','umc-partner-level-endpoints');
    endpoints.append(
      node('span',level.threshold + ' · ' + levelName(level.threshold,c)),
      node('span',level.next == null ? '' : level.next + ' · ' + levelName(level.next,c))
    );
    progress.append(progressTitle,remaining,track,endpoints);
    parent.appendChild(progress);

    var rate = node('div','','umc-partner-level-rate');
    var rateValue = node('span',percentage(level.rate),'umc-partner-rate');
    if (!compact) rateValue.id = 'partner-grade-value';
    rate.append(rateValue,node('p',c.standardCreatorRate));
    parent.appendChild(rate);
    linkControls(parent,safeUrl(data.referral.link),c,false,true);

    if (compact) {
      var milestones = achievementMilestones(data);
      var earned = milestones.filter(function (threshold) { return threshold <= level.count; }).length;
      var achievements = node('button',c.allAchievements + ' · ' + levelText(c.achievementCount,{count:earned,total:milestones.length}),'umc-btn umc-btn--ghost umc-btn--sm umc-btn--block');
      achievements.type = 'button';
      achievements.dataset.partnerOpen = '';
      achievements.addEventListener('click',function () {
        state.focusAchievements = true;
        open();
      });
      parent.appendChild(achievements);
    } else {
      var rules = node('details','','umc-partner-level-rules');
      rules.append(node('summary',c.levelRules),node('p',c.levelHelp),node('p',c.rules));
      parent.appendChild(rules);
    }
  }

  function renderAchievements(parent, data) {
    var c = words();
    var level = levelData(data);
    parent.replaceChildren();
    if (!level) return;
    var milestones = achievementMilestones(data);
    var earned = milestones.filter(function (threshold) { return threshold <= level.count; }).length;
    var heading = node('div','','umc-partner-achievements-heading');
    var title = node('h2',c.achievements);
    title.id = 'partner-achievements-title';
    heading.append(title,node('span',levelText(c.achievementCount,{count:earned,total:milestones.length})));
    var list = node('ul','','umc-partner-achievements');
    var detail = node('p','','umc-partner-achievement-detail');
    detail.setAttribute('aria-live','polite');
    var next = milestones.find(function (threshold) { return threshold > level.count; });
    milestones.forEach(function (threshold) {
      var reached = level.count >= threshold;
      var description = achievementName(threshold,c) + ' · ' + (reached ? c.achieved : levelText(c.remainingAuthors,{count:threshold-level.count}));
      var item = node('li');
      var button = node('button','','umc-partner-achievement');
      button.type = 'button';
      button.dataset.threshold = threshold;
      button.dataset.achieved = String(reached);
      button.setAttribute('aria-pressed',String(threshold === next || (next == null && threshold === milestones[milestones.length-1])));
      button.setAttribute('aria-label',description);
      var mark = node('span',reached ? '✓' : '◇','umc-partner-achievement-mark');
      mark.setAttribute('aria-hidden','true');
      button.append(mark,node('span',achievementName(threshold,c)));
      button.addEventListener('click',function () {
        list.querySelectorAll('button').forEach(function (other) { other.setAttribute('aria-pressed',String(other === button)); });
        detail.textContent = description;
      });
      if (button.getAttribute('aria-pressed') === 'true') detail.textContent = description;
      item.appendChild(button);
      list.appendChild(item);
    });
    parent.append(heading,list,detail);
  }

  function externalLink(url, label) {
    var link = node('a',label);
    link.href = url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    return link;
  }

  function linkControls(card, url, c, cabinet, inviteOnly) {
    if (!url) {
      card.appendChild(node('p',c.noLink,'umc-partner-note'));
      return;
    }

    var row = node('div','',inviteOnly ? 'umc-partner-invite' : 'umc-partner-link-row');
    var link = externalLink(url,url);
    link.hidden = Boolean(inviteOnly);
    link.dataset.partnerLink = '';
    link.title = url;
    var input = node('input');
    input.type = 'text';
    input.readOnly = true;
    input.hidden = true;
    input.setAttribute('aria-label',c.link);
    var button = node('button',inviteOnly ? c.inviteAuthor : c.copyShort,inviteOnly ? 'umc-btn umc-btn--primary umc-btn--block' : 'btn umc-partner-copy');
    button.type = 'button';
    button.dataset.partnerCopy = '';
    button.setAttribute('aria-label',inviteOnly ? c.inviteAuthor : c.copy);
    var status = node('p','','umc-partner-copy-status');
    status.setAttribute('role','status');
    if (cabinet) {
      link.id = 'partner-link';
      input.id = 'partner-link-value';
      button.id = 'btn-partner-copy';
      status.id = 'partner-copy-status';
    }
    row.append(link,input,button);
    card.append(row,status);

    var copyAttempt = 0;
    button.addEventListener('click',async function () {
      if (!current()) return;
      var bound = state.bound;
      var attempt = ++copyAttempt;
      var copied = false;
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(url);
          copied = true;
        }
      } catch (_) {
        // Some in-app browsers deny clipboard access even in a secure context.
      }
      if (attempt !== copyAttempt || bound !== state.bound || !button.isConnected || !current()) return;
      if (!copied) {
        input.value = url;
        input.hidden = false;
        link.hidden = true;
        input.focus();
        input.select();
        input.setSelectionRange(0,url.length);
        try { copied = document.execCommand('copy'); } catch (_) {}
      }
      if (copied && !input.hidden) {
        input.hidden = true;
        link.hidden = Boolean(inviteOnly);
        button.focus();
      }
      button.textContent = copied ? c.copiedShort : inviteOnly ? c.inviteAuthor : c.copyShort;
      status.textContent = copied ? c.copied : c.manual;
    });
  }

  function summaryMoney(value, currency) {
    if (value == null) return '—';
    return money(value,currency === 'RUB' ? '₽' : currency).replace(',00\u00a0','\u00a0');
  }

  function metric(parent, key, label, value) {
    var item = node('div','','umc-partner-metric');
    item.dataset.partnerMetric = key;
    item.append(node('dt',label),node('dd',value == null ? '—' : value));
    parent.appendChild(item);
  }

  function renderOverview(card, data, c, message) {
    if (card.parentElement.id === 'screen-manager-orders') {
      card.className = 'umc-card umc-card--mint umc-partner-level umc-partner-level--compact';
      if (data) renderLevel(card,data,true);
      else card.replaceChildren(node('p',message,'umc-partner-level-loading'));
      return;
    }
    var cabinet = card.id === 'partner-overview';
    var header = node('div','','umc-partner-overview-header');
    header.appendChild(node('h2',cabinet ? c.link : c.entry));
    card.replaceChildren(header);
    if (data) {
      var status = node('span',c[data.account_status] || c.unknown,'umc-partner-status');
      status.dataset.state = data.account_status;
      status.title = c.account;
      if (cabinet) status.id = 'partner-status';
      header.appendChild(status);
      linkControls(card,safeUrl(data.referral.link),c,cabinet);

      var financial = data.financial;
      var earnings = financial.earnings || {};
      var stats = node('dl','','umc-partner-metrics');
      metric(stats,'invited',c.invited,data.network.total);
      metric(stats,'managers',c.managers,data.network.manager_total);
      metric(stats,'referral',c.referralEarned,summaryMoney(earnings.referral_minor,financial.currency));
      metric(stats,'management',c.managementEarned,summaryMoney(earnings.management_minor,financial.currency));
      card.appendChild(stats);

      if (financial.state === 'mismatch' || financial.state === 'unavailable') {
        card.appendChild(node('p',c.earningsUnavailable,'umc-partner-note'));
      }
      var legacy = Object.entries(financial.legacy_referral_income_minor || {});
      if (legacy.length) {
        var earlier = node('p','','umc-partner-legacy');
        var amounts = legacy.map(function (entry) { return summaryMoney(entry[1],entry[0]); });
        earlier.append(node('span',c.legacy),node('strong',amounts.join(' · ')));
        card.appendChild(earlier);
      }
    } else {
      var loading = node('p',message,'umc-partner-note');
      loading.setAttribute('role','status');
      card.appendChild(loading);
    }

    if (!cabinet) {
      var entry = node('button',c.openCabinet,'btn btn-secondary umc-partner-entry');
      entry.type = 'button';
      entry.dataset.partnerOpen = '';
      var rates = data && (data.current_rates || {
        client_bps:data.standards ? data.standards.client_first_year_bps : 1000,
        creator_bps:data.grade.tier_rate_bps
      });
      if (rates) {
        entry.dataset.partnerRate = '';
        entry.appendChild(node('span',c.creator + ' ' + percentage(rates.creator_bps) + ' · ' + c.client + ' ' + percentage(rates.client_bps),'umc-partner-entry-rates'));
      }
      entry.addEventListener('click',open);
      card.appendChild(entry);
      if (rates && rates.overrides) {
        rates.overrides.forEach(function (rate) {
          var terms = (c[rate.side] || rate.side) + ' ' + percentage(rate.rate_bps);
          card.appendChild(node('p',terms + ' · ' + c.override + ' · ' + rate.policy_version,'umc-partner-note'));
        });
      }
    }

    if (data) {
      var help = node('div','','umc-partner-help');
      var links = node('div','','umc-partner-help-links');
      links.append(
        externalLink('https://usemycontent.ru/referral/',c.terms),
        externalLink('https://usemycontent.ru/partner',c.managerProgram)
      );
      help.append(node('p',c.how),links);
      card.appendChild(help);
    }
  }

  function showHomes(data, message) {
    var c = words();
    if (data) state.actor = data.actor_id;
    homes.forEach(function (card) { renderOverview(card,data,c,message); });
  }
  function partnerDetails(data) {
    var c=words(), rows=id('partner-network').querySelectorAll('.umc-partner-row');
    data.network.members.forEach(function(member,index){
      var row=rows[index];if(!row)return;
      if(member.display_name)row.querySelector('h3').textContent=member.display_name;
      if(member.telegram_username){var handle=member.telegram_username.replace(/^@/,'');var el=node(/^[a-zA-Z0-9_]{5,32}$/.test(handle)?'a':'span','@'+handle);if(el.tagName==='A'){el.href='https://t.me/'+handle;el.target='_blank';el.rel='noopener noreferrer';}row.appendChild(el);}
      if(member.work)row.appendChild(node('p',c.activeOrders+': '+member.work.active_orders+' · '+c.completedWorks+': '+member.work.completed_works,'hint'));
    });
    var parent=id('partner-balances');
    var summary=node('p','','umc-partner-notice');summary.id='partner-management-summary';
    var manager=data.financial.management_summary;
    if(manager)summary.textContent=c.successful+': '+manager.successful_works+' × '+money(manager.unit_minor,'RUB')+' = '+money(manager.gross_minor,'RUB')+'. '+c.beforeAdjustments;
    parent.appendChild(summary);
    var pending=node('section');pending.id='partner-pending';
    if(data.financial.pending && data.financial.pending.entries.length){pending.appendChild(node('h3',c.waiting));data.financial.pending.entries.forEach(function(entry){
      var row=node('article','','umc-partner-row');row.appendChild(node('p',(c[entry.kind]||entry.kind)+' · '+money(entry.amount_minor,'RUB')));row.appendChild(node('p',entry.order_id,'umc-partner-reference'));row.appendChild(node('p',c[entry.reason]||c.assessment_pending));
      (entry.waiting_for||[]).forEach(function(party){row.appendChild(node('p',(c[party.role]||party.role)+(party.display_name?' · '+party.display_name:'')+(party.telegram_username?' · @'+party.telegram_username.replace(/^@/,''):'')));});
      if(entry.due_at)row.appendChild(node('p',c.due+': '+date(entry.due_at),'hint'));pending.appendChild(row);
    });}
    parent.appendChild(pending);
  }

  var adminState={pending:null,review:null,busy:false};
  function adminWords(){return (window._me||{}).locale==='en'?{
    title:'Individual referral rates',recipient:'Partner ID',policy:'Published policy version',side:'Transaction side',action:'Action',create:'Create',supersede:'Replace',revoke:'Revoke',rate:'Rate, %',from:'Effective from · ISO with timezone',until:'Effective until · ISO with timezone',reason:'Agreement / reason',oid:'Existing override ID',version:'Current version',review:'Review decision',confirm:'Confirm decision',cancel:'Cancel review',list:'Load history for this scope',saved:'Saved',unknown:'Result unknown. Retry the original operation.',retry:'Retry original operation',invalid:'Check identity, dates, rate and reason.',storage:'Safe operation storage is unavailable. Reopen this section.',author:'Approved by',history:'History',notice:'Only future operations use these terms. Historical payment snapshots are preserved.'
  }:{
    title:'Индивидуальные реферальные ставки',recipient:'ID партнёра',policy:'Версия опубликованных условий',side:'Сторона сделки',action:'Действие',create:'Создать',supersede:'Заменить',revoke:'Отозвать',rate:'Ставка, %',from:'Действует с · ISO с часовым поясом',until:'Действует до · ISO с часовым поясом',reason:'Соглашение / причина',oid:'ID существующей ставки',version:'Текущая версия',review:'Проверить решение',confirm:'Подтвердить решение',cancel:'Отменить проверку',list:'Загрузить историю этих условий',saved:'Сохранено',unknown:'Результат неизвестен. Повторите исходную операцию.',retry:'Повторить исходную операцию',invalid:'Проверьте ID, даты, ставку и причину.',storage:'Безопасное сохранение операции недоступно. Откройте раздел заново.',author:'Утвердил',history:'История',notice:'Условия применяются к будущим операциям. Снимки уже оплаченных заказов сохраняются.'
  };}
  function adminKey(){return 'umc:partner-overrides:v1:'+(window.__miniapp_platform||'telegram')+':'+state.actor;}
  function adminStatus(message){var el=id('override-status');if(el)el.textContent=message;}
  function adminButton(parent,label,name,action){var button=node('button',label,'btn btn-secondary');button.type='button';button.id=name;button.addEventListener('click',action);parent.appendChild(button);return button;}
  function adminField(form,label,name,type,choices){
    var title=node('label',label);title.htmlFor=name;form.appendChild(title);
    var input=node(choices?'select':type==='textarea'?'textarea':'input');input.id=name;
    if(choices)choices.forEach(function(choice){var option=node('option',choice[1]);option.value=choice[0];input.appendChild(option);});
    else if(type!=='textarea')input.type=type||'text';
    input.maxLength=name==='override-reason'?4000:256;form.appendChild(input);return input;
  }
  function adminAllowed(){return current()&&state.data&&state.data.capabilities&&state.data.capabilities.manage_overrides===true&&!adminState.busy;}
  function validPending(value){
    return value&&['create','supersede','revoke'].indexOf(value.action)>=0&&typeof value.operation_key==='string'&&typeof value.reason==='string'&&typeof value.recipient_id==='string'&&['client','creator'].indexOf(value.side)>=0&&typeof value.policy_version==='string';
  }
  function renderAdmin(data){
    var old=id('partner-override-admin');if(old)old.remove();
    if(!data.capabilities||data.capabilities.manage_overrides!==true)return;
    var c=adminWords(),panel=node('section','','umc-partner-row');panel.id='partner-override-admin';panel.appendChild(node('h2',c.title));panel.appendChild(node('p',c.notice,'hint'));
    var status=node('p');status.id='override-status';status.setAttribute('role','status');panel.appendChild(status);
    try{var retained=sessionStorage.getItem(adminKey());if(retained){var parsed=JSON.parse(retained);if(!validPending(parsed))throw new Error();adminState.pending=parsed;}}
    catch(_){status.textContent=c.storage;id('partner-content').appendChild(panel);return;}
    var form=node('form');form.id='override-form';
    adminField(form,c.recipient,'override-recipient');adminField(form,c.policy,'override-policy');
    adminField(form,c.side,'override-side',null,[['client',words().client],['creator',words().creator]]);
    adminField(form,c.action,'override-action',null,[['create',c.create],['supersede',c.supersede],['revoke',c.revoke]]);
    adminField(form,c.rate,'override-rate');adminField(form,c.from,'override-from');adminField(form,c.until,'override-until');
    adminField(form,c.reason,'override-reason','textarea');adminField(form,c.oid,'override-id');adminField(form,c.version,'override-version');
    var review=adminButton(form,c.review,'override-review',function(){form.requestSubmit();});
    form.addEventListener('submit',reviewOverride);
    adminButton(form,c.list,'override-list',listOverrides);panel.appendChild(form);
    var decision=node('section');decision.id='override-decision';decision.hidden=true;panel.appendChild(decision);
    var historyPanel=node('section');historyPanel.id='override-history';panel.appendChild(historyPanel);
    id('partner-content').appendChild(panel);
    if(adminState.pending){form.hidden=true;adminStatus(c.unknown);adminButton(panel,c.retry,'override-retry',sendOverride);}
  }
  function overrideValue(name){return id('override-'+name).value.trim();}
  function overrideTime(value){if(!/(Z|[+-]\d{2}:\d{2})$/.test(value))throw new Error();var dateValue=new Date(value);if(isNaN(dateValue.getTime()))throw new Error();return dateValue.toISOString();}
  function overrideScope(){
    var recipient=overrideValue('recipient'),policy=overrideValue('policy'),side=overrideValue('side');
    if(!/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(recipient)||!policy)throw new Error();
    return {recipient_id:recipient,policy_version:policy,side:side};
  }
  function reviewOverride(event){
    event.preventDefault();if(!adminAllowed()||adminState.pending)return;
    var c=adminWords(),command;
    try{
      command=overrideScope();command.action=overrideValue('action');command.reason=overrideValue('reason');if(!command.reason)throw new Error();
      if(!window.crypto||!crypto.getRandomValues)throw new Error();var random=new Uint8Array(16);crypto.getRandomValues(random);command.operation_key='override:'+Array.from(random).map(function(n){return n.toString(16).padStart(2,'0');}).join('');
      if(command.action!=='create'){command.override_id=overrideValue('id');command.expected_version=Number(overrideValue('version'));if(!command.override_id||!Number.isSafeInteger(command.expected_version)||command.expected_version<1)throw new Error();}
      if(command.action==='revoke'){command.effective_at=overrideTime(overrideValue('from'));}
      else{var rate=overrideValue('rate');if(!/^\d{1,3}(\.\d{1,2})?$/.test(rate))throw new Error();command.rate_bps=Math.round(Number(rate)*100);if(command.rate_bps<1||command.rate_bps>10000)throw new Error();command.effective_from=overrideTime(overrideValue('from'));command.effective_until=overrideTime(overrideValue('until'));if(command.effective_from>=command.effective_until)throw new Error();}
    }catch(_){adminStatus(c.invalid);return;}
    adminState.review=command;var panel=id('override-decision');panel.hidden=false;panel.replaceChildren(node('p',(c[command.action]||command.action)+' · '+command.recipient_id+' · '+words()[command.side]+' · '+(command.rate_bps?percentage(command.rate_bps):'')+' · '+command.policy_version));
    panel.appendChild(node('p',(command.effective_at||command.effective_from)+(command.effective_until?' — '+command.effective_until:'')));panel.appendChild(node('p',command.reason));
    adminButton(panel,c.confirm,'override-confirm',function(){if(!adminAllowed()||adminState.pending)return;try{sessionStorage.setItem(adminKey(),JSON.stringify(adminState.review));}catch(_){adminStatus(c.storage);return;}adminState.pending=adminState.review;adminState.review=null;id('override-form').hidden=true;panel.hidden=true;sendOverride();});
    adminButton(panel,c.cancel,'override-cancel',function(){adminState.review=null;panel.hidden=true;});
  }
  function sendOverride(){
    if(!adminAllowed()||!adminState.pending)return;
    var command=adminState.pending,bound=state.bound;adminState.busy=true;adminStatus(words().loading);
    bound.request('/admin/rate-overrides/command',command).then(function(result){
      if(bound!==state.bound||!current())return;
      if(result.operation_key!==command.operation_key)throw new Error('unconfirmed');
      sessionStorage.removeItem(adminKey());adminState.pending=null;adminState.busy=false;
      var retry=id('override-retry');if(retry)retry.remove();id('override-form').hidden=false;adminStatus(adminWords().saved);listOverrides();
    }).catch(function(error){
      if(bound!==state.bound||!current())return;adminState.busy=false;
      if(error.status===401||error.status===403){clearPrivate();text('partner-error',words().forbidden);return;}
      adminStatus(adminWords().unknown);if(!id('override-retry'))adminButton(id('partner-override-admin'),adminWords().retry,'override-retry',sendOverride);
    });
  }
  function listOverrides(){
    if(!adminAllowed()||adminState.pending)return;var scope;try{scope=overrideScope();}catch(_){adminStatus(adminWords().invalid);return;}
    var bound=state.bound;adminState.busy=true;
    bound.request('/admin/rate-overrides/list',scope).then(function(rows){
      if(bound!==state.bound||!current())return;
      var parent=id('override-history');parent.replaceChildren(node('h3',adminWords().history));
      rows.forEach(function(value){var a=value.approval,row=node('article','','umc-partner-row');row.appendChild(node('p',percentage(a.rate_bps)+' · '+date(a.effective_from)+' — '+date(a.effective_until)));row.appendChild(node('p',a.reason));row.appendChild(node('p',adminWords().author+': '+a.approved_by,'umc-partner-reference'));row.appendChild(node('p',(value.revoked_at?date(value.revoked_at):'')+' · v'+value.version,'hint'));adminButton(row,adminWords().supersede,'override-select-'+a.override_id,function(){id('override-id').value=a.override_id;id('override-version').value=value.version;id('override-action').value='supersede';});parent.appendChild(row);});
    }).catch(function(error){if(bound===state.bound&&current()){if(error.status===401||error.status===403)clearPrivate();else adminStatus(words().error);}}).finally(function(){adminState.busy=false;});
  }

  function viewRequest(bound) {
    return bound.request('/partner/view',{
      network_page:state.network_page,
      history_page:state.history_page,
      assignment_page:state.assignment_page
    });
  }

  function load() {
    if (state.busy || !bind()) return;
    var bound = state.bound;
    state.requestId++;
    localize();
    text('partner-error','');
    id('partner-content').hidden = true;
    busy(true);
    viewRequest(bound).then(function (data) {
      if (bound !== state.bound || !current()) return;
      state.data = data;
      render(data);
      showHomes(data);
      partnerDetails(data);
      renderAdmin(data);
      if (state.focusAchievements) {
        state.focusAchievements = false;
        id('partner-achievements').focus();
      }
    }).catch(function (error) {
      if (bound !== state.bound) return;
      if (error.status === 401 || error.status === 403) clearPrivate();
      text('partner-error',error.status === 401 ? words().session : error.status === 403 ? words().forbidden : words().error);
    }).finally(function () { busy(false); });
  }

  function open() { if (state.busy) return; var active=document.querySelector('.screen.active'); if (active && active!==screen) state.returnScreen=active.id; var url=new URL(location.href); url.searchParams.set('view','partner'); history.replaceState(null,'',url.href); bridge.showScreen(screen.id); state.opened=true; load(); }
  ['screen-role-choice','screen-advertiser-dashboard','screen-blogger-dashboard','screen-manager-orders'].forEach(function (name) {
    var parent = id(name);
    if (!parent) return;
    var card = node('section','','umc-partner-overview');
    card.dataset.partnerHome = '';
    parent.querySelector('h1').insertAdjacentElement('afterend',card);
    homes.push(card);
  });
  id('btn-partner-reload').addEventListener('click',load);
  id('btn-partner-back').addEventListener('click',function () { if (state.busy) return; var url=new URL(location.href); url.searchParams.delete('view'); history.replaceState(null,'',url.href); bridge.showScreen(state.returnScreen); });
  function ready() {
    localize();
    if (state.busy || !bind()) return;
    var bound = state.bound;
    showHomes(null,words().loading);
    var params = new URLSearchParams(location.search);
    if (!state.opened && params.get('view') === 'partner' && !params.has('assignment') && !params.has('assignment_id')) {
      open();
      return;
    }
    var requestId = ++state.requestId;
    viewRequest(bound).then(function (data) {
      if (bound === state.bound && requestId === state.requestId && current()) showHomes(data);
    }).catch(function (error) {
      if (bound !== state.bound || requestId !== state.requestId) return;
      if (error.status === 401 || error.status === 403) clearPrivate();
      else showHomes(null,words().error);
    });
  }
  document.addEventListener('visibilitychange',function(){if(state.bound)current();}); window.addEventListener('focus',function(){if(state.bound)current();});
  document.addEventListener('umc:app-ready',ready); if (window.__umcAppReady) ready();
})();

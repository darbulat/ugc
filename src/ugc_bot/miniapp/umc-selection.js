/* Own-client requested intake and immutable selection facts. No provider commands. */
(function () {
  'use strict';
  var bridge = window.__umcAppBridge;
  var intake = document.getElementById('screen-intake');
  var selection = document.getElementById('screen-selection');
  if (!bridge || !intake || !selection) return;
  var copy = {
    ru: { entry:'Подбор 30 авторов', title:'Заказ с подбором', policy:'Опубликованные условия', choose:'Выберите условия', product:'Ссылка на товар', brief:'Задание для авторов', honorarium:'Гонорар одному автору, руб.', direct:'Гонорар автору оплачивается напрямую и не входит в стоимость услуг платформы.', due:'Согласованный срок подбора', contact:'Ваш контакт для сопровождения', mode:'Как работать с заказом', self:'Самостоятельно', manager:'С сопровождением', all:'Сопровождение всех 30 позиций', positions:'Выберите позиции для сопровождения', leadHint:'Запрос на сопровождение создаётся до оплаты. Назначение и вознаграждение менеджера здесь не подтверждаются.', create:'Создать заказ с подбором', newOrder:'Создать ещё один заказ', saved:'Заказ сохранён', viewSelection:'Смотреть подбор', selectionTitle:'Подбор авторов', reload:'Обновить', back:'Назад', loading:'Загружаем сохранённые данные…', sending:'Сохраняем заказ…', paused:'Создание платных заказов временно приостановлено.', readPaused:'Финансовые операции приостановлены. Сохранённый подбор доступен для просмотра.', empty:'Для вашего аккаунта пока нет доступных опубликованных условий. Обратитесь в поддержку.', published:'Опубликованные условия', refund:'Длительность периода возврата', refundHint:'Начало периода и право на возврат определяются опубликованными условиями. Срок возврата здесь не рассчитывается.', hours:'ч.', minutes:'мин.', seconds:'сек.', preview:'Опубликованная стоимость услуг', base:'Подбор, 30 позиций', accompaniment:'Сопровождение выбранных позиций', total:'Итого услуги платформы', unpaid:'Запрос на сопровождение сохранён до оплаты. Этот результат не подтверждает оплату или назначение менеджера.', noLead:'Самостоятельное ведение. Сопровождение не запрошено.', uncertain:'Результат отправки пока неизвестен. Данные сохранены. Повторите проверку тем же запросом; новый заказ автоматически не создаётся.', retry:'Проверить тем же запросом', error:'Не удалось загрузить данные. Попробуйте обновить.', invalid:'Проверьте заполненные поля, срок и выбранные позиции.', forbidden:'Этот заказ или действие недоступны вашему аккаунту.', missing:'Заказ с подбором не найден.', session:'Откройте приложение заново, чтобы продолжить.', storage:'Не удалось сохранить запрос для безопасного повтора. Откройте приложение заново.', conflict:'Запрос уже использован с другими данными. Обратитесь в поддержку.', position:'Позиция', waiting:'Автор ещё не назначен', waitlist:'Ожидают назначения', current:'Текущий автор', history:'Ранее переданные контакты', fulfilled:'Первая подтверждённая передача по позиции', delivered:'Передача текущего контакта подтверждена', previous:'Предыдущее назначение', openWork:'Открыть сотрудничество', unknown:'Результат доставки неизвестен', unassigned:'Не назначено', ready:'Ожидает отправки', sendingState:'Отправляется', accepted:'Передача подтверждена', failed:'Передача не выполнена', obsolete:'Прежняя попытка доставки', refunded:'Возврат', cancelled:'Отменено', breakdown:'Состав сохранённого заказа', noPositions:'Позиции подбора пока отсутствуют.' },
    en: { entry:'Find 30 creators', title:'Create a selection order', policy:'Published terms', choose:'Choose terms', product:'Product link', brief:'Creator brief', honorarium:'Fee per creator, RUB', direct:'You pay the creator directly. This fee is excluded from platform services.', due:'Agreed selection due date', contact:'Your accompaniment contact', mode:'How to run the order', self:'Self-service', manager:'With accompaniment', all:'Accompany all 30 positions', positions:'Choose accompanied positions', leadHint:'This requests accompaniment before payment. It confirms no manager assignment or reward.', create:'Create selection order', newOrder:'Create another order', saved:'Order saved', viewSelection:'View selection', selectionTitle:'Creator selection', reload:'Refresh', back:'Back', loading:'Loading saved data…', sending:'Saving order…', paused:'New paid orders are temporarily paused.', readPaused:'Financial operations are paused. Saved selection remains available to view.', empty:'No eligible published terms are available for your account. Contact support.', published:'Published terms', refund:'Published refund period duration', refundHint:'The published terms govern when the period starts and eligibility. No refund deadline is calculated here.', hours:'hours', minutes:'minutes', seconds:'seconds', preview:'Published service schedule', base:'Selection, 30 positions', accompaniment:'Accompaniment for selected positions', total:'Total platform services', unpaid:'Accompaniment was requested before payment. This receipt confirms neither payment nor manager assignment.', noLead:'Self-service. No accompaniment requested.', uncertain:'The send result is unknown. Your request is saved. Check with the same request; no new order is submitted automatically.', retry:'Check with the same request', error:'Data could not be loaded. Try refreshing.', invalid:'Check the required fields, due date and selected positions.', forbidden:'This order or action is unavailable to your account.', missing:'Selection order not found.', session:'Reopen the app to continue.', storage:'The request could not be saved for a safe retry. Reopen the app.', conflict:'This request was used with different data. Contact support.', position:'Position', waiting:'No creator assigned yet', waitlist:'Waiting for assignment', current:'Current creator', history:'Previously delivered contacts', fulfilled:'First confirmed delivery for this position', delivered:'Current contact delivery confirmed', previous:'Previous assignment', openWork:'Open collaboration', unknown:'Delivery result unknown', unassigned:'Unassigned', ready:'Waiting to send', sendingState:'Sending', accepted:'Delivery confirmed', failed:'Delivery failed', obsolete:'Previous delivery attempt', refunded:'Refunded', cancelled:'Cancelled', breakdown:'Saved order components', noPositions:'No selection positions yet.' },
    kk: { entry:'30 авторды іріктеу', title:'Іріктеуге тапсырыс', policy:'Жарияланған шарттар', choose:'Шарттарды таңдаңыз', product:'Тауар сілтемесі', brief:'Авторларға тапсырма', honorarium:'Бір автордың ақысы, RUB', direct:'Автор ақысын тікелей төлейсіз. Ол платформа қызметтерінің құнына кірмейді.', due:'Келісілген іріктеу мерзімі', contact:'Сүйемелдеу үшін байланысыңыз', mode:'Тапсырыспен жұмыс істеу', self:'Өз бетінше', manager:'Сүйемелдеумен', all:'Барлық 30 позицияны сүйемелдеу', positions:'Сүйемелденетін позицияларды таңдаңыз', leadHint:'Сүйемелдеу өтінімі төлемге дейін жасалады. Менеджер тағайындауы мен сыйақы расталмайды.', create:'Іріктеуге тапсырыс жасау', newOrder:'Тағы бір тапсырыс жасау', saved:'Тапсырыс сақталды', viewSelection:'Іріктеуді көру', selectionTitle:'Авторларды іріктеу', reload:'Жаңарту', back:'Артқа', loading:'Сақталған деректер жүктелуде…', sending:'Тапсырыс сақталуда…', paused:'Жаңа ақылы тапсырыстар уақытша тоқтатылды.', readPaused:'Қаржы операциялары тоқтатылды. Сақталған іріктеуді көруге болады.', empty:'Аккаунтыңыз үшін қолжетімді жарияланған шарттар жоқ. Қолдауға хабарласыңыз.', published:'Жарияланған шарттар', refund:'Қайтару кезеңінің ұзақтығы', refundHint:'Кезеңнің басталуы мен қайтару құқығы жарияланған шарттармен анықталады. Мұнда қайтару мерзімі есептелмейді.', hours:'сағ.', minutes:'мин.', seconds:'сек.', preview:'Қызметтердің жарияланған құны', base:'Іріктеу, 30 позиция', accompaniment:'Таңдалған позицияларды сүйемелдеу', total:'Платформа қызметтерінің жиыны', unpaid:'Сүйемелдеу өтінімі төлемге дейін сақталды. Бұл нәтиже төлемді не менеджер тағайындауын растамайды.', noLead:'Өз бетінше жүргізу. Сүйемелдеу сұралмаған.', uncertain:'Жіберу нәтижесі белгісіз. Өтінім сақталды. Сол сұраумен тексеріңіз; жаңа тапсырыс автоматты жіберілмейді.', retry:'Сол сұраумен тексеру', error:'Деректер жүктелмеді. Жаңартып көріңіз.', invalid:'Міндетті өрістерді, мерзім мен позицияларды тексеріңіз.', forbidden:'Аккаунтыңызға бұл тапсырыс не әрекет қолжетімсіз.', missing:'Іріктеу тапсырысы табылмады.', session:'Жалғастыру үшін қолданбаны қайта ашыңыз.', storage:'Қауіпсіз қайталау үшін сұрау сақталмады. Қолданбаны қайта ашыңыз.', conflict:'Бұл сұрау басқа деректермен қолданылған. Қолдауға хабарласыңыз.', position:'Позиция', waiting:'Автор әлі тағайындалмаған', waitlist:'Тағайындауды күтуде', current:'Қазіргі автор', history:'Бұрын берілген байланыстар', fulfilled:'Позиция бойынша алғашқы расталған беру', delivered:'Қазіргі байланысты беру расталды', previous:'Бұрынғы тағайындау', openWork:'Ынтымақтастықты ашу', unknown:'Жеткізу нәтижесі белгісіз', unassigned:'Тағайындалмаған', ready:'Жіберуді күтуде', sendingState:'Жіберілуде', accepted:'Беру расталды', failed:'Жеткізу орындалмады', obsolete:'Бұрынғы жеткізу әрекеті', refunded:'Қайтарылды', cancelled:'Бас тартылды', breakdown:'Сақталған тапсырыс құрамы', noPositions:'Іріктеу позициялары әзірге жоқ.' },
    be: { entry:'Падбор 30 аўтараў', title:'Заказ з падборам', policy:'Апублікаваныя ўмовы', choose:'Выберыце ўмовы', product:'Спасылка на тавар', brief:'Заданне для аўтараў', honorarium:'Ганарар аднаму аўтару, RUB', direct:'Ганарар аўтару аплачваецца напрамую і не ўваходзіць у кошт паслуг платформы.', due:'Узгоднены тэрмін падбору', contact:'Ваш кантакт для суправаджэння', mode:'Як весці заказ', self:'Самастойна', manager:'З суправаджэннем', all:'Суправаджэнне ўсіх 30 пазіцый', positions:'Выберыце пазіцыі для суправаджэння', leadHint:'Запыт суправаджэння ствараецца да аплаты. Прызначэнне і ўзнагарода менеджара тут не пацвярджаюцца.', create:'Стварыць заказ з падборам', newOrder:'Стварыць яшчэ адзін заказ', saved:'Заказ захаваны', viewSelection:'Глядзець падбор', selectionTitle:'Падбор аўтараў', reload:'Абнавіць', back:'Назад', loading:'Загружаем захаваныя даныя…', sending:'Захоўваем заказ…', paused:'Стварэнне новых платных заказаў часова прыпынена.', readPaused:'Фінансавыя аперацыі прыпынены. Захаваны падбор даступны для прагляду.', empty:'Для вашага акаўнта няма даступных апублікаваных умоў. Звярніцеся ў падтрымку.', published:'Апублікаваныя ўмовы', refund:'Працягласць перыяду вяртання', refundHint:'Пачатак перыяду і права на вяртанне вызначаюць апублікаваныя ўмовы. Тэрмін вяртання тут не разлічваецца.', hours:'гадз.', minutes:'хв.', seconds:'сек.', preview:'Апублікаваны кошт паслуг', base:'Падбор, 30 пазіцый', accompaniment:'Суправаджэнне выбраных пазіцый', total:'Разам паслугі платформы', unpaid:'Запыт суправаджэння захаваны да аплаты. Гэты вынік не пацвярджае аплату ці прызначэнне менеджара.', noLead:'Самастойнае вядзенне. Суправаджэнне не запытана.', uncertain:'Вынік адпраўкі невядомы. Запыт захаваны. Праверце тым жа запытам; новы заказ аўтаматычна не ствараецца.', retry:'Праверыць тым жа запытам', error:'Не ўдалося загрузіць даныя. Паспрабуйце абнавіць.', invalid:'Праверце палі, тэрмін і выбраныя пазіцыі.', forbidden:'Гэты заказ або дзеянне недаступны вашаму акаўнту.', missing:'Заказ з падборам не знойдзены.', session:'Адкрыйце праграму зноў, каб працягнуць.', storage:'Не ўдалося захаваць запыт для бяспечнага паўтору. Адкрыйце праграму зноў.', conflict:'Запыт ужо ўжыты з іншымі данымі. Звярніцеся ў падтрымку.', position:'Пазіцыя', waiting:'Аўтар яшчэ не прызначаны', waitlist:'Чакаюць прызначэння', current:'Цяперашні аўтар', history:'Раней перададзеныя кантакты', fulfilled:'Першая пацверджаная перадача па пазіцыі', delivered:'Перадача цяперашняга кантакту пацверджана', previous:'Папярэдняе прызначэнне', openWork:'Адкрыць супрацоўніцтва', unknown:'Вынік дастаўкі невядомы', unassigned:'Не прызначана', ready:'Чакае адпраўкі', sendingState:'Адпраўляецца', accepted:'Перадача пацверджана', failed:'Перадача не выканана', obsolete:'Папярэдняя спроба дастаўкі', refunded:'Вяртанне', cancelled:'Скасавана', breakdown:'Склад захаванага заказу', noPositions:'Пазіцый падбору пакуль няма.' },
    uz: { entry:'30 muallifni tanlash', title:'Tanlov buyurtmasi', policy:'E’lon qilingan shartlar', choose:'Shartlarni tanlang', product:'Mahsulot havolasi', brief:'Mualliflar uchun topshiriq', honorarium:'Bir muallif haqi, RUB', direct:'Muallif haqini bevosita to‘laysiz. Bu haq platforma xizmatlari narxiga kirmaydi.', due:'Kelishilgan tanlov muddati', contact:'Hamrohlik uchun aloqangiz', mode:'Buyurtmani yuritish', self:'Mustaqil', manager:'Hamrohlik bilan', all:'Barcha 30 pozitsiyaga hamrohlik', positions:'Hamrohlik pozitsiyalarini tanlang', leadHint:'Hamrohlik so‘rovi to‘lovdan oldin yaratiladi. Menejer tayinlanishi va mukofoti tasdiqlanmaydi.', create:'Tanlov buyurtmasini yaratish', newOrder:'Yana buyurtma yaratish', saved:'Buyurtma saqlandi', viewSelection:'Tanlovni ko‘rish', selectionTitle:'Mualliflar tanlovi', reload:'Yangilash', back:'Orqaga', loading:'Saqlangan ma’lumotlar yuklanmoqda…', sending:'Buyurtma saqlanmoqda…', paused:'Yangi pulli buyurtmalar vaqtincha to‘xtatildi.', readPaused:'Moliyaviy amallar to‘xtatilgan. Saqlangan tanlovni ko‘rish mumkin.', empty:'Hisobingiz uchun mos e’lon qilingan shartlar yo‘q. Yordam xizmatiga murojaat qiling.', published:'E’lon qilingan shartlar', refund:'Qaytarish davri davomiyligi', refundHint:'Davr boshlanishi va qaytarish huquqi e’lon qilingan shartlar bilan belgilanadi. Qaytarish muddati bu yerda hisoblanmaydi.', hours:'soat', minutes:'daqiqa', seconds:'soniya', preview:'Xizmatlarning e’lon qilingan narxi', base:'Tanlov, 30 pozitsiya', accompaniment:'Tanlangan pozitsiyalarga hamrohlik', total:'Platforma xizmatlari jami', unpaid:'Hamrohlik so‘rovi to‘lovdan oldin saqlandi. Bu natija to‘lovni yoki menejer tayinlanishini tasdiqlamaydi.', noLead:'Mustaqil yuritish. Hamrohlik so‘ralmagan.', uncertain:'Yuborish natijasi noma’lum. So‘rov saqlandi. Ayni so‘rov bilan tekshiring; yangi buyurtma avtomatik yuborilmaydi.', retry:'Ayni so‘rov bilan tekshirish', error:'Ma’lumotlar yuklanmadi. Yangilab ko‘ring.', invalid:'Maydonlar, muddat va pozitsiyalarni tekshiring.', forbidden:'Bu buyurtma yoki amal hisobingizga ochiq emas.', missing:'Tanlov buyurtmasi topilmadi.', session:'Davom etish uchun ilovani qayta oching.', storage:'Xavfsiz qayta yuborish uchun so‘rov saqlanmadi. Ilovani qayta oching.', conflict:'So‘rov boshqa ma’lumot bilan ishlatilgan. Yordamga murojaat qiling.', position:'Pozitsiya', waiting:'Muallif hali tayinlanmagan', waitlist:'Tayinlashni kutmoqda', current:'Joriy muallif', history:'Avval yetkazilgan aloqalar', fulfilled:'Pozitsiyadagi ilk tasdiqlangan yetkazish', delivered:'Joriy aloqa yetkazilgani tasdiqlandi', previous:'Oldingi tayinlash', openWork:'Hamkorlikni ochish', unknown:'Yetkazish natijasi noma’lum', unassigned:'Tayinlanmagan', ready:'Yuborishni kutmoqda', sendingState:'Yuborilmoqda', accepted:'Yetkazish tasdiqlandi', failed:'Yetkazilmadi', obsolete:'Oldingi yetkazish urinishi', refunded:'Qaytarildi', cancelled:'Bekor qilindi', breakdown:'Saqlangan buyurtma tarkibi', noPositions:'Hozircha tanlov pozitsiyalari yo‘q.' }
  };
  var clientCopy = {
    ru:{entry:'Подобрать блогеров',base:'Подбор авторов',all:'Сопровождение всех авторов',count:'Количество авторов, от 10 до 200',image:'Изображение для задания',removeImage:'Удалить изображение',leadHint:'Менеджер согласует условия, проследит за сроками, соберёт материалы и статистику.',create:'Перейти к оплате',unpaid:'Сопровождение добавлено. Продолжите к оплате.'},
    en:{entry:'Find creators',base:'Creator selection',all:'Accompany every creator',count:'Number of creators, 10–200',image:'Brief image',removeImage:'Remove image',leadHint:'A manager coordinates terms, deadlines, materials and statistics.',create:'Continue to payment',unpaid:'Accompaniment added. Continue to payment.'},
    kk:{entry:'Авторларды іріктеу',base:'Авторларды іріктеу',all:'Барлық авторларды сүйемелдеу',count:'Автор саны, 10–200',image:'Тапсырма суреті',removeImage:'Суретті өшіру',leadHint:'Менеджер шарттарды, мерзімдерді, материалдар мен статистиканы бақылайды.',create:'Төлемге өту',unpaid:'Сүйемелдеу қосылды. Төлемге өтіңіз.'},
    be:{entry:'Падабраць аўтараў',base:'Падбор аўтараў',all:'Суправаджэнне ўсіх аўтараў',count:'Колькасць аўтараў, 10–200',image:'Выява задання',removeImage:'Выдаліць выяву',leadHint:'Менеджар узгодніць умовы, тэрміны, матэрыялы і статыстыку.',create:'Перайсці да аплаты',unpaid:'Суправаджэнне дададзена. Перайдзіце да аплаты.'},
    uz:{entry:'Mualliflarni tanlash',base:'Mualliflarni tanlash',all:'Barcha mualliflarga hamrohlik',count:'Mualliflar soni, 10–200',image:'Topshiriq rasmi',removeImage:'Rasmni o‘chirish',leadHint:'Menejer shartlar, muddatlar, materiallar va statistikani muvofiqlashtiradi.',create:'To‘lovga o‘tish',unpaid:'Hamrohlik qo‘shildi. To‘lovga o‘ting.'}
  };
  var paymentTogether={ru:'Подбор и выбранное сопровождение оплачиваются вместе в одном счёте.',en:'Creator selection and chosen management are paid together in one invoice.',kk:'Іріктеу мен таңдалған сүйемелдеу бір шотпен бірге төленеді.',be:'Падбор і выбранае суправаджэнне аплачваюцца разам у адным рахунку.',uz:'Tanlov va tanlangan hamrohlik bitta hisobda birga to‘lanadi.'};
  Object.keys(paymentTogether).forEach(function(locale){copy[locale].paymentTogether=paymentTogether[locale];});
  Object.keys(clientCopy).forEach(function(locale){Object.assign(copy[locale],clientCopy[locale]);});
  var state = { busy:false, policies:[], pending:null, pendingEntry:null, completedEntry:null, result:null, order:null, intakeBack:'screen-advertiser-dashboard', selectionBack:'screen-advertiser-dashboard', opened:false };
  var context=null,owner=null;
  function binding(){if(!context)context=bridge.createRequestContext();return context;}
  function id(name) { return document.getElementById(name); }
  function words() { return copy[(window._me || {}).locale] || copy.ru; }
  function node(tag, content, className) { var el=document.createElement(tag); el.textContent=content == null ? '' : String(content); if(className) el.className=className; return el; }
  var submittedCopy={ru:['Этот черновик уже отправлен. Откройте заказ в списке или начните новый.','Использовать как новый заказ'],en:['This draft was already submitted. Open your order list or start a new order.','Use as a new order'],kk:['Бұл жоба жіберілген. Тапсырыстар тізімін ашыңыз немесе жаңасын бастаңыз.','Жаңа тапсырыс бастау'],be:['Гэты чарнавік ужо адпраўлены. Адкрыйце спіс заказаў або пачніце новы.','Пачаць новы заказ'],uz:['Bu qoralama yuborilgan. Buyurtmalar ro‘yxatini oching yoki yangisini boshlang.','Yangi buyurtma boshlash']};
  var freshDraft=node('button','','btn btn-secondary');freshDraft.type='button';freshDraft.id='btn-intake-fresh';freshDraft.hidden=true;id('intake-error').after(freshDraft);
  function submittedWords(){return submittedCopy[(window._me||{}).locale]||submittedCopy.en;}
  function showSubmitted(){text('intake-error',submittedWords()[0]);freshDraft.textContent=submittedWords()[1];freshDraft.hidden=false;}
  freshDraft.addEventListener('click',function(){
    var ctx=binding(),progress=window.UMCIntakeProgress;if(state.busy||!ctx.isCurrent()){text('intake-error',words().session);return;}
    try{if(progress&&!progress.startNew())throw new Error('storage_unavailable');}catch(_){text('intake-error',words().storage);return;}
    freshDraft.hidden=true;text('intake-error','');preview();
  });
  function text(name, value) { id(name).textContent=value || ''; }
  function sync() { if(window.UMCShell) window.UMCShell.syncControls(); }
  function validId(value) { return typeof value==='string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value) && !/^0{8}-0{4}-0{4}-0{4}-0{12}$/.test(value); }
  function safeUrl(value) { try { var url=new URL(value); return url.protocol==='https:' && !url.username && !url.password ? url.href : null; } catch(_) { return null; } }
  function money(value, currency) { var raw=String(value); if(!/^\d+$/.test(raw) || (typeof value==='number' && !Number.isSafeInteger(value))) return words().unknown; raw=raw.padStart(3,'0'); return raw.slice(0,-2).replace(/\B(?=(\d{3})+(?!\d))/g,'\u00a0') + ',' + raw.slice(-2) + '\u00a0' + (currency==='RUB' && (window._me || {}).locale==='ru' ? 'руб.' : currency); }
  function date(value) { var d=new Date(value); return value && !isNaN(d.getTime()) ? d.toISOString().replace('T',' ').slice(0,16)+' UTC' : words().unknown; }
  function localize() {
    document.querySelectorAll('[data-intake-copy]').forEach(function(el) { el.textContent=words()[el.dataset.intakeCopy] || ''; });
    var entry=id('btn-show-create-order'); if(entry) entry.textContent=words().entry;freshDraft.textContent=submittedWords()[1];
    document.querySelectorAll('[data-selection-open]').forEach(function(el) { el.textContent=words().viewSelection; });
    dueLabel(); targetLocalize();var hints={ru:'до 5 МБ (5 000 000 байт)',en:'up to 5 MB (5 000 000 bytes)',kk:'5 МБ дейін (5 000 000 байт)',be:'да 5 МБ (5 000 000 байт)',uz:'5 MB gacha (5 000 000 bayt)'};text('intake-image-hint','JPEG, 1080 × 1080 px, '+(hints[(window._me||{}).locale]||hints.en));
  }
  function dueLabel() { var d=new Date(id('intake-due').value || Date.now()); var offset=-d.getTimezoneOffset(), sign=offset>=0?'+':'-'; var zone=Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'; text('intake-due-label',words().due+' ('+zone+', UTC'+sign+String(Math.floor(Math.abs(offset)/60)).padStart(2,'0')+':'+String(Math.abs(offset)%60).padStart(2,'0')+')'); }
  function row(parent, label, value, valueId, minor) { var line=node('div'), dt=node('dt',label), dd=node('dd',value); if(valueId) dd.id=valueId; if(minor != null) dd.dataset.minor=String(minor); line.append(dt,dd); parent.appendChild(line); }
  function link(parent, value, label) { var url=safeUrl(value), el=node(url?'a':'span',url?(label || value):value); if(url) { el.href=url; el.target='_blank'; el.rel='noopener noreferrer'; } parent.appendChild(el); }
  var targetLabels={ru:['Фильтры авторов','Подписчиков от','Подписчиков до','Возраст от','Возраст до','Пол автора','Любой','Мужской','Женский'],en:['Creator filters','Followers from','Followers to','Age from','Age to','Creator gender','Any','Male','Female'],kk:['Автор сүзгілері','Жазылушылар саны бастап','Жазылушылар саны дейін','Жасы бастап','Жасы дейін','Автор жынысы','Кез келген','Ер','Әйел'],be:['Фільтры аўтараў','Падпісчыкі ад','Падпісчыкі да','Узрост ад','Узрост да','Пол аўтара','Любы','Мужчынскі','Жаночы'],uz:['Muallif filtrlari','Obunachilar kamida','Obunachilar ko‘pi bilan','Yosh kamida','Yosh ko‘pi bilan','Muallif jinsi','Istalgan','Erkak','Ayol']};
  var briefLabels={ru:['Город автора (точное совпадение)','Площадки (хотя бы одна)','Использование и формат контента','Ссылка на подробный бриф','Тип работы','Только UGC','UGC с размещением'],en:['Creator city (exact match)','Platforms (at least one)','Content use and format','Detailed brief link','Work type','UGC only','UGC with placement'],kk:['Автор қаласы (дәл сәйкестік)','Платформалар (кемінде біреу)','Контентті пайдалану және пішімі','Толық бриф сілтемесі','Жұмыс түрі','Тек UGC','Жарияланатын UGC'],be:['Горад аўтара (дакладнае супадзенне)','Пляцоўкі (хаця б адна)','Выкарыстанне і фармат кантэнту','Спасылка на падрабязны брыф','Тып працы','Толькі UGC','UGC з размяшчэннем'],uz:['Muallif shahri (aniq moslik)','Platformalar (kamida bittasi)','Kontentdan foydalanish va format','Batafsil brif havolasi','Ish turi','Faqat UGC','Joylashtirish bilan UGC']};
  Object.keys(targetLabels).forEach(function(locale){targetLabels[locale]=targetLabels[locale].concat(briefLabels[locale]);});
  var targetFields=['min_followers','max_followers','min_age','max_age'];
  function targeting() { var result={}, any=false;targetFields.forEach(function(name){var value=id('intake-'+name).value;result[name]=value===''?null:Number(value);if(value!=='')any=true;});result.gender=id('intake-gender').value||null;['city','content_usage','brief_link'].forEach(function(name){var value=id('intake-'+name).value.trim();if(value){result[name]=value;any=true;}});var platforms=Array.from(document.querySelectorAll('[data-intake-platform]:checked')).map(function(el){return el.value;});if(platforms.length){result.platforms=platforms;any=true;}return any||result.gender?result:null; }
  function targetLocalize(){var c=targetLabels[(window._me||{}).locale]||targetLabels.en;document.querySelectorAll('[data-target-copy]').forEach(function(el){el.textContent=c[Number(el.dataset.targetCopy)];});}
  function targetControls(){var box=node('fieldset'),title=node('legend');title.dataset.targetCopy='0';box.appendChild(title);targetFields.forEach(function(name,index){var label=node('label'),span=node('span'),input=document.createElement('input');span.dataset.targetCopy=String(index+1);input.id='intake-'+name;input.type='number';input.min='0';input.max=index<2?'2147483647':'120';input.step='1';input.inputMode='numeric';label.append(span,input);box.appendChild(label);});var label=node('label'),span=node('span'),select=document.createElement('select');span.dataset.targetCopy='5';select.id='intake-gender';['','m','f'].forEach(function(value,index){var option=node('option');option.value=value;option.dataset.targetCopy=String(index+6);select.appendChild(option);});label.append(span,select);box.appendChild(label);[['city',9,'text'],['content_usage',11,'text'],['brief_link',12,'url']].forEach(function(row){var label=node('label'),span=node('span'),input=document.createElement('input');span.dataset.targetCopy=String(row[1]);input.id='intake-'+row[0];input.type=row[2];input.maxLength=row[0]==='city'?200:row[0]==='brief_link'?2048:4000;label.append(span,input);box.appendChild(label);});var platforms=node('fieldset'),platformTitle=node('legend');platformTitle.dataset.targetCopy='10';platforms.appendChild(platformTitle);['instagram','tiktok','youtube','telegram','vk'].forEach(function(value){var label=node('label'),input=document.createElement('input');input.type='checkbox';input.id='intake-platform-'+value;input.value=value;input.dataset.intakePlatform='';label.append(input,node('span',value));platforms.appendChild(label);});box.appendChild(platforms);var formatLabel=node('label'),formatTitle=node('span'),format=document.createElement('select');formatTitle.dataset.targetCopy='13';format.id='intake-order-type';['ugc_only','ugc_plus_placement','stories'].forEach(function(value,index){var option=node('option');option.value=value;if(value==='stories')option.textContent=({ru:'Сторис',en:'Stories',kk:'Сторис',be:'Сторыс',uz:'Stories'})[(window._me||{}).locale]||'Stories';else option.dataset.targetCopy=String(14+index);format.appendChild(option);});formatLabel.append(formatTitle,format);box.appendChild(formatLabel);id('intake-contact').insertAdjacentElement('afterend',box);targetLocalize();}
  targetControls();
  function selectedPolicy() { return state.policies.find(function(p) { return p.version===id('intake-policy').value; }); }
  function selectedPositions() { if(document.querySelector('input[name="intake-mode"]:checked').value==='self_service') return []; if(id('intake-all-manager').checked) return null; return Array.from(id('intake-position-options').querySelectorAll('input:checked')).map(function(el) { return Number(el.value); }); }
  function preview() {
    var c=words(), p=selectedPolicy(), manager=document.querySelector('input[name="intake-mode"]:checked').value==='with_manager';
    id('intake-manager-options').hidden=!manager; id('intake-positions').hidden=!manager || id('intake-all-manager').checked;
    id('intake-terms').hidden=!p; id('intake-preview').hidden=!p;
    if(!p) return;
    var terms=id('intake-terms'); terms.replaceChildren(); link(terms,p.terms_reference,c.published); var seconds=Number(p.refund_window_seconds), unit=seconds%3600===0?3600:seconds%60===0?60:1;
    terms.appendChild(node('p',c.refund+': '+String(seconds/unit)+' '+(unit===3600?c.hours:unit===60?c.minutes:c.seconds))); terms.appendChild(node('p',c.refundHint,'hint'));
    var positions=selectedPositions(), count=positions===null?positionCount():positions.length;
    var parent=id('intake-preview'); parent.replaceChildren(); parent.appendChild(node('h2',c.preview)); var list=node('dl');
    row(list,c.base,money(p.selection_minor,p.currency)+' × '+positionCount());
    row(list,c.accompaniment,money(p.accompaniment_minor,p.currency)+' / '+c.position.toLowerCase()+' × '+count);
    if(manager) row(list,c.manager,money(Number(p.selection_minor)+Number(p.accompaniment_minor),p.currency)+' / '+c.position.toLowerCase());
    row(list,c.total,money(Number(p.selection_minor)*positionCount()+Number(p.accompaniment_minor)*count,p.currency)); parent.appendChild(list);if(manager&&count>0)parent.appendChild(node('p',c.paymentTogether,'hint'));
  }
  function storageKey() { var user=(window._me || {}).user_id; if(!validId(user)) throw new Error('missing_authenticated_identity'); return 'umc:intake:'+window.__miniapp_platform+':'+user; }
  function legacyPending(owner) { var raw=sessionStorage.getItem(owner); return raw?JSON.parse(raw):null; }
  function mirrorPending(owner,entry) { try { sessionStorage.setItem(owner,JSON.stringify({__umcIntakeMirror:1,payload:entry.payload,snapshot:entry.snapshot})); } catch(_) { /* IndexedDB is the recovery source. */ } }
  function restore(owner,ctx) {
    if(!window.UMCIntakeStore) return Promise.reject(new Error('storage_unavailable'));
    return window.UMCIntakeStore.pending(owner,legacyPending(owner),null).then(function(saved) {
      if(!ctx.isCurrent())return;
      state.pendingEntry=saved.entry;state.pending=saved.entry?saved.entry.payload:null;
      if(saved.entry) mirrorPending(owner,saved.entry);
      else { var old=legacyPending(owner);if(old)sessionStorage.removeItem(owner); }
    });
  }
  function clearMirror(owner,entry) {
    var saved=legacyPending(owner), payload=saved&&saved.__umcIntakeMirror===1?saved.payload:saved;
    if(payload && payload.operation_key===entry.payload.operation_key)sessionStorage.removeItem(owner);
  }
  function finishPending(owner,entry,outcome) {
    if(!window.UMCIntakeStore || !entry) return Promise.reject(new Error('storage_unavailable'));
    return window.UMCIntakeStore.retire(owner,entry,outcome).then(function(result) {
      if(!result.retained)clearMirror(owner,entry);
      return result;
    });
  }
  function busy(value, screen) { state.busy=value; screen.setAttribute('aria-busy',String(value)); screen.querySelectorAll('button,input,textarea,select').forEach(function(el) { el.disabled=value; }); sync(); }
  function failure(error, target) { var c=words(); text(target,error.status===401?c.session:error.status===403?c.forbidden:error.status===404?c.missing:error.status===409?c.conflict:c.error); }
  function pendingView() { id('form-umc-intake').hidden=true; id('intake-result').hidden=true; id('intake-uncertain').hidden=false; sync(); }
  function renderResult(result,entry) {
    document.dispatchEvent(new CustomEvent("umc:intake-created",{detail:{order_id:result.order_id,intent_id:entry.payload.funnel_id||null}}));
    var request=entry.payload;state.result=result; state.pending=null;state.pendingEntry=null;state.completedEntry=entry;
    document.dispatchEvent(new CustomEvent('umc:checkout-order',{detail:{order_id:result.order_id,target:'intake-result'}}));
    id('form-umc-intake').hidden=true; id('intake-uncertain').hidden=true; id('intake-result').hidden=false;
    text('intake-error',''); text('intake-order-id',[result.public_number,result.public_title||(request&&request.offer_text||'').split('\n')[0].slice(0,120)].filter(Boolean).join(' · '));
    var parent=id('intake-quote'); parent.replaceChildren(); var accompaniment=result.items.reduce(function(total,item) { return total+Number(item.accompaniment_minor); },0);
    row(parent,words().base+' · '+result.items.length,money(result.selection_base_minor,result.currency)); row(parent,words().accompaniment,money(accompaniment,result.currency)); row(parent,words().total,money(result.total_minor,result.currency),'intake-total',result.total_minor); row(parent,words().due,date(result.selection_due_at));
    text('intake-lead-state',result.lead_id?words().unpaid+' '+words().paymentTogether:words().noLead); id('intake-lead-state').dataset.state=result.lead_id?'requested_unpaid':'self_service';
    var previous=id('intake-components'); if(previous) previous.remove(); var details=node('details'); details.id='intake-components'; details.appendChild(node('summary',words().breakdown));
    result.items.forEach(function(item) { var total=Number(item.selection_minor)+Number(item.accompaniment_minor); var line=node('p',words().position+' '+item.ordinal+': '+money(item.selection_minor,result.currency)+' + '+money(item.accompaniment_minor,result.currency)+' = '+money(total,result.currency)); line.dataset.positionTotal=String(total); details.appendChild(line); }); id('intake-result').appendChild(details); sync();
  }
  function newOrder() {
    if(state.busy || !state.result || state.pending) return;
    var ctx=binding(),owner;
    if(!ctx.isCurrent()){text('intake-error',words().session);return;}
    try{owner=storageKey();}catch(_){text('intake-error',words().storage);return;}
    busy(true,intake);
    var progress=window.UMCIntakeProgress;
    (progress?progress.complete(state.completedEntry.snapshot):Promise.resolve()).then(function(){
      if(!ctx.isCurrent())return null;
      return finishPending(owner,state.completedEntry,'confirmed');
    }).then(function(result){
      if(!ctx.isCurrent()||!result)return;
      document.dispatchEvent(new CustomEvent('umc:checkout-order',{detail:{order_id:null,target:null}}));
      state.result=null;state.completedEntry=null; id('form-umc-intake').reset();positionOptions(); id('intake-result').hidden=true;
      text('intake-order-id',''); id('intake-quote').replaceChildren(); text('intake-lead-state',''); delete id('intake-lead-state').dataset.state;
      var details=id('intake-components'); if(details) details.remove();
      busy(false,intake);loadPolicies();
    }).catch(function(){if(ctx.isCurrent()){text('intake-error',words().storage);busy(false,intake);}});
  }
  function send(payload, isRetry) {
    if(state.busy || !state.pendingEntry) return;
    var ctx=binding(),entry=state.pendingEntry,owner;
    if(!ctx.isCurrent()){text('intake-error',words().session);return;}
    try{owner=storageKey();}catch(_){text('intake-error',words().storage);return;}
    text('intake-error',''); text('intake-loading',words().sending); busy(true,intake);
    window.UMCIntakeStore.beginSend(owner,entry,!!isRetry).then(function(status){
      if(!ctx.isCurrent())return null;
      if(!status.active){
        clearMirror(owner,entry);state.pending=null;state.pendingEntry=null;
        id('form-umc-intake').hidden=false;id('intake-uncertain').hidden=true;
        if(status.outcome==='confirmed')showSubmitted();else text('intake-error',words().invalid);
        return null;
      }
      return ctx.request('/financial/orders',payload);
    }).then(function(data){
      if(!ctx.isCurrent()||!data)return;
      return window.UMCIntakeStore.confirm(owner,entry).catch(function(){/* Keep the same key for recovery. */}).then(function(){
        if(!ctx.isCurrent())return;
        var progress=window.UMCIntakeProgress;
        return progress?progress.complete(entry.snapshot):null;
      }).catch(function(){/* Keep the same key until cleanup succeeds. */}).then(function(){if(ctx.isCurrent())renderResult(data,entry);});
    }).catch(function(error) {
      if(!ctx.isCurrent())return;
      // If another window retried, the first rejection cannot settle the outcome.
      if((error.status===400 || error.status===422) && !isRetry) {
        return finishPending(owner,entry,'rejected').then(function(result){
          if(!ctx.isCurrent())return;
          if(result.retained){pendingView();text('intake-error',words().invalid);return;}
          state.pending=null;state.pendingEntry=null; id('form-umc-intake').hidden=false; id('intake-uncertain').hidden=true; text('intake-error',words().invalid);
        }).catch(function(){if(ctx.isCurrent()){pendingView();text('intake-error',words().storage);}});
      } else { pendingView(); failure(error,'intake-error'); }
    }).finally(function() { if(ctx.isCurrent()){text('intake-loading',''); busy(false,intake);} });
  }
  function loadPolicies() {
    if(state.busy) return; localize(); text('intake-error',''); text('intake-loading',words().loading); busy(true,intake);
    if(!state.result) { id('form-umc-intake').hidden=true; id('intake-uncertain').hidden=true; }
    var ctx=binding(),owner;
    if(!ctx.isCurrent()){text('intake-error',words().session);text('intake-loading','');busy(false,intake);return;}
    try{owner=storageKey();}catch(_){text('intake-error',words().storage);text('intake-loading','');busy(false,intake);return;}
    Promise.resolve().then(function(){return !state.result?restore(owner,ctx):null;}).catch(function(error){error.intakeStorage=true;throw error;}).then(function(){
      if(!ctx.isCurrent())return null;
      return ctx.request('/financial/orders/policies',{});
    }).then(function(data) {
      if(!ctx.isCurrent()||!data)return;
      state.policies=data.policies || []; id('intake-paused').hidden=!data.writes_paused; text('intake-paused',words().paused); id('intake-empty').hidden=data.writes_paused || state.policies.length>0; text('intake-empty',words().empty);
      var select=id('intake-policy'), old=select.value; select.replaceChildren(); var placeholder=node('option',words().choose); placeholder.value=''; select.appendChild(placeholder);
      state.policies.forEach(function(p) { var option=node('option',p.terms_reference+' · '+date(p.effective_from)); option.value=p.version; select.appendChild(option); }); if(state.policies.some(function(p) { return p.version===old; })) select.value=old; else if(state.policies.length===1)select.value=state.policies[0].version;
      var progress=window.UMCIntakeProgress;
      return (progress?progress.prepare():Promise.resolve()).then(function(){
        if(!ctx.isCurrent())return;
        if(state.pending) pendingView(); else if(!state.result) id('form-umc-intake').hidden=data.writes_paused || !state.policies.length;
        document.dispatchEvent(new CustomEvent("umc:intake-policy-ready",{detail:{tracking:data.funnel_tracking===true}}));
        preview();
      });
    }).catch(function(error) { if(!ctx.isCurrent())return;if(state.pending) pendingView(); if(error.intakeStorage)text('intake-error',words().storage);else failure(error,'intake-error'); }).finally(function() { if(ctx.isCurrent()){text('intake-loading',''); busy(false,intake);} });
  }
  function openIntake(options) { if(state.busy) return; var current=document.querySelector('.screen.active'); if(current && current!==intake) state.intakeBack=current.id; bridge.showScreen(intake.id);if(options&&options.withManager)document.querySelector('[name="intake-mode"][value="with_manager"]').checked=true;loadPolicies(); }
  function key() { if(!window.crypto || !crypto.getRandomValues) return null; if(crypto.randomUUID) return crypto.randomUUID(); return Array.from(crypto.getRandomValues(new Uint8Array(16))).map(function(n) { return n.toString(16).padStart(2,'0'); }).join(''); }
  id('form-umc-intake').addEventListener('submit',function(event) {
    event.preventDefault(); if(state.busy || state.pending || state.result || (window.UMCOrderImages && window.UMCOrderImages.busy())) return;
    var p=selectedPolicy(), positions=selectedPositions(), due=new Date(id('intake-due').value), op=key();
    if(!p || !op || isNaN(due.getTime()) || due<=new Date() || (positions!==null && document.querySelector('input[name="intake-mode"]:checked').value==='with_manager' && !positions.length)) { text('intake-error',words().invalid); return; }
    var payload={ position_count:positionCount(), operation_key:'miniapp:intake:'+op, policy_version:p.version, product_link:id('intake-product').value.trim(), offer_text:id('intake-brief').value.trim(), honorarium:Number(id('intake-honorarium').value).toFixed(2), selection_due_at:due.toISOString(), contact_reference:id('intake-contact').value.trim(), service_mode:document.querySelector('input[name="intake-mode"]:checked').value, accompaniment_ordinals:positions };
    if(id('intake-image-token').value) payload.image_token=id('intake-image-token').value;
    payload.order_type=id('intake-order-type').value;var filters=targeting();if(filters)payload.targeting=filters;
    if(window.UMCIntakeProgress&&window.UMCIntakeProgress.funnel())payload.funnel_id=window.UMCIntakeProgress.funnel();
    var ctx=binding(),owner,progress=window.UMCIntakeProgress;
    if(!ctx.isCurrent()){text('intake-error',words().session);return;}
    try{owner=storageKey();}catch(_){text('intake-error',words().storage);return;}
    text('intake-error','');text('intake-loading',words().sending);busy(true,intake);
    (progress?progress.flush():Promise.resolve()).then(function(){
      if(!ctx.isCurrent())return null;
      if(!window.UMCIntakeStore)throw new Error('storage_unavailable');
      return window.UMCIntakeStore.pending(owner,legacyPending(owner),{payload:payload,snapshot:progress?progress.snapshot():null});
    }).then(function(saved){
      if(!ctx.isCurrent()||!saved)return;
      text('intake-loading','');busy(false,intake);
      if(saved.submitted){showSubmitted();return;}
      state.pendingEntry=saved.entry;state.pending=saved.entry.payload;mirrorPending(owner,saved.entry);
      if(saved.created)send(saved.entry.payload,false);else pendingView();
    }).catch(function(){if(ctx.isCurrent()){text('intake-loading','');busy(false,intake);text('intake-error',words().storage);}});
  });
  id('btn-intake-retry').addEventListener('click',function() { if(state.pending) send(state.pending,true); });
  id('btn-intake-new').addEventListener('click',newOrder);
  id('btn-intake-refresh').addEventListener('click',loadPolicies);
  id('btn-intake-back').addEventListener('click',function() { if(!state.busy) bridge.showScreen(state.intakeBack); });
  id('btn-intake-selection').addEventListener('click',function() { if(state.result) openSelection(state.result.order_id); });
  id('form-umc-intake').addEventListener('input',function() { text('intake-error',''); dueLabel(); preview(); });
  id('form-umc-intake').addEventListener('change',preview);
  function positionCount(){return Number(id('intake-count').value);}
  function positionOptions(){var parent=id('intake-position-options'),selected=Array.from(parent.querySelectorAll('input:checked')).map(function(n){return n.value;});parent.replaceChildren();var count=positionCount();if(!Number.isInteger(count)||count<10||count>200)return;for(var ordinal=1;ordinal<=count;ordinal++){var label=node('label'),checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.id='intake-position-'+ordinal;checkbox.value=String(ordinal);checkbox.checked=selected.includes(checkbox.value);label.append(checkbox,node('span',ordinal));parent.appendChild(label);}}
  id('intake-count').addEventListener('input',function(){positionOptions();preview();});
  positionOptions();
  function renderSelection(data) {
    document.dispatchEvent(new CustomEvent('umc:checkout-order',{detail:{order_id:data.order_id,target:'screen-selection'}}));
    var c=words(); text('selection-order-id',data.public_number || ''); id('selection-paused').hidden=!data.writes_paused; text('selection-paused',c.readPaused); text('selection-waitlist',c.waitlist+': '+data.waitlist_count);
    var parent=id('selection-positions'); parent.replaceChildren(); if(!data.positions.length) parent.appendChild(node('p',c.noPositions,'hint'));
    data.positions.forEach(function(position) {
      var article=node('article','','umc-selection-position'); article.dataset.position=String(position.ordinal); article.appendChild(node('h2',c.position+' '+position.ordinal));
      article.appendChild(node('p',money(position.selection_minor,position.currency)+' + '+money(position.accompaniment_minor,position.currency),'hint'));
      var proof=(position.deliveries || []).find(function(delivery) { return delivery.current && position.current && delivery.assignment_id===position.assignment_id && delivery.creator_id===position.creator_id && delivery.accepted_at && position.delivered_at && !isNaN(new Date(delivery.accepted_at).getTime()) && new Date(delivery.accepted_at).getTime()===new Date(position.delivered_at).getTime(); });
      var deliveryState=position.delivery_state==='accepted' && !proof?'unknown':position.delivery_state;
      var current=node('div'); current.dataset.currentDelivery=''; current.dataset.state=deliveryState;
      var stateKey=deliveryState==='sending'?'sendingState':deliveryState;
      current.appendChild(node('p',c[stateKey] || c.unknown,'umc-selection-state'));
      if(position.creator_id) { current.appendChild(node('p',c.current)); if(position.instagram_url) link(current,position.instagram_url); }
      else current.appendChild(node('p',c.waiting,'hint'));
      if(proof && deliveryState==='accepted') current.appendChild(node('p',c.delivered+': '+date(proof.accepted_at)));
      article.appendChild(current);
      if(position.fulfilled_at) article.appendChild(node('p',c.fulfilled+': '+date(position.fulfilled_at),'hint'));
      if(position.deliveries && position.deliveries.length) {
        var history=node('div','','umc-selection-history'); history.dataset.deliveryHistory=''; history.appendChild(node('h3',c.history));
        position.deliveries.forEach(function(delivery) { var line=node('p',(delivery.current?c.current:c.previous)+': '+date(delivery.accepted_at)+' '); if(delivery.instagram_url) link(line,delivery.instagram_url); history.appendChild(line); }); article.appendChild(history);
      }
      if(position.assignment_id && position.current && window.UMCCollaboration) { var button=node('button',c.openWork,'btn btn-secondary'); button.type='button'; button.addEventListener('click',function() { window.UMCCollaboration.open(position.assignment_id); }); article.appendChild(button); }
      parent.appendChild(article);
    });
    document.dispatchEvent(new CustomEvent("umc:selection-view",{detail:data}));
  }
  function loadSelection() {
    if(state.busy || !state.order) return; localize(); text('selection-error','');text('selection-order-id','');document.dispatchEvent(new CustomEvent('umc:checkout-order',{detail:{order_id:null,target:null}})); text('selection-loading',words().loading); id('selection-positions').replaceChildren(); text('selection-waitlist',''); id('selection-paused').hidden=true; busy(true,selection);
    var ctx=binding();if(!ctx.isCurrent()){text('selection-loading','');busy(false,selection);text('selection-error',words().session);return;}ctx.request('/financial/orders/'+state.order+'/selection',{}).then(function(data){if(ctx.isCurrent())renderSelection(data);}).catch(function(error) { if(ctx.isCurrent())failure(error,'selection-error'); }).finally(function() { if(ctx.isCurrent()){text('selection-loading',''); busy(false,selection);} });
  }
  function openSelection(order) {
    if(state.busy) return; localize(); var current=document.querySelector('.screen.active'); if(current && current!==selection) state.selectionBack=current.id; bridge.showScreen(selection.id);
    if(!validId(order)) { state.order=null; text('selection-error',words().invalid); id('selection-positions').replaceChildren(); return; }
    state.order=order; var url=new URL(location.href); url.searchParams.set('selection',order); history.replaceState(null,'',url.href); loadSelection();
  }
  id('btn-selection-refresh').addEventListener('click',loadSelection);
  id('btn-selection-back').addEventListener('click',function() { if(state.busy) return; var url=new URL(location.href); url.searchParams.delete('selection'); history.replaceState(null,'',url.href); bridge.showScreen(state.selectionBack); });
  document.addEventListener('umc:screen-change',function(event) { if(!event.detail || event.detail.screen!==intake.id || !state.result) return; var panel=id('umc-checkout');if(!panel || panel.parentElement!==id('intake-result')) document.dispatchEvent(new CustomEvent('umc:checkout-order',{detail:{order_id:state.result.order_id,target:'intake-result'}})); });
  id('btn-show-create-order').textContent=words().entry;
  var list=id('orders-list');
  function orderLinks() { list.querySelectorAll('[data-order-id]').forEach(function(row) { if(!row.dataset.financialVersion || row.querySelector('[data-selection-open]')) return; var button=node('button',words().viewSelection,'btn btn-secondary'); button.type='button'; button.dataset.selectionOpen=''; button.addEventListener('click',function(event) { event.preventDefault(); event.stopPropagation(); openSelection(row.dataset.orderId); }); row.appendChild(button); }); }
  new MutationObserver(orderLinks).observe(list,{childList:true,subtree:true});
  function ready() { var identity=(window.__miniapp_platform||'telegram')+':'+(window._me||{}).user_id;if(owner!==identity||(context&&!context.isCurrent())){owner=identity;if(context)context.dispose();context=null;state.busy=false;state.pending=null;state.pendingEntry=null;state.completedEntry=null;state.result=null;state.order=null;state.opened=false;freshDraft.hidden=true;id('form-umc-intake').reset();positionOptions();id('intake-result').hidden=true;id('intake-uncertain').hidden=true;id('selection-positions').replaceChildren();text('intake-order-id','');text('selection-order-id','');document.dispatchEvent(new CustomEvent('umc:checkout-order',{detail:{order_id:null,target:null}}));}if(!context)context=bridge.createRequestContext();localize(); orderLinks();if(intake.classList.contains('active')){loadPolicies();return;} if(state.opened) return; var params=new URLSearchParams(location.search), values=params.getAll('selection');if(['orders','services','ratings'].indexOf(params.get('screen'))>=0&&params.has('order_id'))return;if(params.get('view')==='order'||params.get('tgWebAppStartParam')==='order'){state.opened=true;openIntake();return;} if(!values.length || params.has('assignment') || params.has('assignment_id') || params.get('view')==='partner') return; state.opened=true; openSelection(values.length===1?values[0]:null); }
  window.UMCSelection={open:openSelection,create:openIntake,rebuildPositions:positionOptions};
  document.addEventListener('umc:app-ready',ready); if(window.__umcAppReady) ready();
})();

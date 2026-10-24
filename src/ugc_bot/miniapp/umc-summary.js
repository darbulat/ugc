/* Own campaign aggregates. Provider acceptance and participant work stay separate. */
(function () {
  'use strict';
  var bridge=window.__umcAppBridge, screen=document.getElementById('screen-summary');
  if (!bridge || !screen) return;
  var keys=['title','back','refresh','loading','error','forbidden','missing','session','invalid','total','contacts','financial','legacy','client','manager','empty','asOf','assigned','unassigned','not_configured','in_progress','success_claimed','disputed','success_final','unconfirmed_expired','available','unknown','legacy_pending','legacy_ok','legacy_no_deal','legacy_issue','legacy_unknown'];
  var labels={
    ru:['Сводка по заказу','Назад','Обновить','Загружаем сводку…','Не удалось загрузить сводку. Попробуйте обновить.','Сводка недоступна этому аккаунту.','Заказ или назначение не найдены.','Откройте приложение заново.','Некорректная ссылка на сводку.','Всего позиций','Доставка контактов подтверждена','Статусы сотрудничества','Ранее собранные отзывы','Весь заказ','Ваши назначения','Пока нет позиций для сводки.','Данные на','Назначено','Не назначено','Условия работы ещё не сохранены','В работе','Заявлен успех','Есть возражение','Успех подтверждён','Срок подтверждения истёк','Срок удержания завершён','Неизвестно','Ожидается отзыв','Отмечено «всё прошло нормально»','Не договорились','Сообщили о проблеме','Неизвестный статус отзыва'],
    en:['Order summary','Back','Refresh','Loading summary…','Summary could not be loaded. Try refreshing.','This account cannot view the summary.','Order or assignment not found.','Reopen the app.','Invalid summary link.','Total positions','Contact deliveries confirmed','Collaboration states','Previously collected feedback','Whole order','Your assignments','No positions to summarize yet.','As of','Assigned','Unassigned','Work terms not saved yet','In progress','Success claimed','Disputed','Success confirmed','Confirmation expired','Hold period finished','Unknown','Awaiting feedback','Marked “Everything went well”','No agreement','Problem reported','Unknown feedback state'],
    kk:['Тапсырыс қорытындысы','Артқа','Жаңарту','Қорытынды жүктелуде…','Қорытынды жүктелмеді. Жаңартып көріңіз.','Бұл аккаунтқа қорытынды қолжетімсіз.','Тапсырыс не тағайындау табылмады.','Қолданбаны қайта ашыңыз.','Қорытынды сілтемесі дұрыс емес.','Барлық позициялар','Байланыстарды жеткізу расталды','Ынтымақтастық күйлері','Бұрын жиналған пікірлер','Бүкіл тапсырыс','Сізге тағайындалғандар','Қорытынды үшін позициялар әлі жоқ.','Деректер уақыты','Тағайындалған','Тағайындалмаған','Жұмыс шарттары әлі сақталмаған','Жұмыста','Сәтті аяқталу мәлімделді','Қарсылық бар','Сәтті аяқталу расталды','Растау мерзімі өтті','Ұсталым мерзімі аяқталды','Белгісіз','Пікір күтілуде','«Бәрі жақсы өтті» деп белгіленген','Келісім болмады','Мәселе хабарланды','Пікір күйі белгісіз'],
    be:['Зводка па заказе','Назад','Абнавіць','Загружаем зводку…','Не ўдалося загрузіць зводку. Паспрабуйце абнавіць.','Зводка недаступна гэтаму акаўнту.','Заказ або прызначэнне не знойдзены.','Адкрыйце праграму зноў.','Няправільная спасылка на зводку.','Усяго пазіцый','Дастаўка кантактаў пацверджана','Статусы супрацоўніцтва','Раней сабраныя водгукі','Увесь заказ','Вашы прызначэнні','Пакуль няма пазіцый для зводкі.','Даныя на','Прызначана','Не прызначана','Умовы працы яшчэ не захаваны','У працы','Заяўлены поспех','Ёсць пярэчанне','Поспех пацверджаны','Тэрмін пацверджання мінуў','Тэрмін утрымання скончыўся','Невядома','Чакаецца водгук','Адзначана «ўсё прайшло добра»','Не дамовіліся','Паведамлена пра праблему','Невядомы статус водгуку'],
    uz:['Buyurtma xulosasi','Orqaga','Yangilash','Xulosa yuklanmoqda…','Xulosa yuklanmadi. Yangilab ko‘ring.','Bu hisob uchun xulosa mavjud emas.','Buyurtma yoki topshiriq topilmadi.','Ilovani qayta oching.','Xulosa havolasi noto‘g‘ri.','Jami pozitsiyalar','Kontakt yetkazilishi tasdiqlangan','Hamkorlik holatlari','Avval yig‘ilgan fikrlar','Butun buyurtma','Sizning topshiriqlaringiz','Xulosa uchun pozitsiyalar hali yo‘q.','Ma’lumot vaqti','Tayinlangan','Tayinlanmagan','Ish shartlari hali saqlanmagan','Jarayonda','Muvaffaqiyat bildirildi','E’tiroz bor','Muvaffaqiyat tasdiqlandi','Tasdiqlash muddati o‘tdi','Ushlab turish muddati tugadi','Noma’lum','Fikr kutilmoqda','“Hammasi yaxshi o‘tdi” deb belgilangan','Kelishilmagan','Muammo bildirilgan','Fikr holati noma’lum']
  };
  var state={order:null,request:0,busy:false,opened:false,back:'screen-role-choice'};
  function id(value){return document.getElementById(value);}
  function words(){var raw=labels[(window._me||{}).locale]||labels.ru, out=Object.create(null); keys.forEach(function(k,i){out[k]=raw[i];});return out;}
  function node(tag,value){var el=document.createElement(tag);el.textContent=String(value);return el;}
  function text(name,value){id(name).textContent=value==null?'':String(value);}
  function validId(value){return typeof value==='string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);}
  function count(value){return Number.isSafeInteger(value) && value>=0;}
  function localize(){var c=words();text('summary-title',c.title);text('btn-summary-back',c.back);text('btn-summary-refresh',c.refresh);text('summary-total-label',c.total);}
  function busy(value){state.busy=value;screen.setAttribute('aria-busy',String(value));id('btn-summary-refresh').disabled=value; text('summary-loading',value?words().loading:'');}
  function render(data){
    var c=words(), states=data.states;
    if(data.order_id!==state.order || !count(data.total) || !states || typeof states!=='object' || Array.isArray(states) || ['client','manager'].indexOf(data.role)<0 || ['financial_positions','legacy_feedback'].indexOf(data.source)<0) throw new Error('invalid_summary');
    var total=0;Object.keys(states).forEach(function(key){if(!count(states[key])) throw new Error('invalid_count');total+=states[key];});
    if(total!==data.total || (data.contact_accepted!==null && (!count(data.contact_accepted)||data.contact_accepted>data.total))) throw new Error('invalid_summary');
    text('summary-total',data.total);text('summary-role',c[data.role]);text('summary-source',data.source==='financial_positions'?c.financial:c.legacy);
    id('summary-contacts').hidden=data.contact_accepted===null; text('summary-contacts',data.contact_accepted===null?'':c.contacts+': '+data.contact_accepted);
    var parent=id('summary-states');parent.replaceChildren();
    Object.keys(states).forEach(function(key){var row=document.createElement('div');row.dataset.summaryState=key;row.appendChild(node('dt',c[key]||c.unknown));row.appendChild(node('dd',states[key]));parent.appendChild(row);});
    text('summary-empty',data.total===0?c.empty:'');
    var at=new Date(data.as_of);text('summary-asof',c.asOf+': '+(!isNaN(at.getTime())?at.toISOString().replace('T',' ').slice(0,16)+' UTC':c.unknown));
    id('summary-content').hidden=false;
  }
  function load(){
    if(!state.order || state.busy)return;localize();var request=++state.request;text('summary-error','');id('summary-content').hidden=true;busy(true);
    bridge.request('/orders/'+state.order+'/campaign-summary',{}).then(function(data){if(request===state.request)render(data);}).catch(function(error){if(request!==state.request)return;var c=words();text('summary-error',error.status===401?c.session:error.status===403?c.forbidden:error.status===404?c.missing:c.error);}).finally(function(){if(request===state.request)busy(false);});
  }
  function open(order){
    var current=document.querySelector('.screen.active');if(current && current!==screen)state.back=current.id;
    state.request++;busy(false);localize();id('summary-content').hidden=true;bridge.showScreen(screen.id);state.opened=true;
    if(!validId(order)){state.order=null;text('summary-error',words().invalid);return;}
    state.order=order.toLowerCase();text('summary-order',state.order);var url=new URL(location.href);url.searchParams.set('summary',state.order);history.replaceState(null,'',url.href);load();
  }
  id('btn-summary-refresh').addEventListener('click',load);
  id('btn-summary-back').addEventListener('click',function(){state.request++;busy(false);var url=new URL(location.href);url.searchParams.delete('summary');history.replaceState(null,'',url.href);bridge.showScreen(state.back);});
  function entries(){['orders-list','manager-orders-list'].forEach(function(name){var list=id(name);if(!list)return;list.querySelectorAll('[data-order-id]').forEach(function(row){if(!validId(row.dataset.orderId)||row.querySelector('[data-summary-open]'))return;var button=node('button',words().title);button.className='btn btn-secondary';button.type='button';button.dataset.summaryOpen='';button.addEventListener('click',function(event){event.preventDefault();event.stopPropagation();open(row.dataset.orderId);});row.appendChild(button);});});}
  ['orders-list','manager-orders-list'].forEach(function(name){var list=id(name);if(list)new MutationObserver(entries).observe(list,{childList:true,subtree:true});});
  function ready(){localize();entries();if(state.opened)return;var params=new URLSearchParams(location.search), values=params.getAll('summary');if(!values.length||['assignment','assignment_id','selection','checkout','campaign'].some(function(key){return params.has(key);})||params.get('view')==='partner')return;open(values.length===1?values[0]:null);}
  window.UMCCampaignSummary={open:open};document.addEventListener('umc:app-ready',ready);if(window.__umcAppReady)ready();
})();

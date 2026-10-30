/* Own-client native checkout. Provider callbacks only refresh signed server facts. */
(function () {
  'use strict';
  var bridge=window.__umcAppBridge;
  if(!bridge) return;
  var copy={
    ru:{title:'Оплата услуг платформы',prepare:'Подготовить счёт',pay:'Оплатить в Telegram',refresh:'Проверить оплату',retry:'Повторить запрос',newLink:'Создать новую ссылку',waiting:'Оплата сервером ещё не подтверждена.',creating:'Ссылка подготавливается. Проверьте статус позже.',unknown:'Результат неизвестен. Автоматической повторной оплаты нет.',failed:'Ссылка не создана. Можно явно повторить запрос.',paid:'Оплата подтверждена сервером',paused:'Новые финансовые операции приостановлены.',error:'Не удалось проверить статус. Обновите данные.',storage:'Запрос не сохранён. Откройте приложение заново.',pending:'Разрешение оплаты ожидает результата. Для проверки обратитесь в поддержку.',max:'Оплата доступна в Telegram через подтверждённый связанный аккаунт.',link:'Открыть заказ в Telegram',unlinked:'Для оплаты нужно безопасно связать аккаунт Telegram. Обратитесь в поддержку.',source:'Сумма сохранённого счёта',noProof:'Сохранённые данные требуют проверки. Оплата не подтверждена.'},
    en:{title:'Platform services payment',prepare:'Prepare invoice',pay:'Pay in Telegram',refresh:'Check payment',retry:'Retry same request',newLink:'Create another link',waiting:'The server has not confirmed payment yet.',creating:'The link is being prepared. Check its status later.',unknown:'The outcome is unknown. Payment is never retried automatically.',failed:'No link was created. You can explicitly retry.',paid:'Payment confirmed by the server',paused:'New financial operations are paused.',error:'Status could not be checked. Refresh to try again.',storage:'The request could not be saved. Reopen the app.',pending:'Payment authorization awaits an outcome. Contact support for review.',max:'Pay in Telegram with your verified linked account.',link:'Open order in Telegram',unlinked:'Payment requires a securely linked Telegram account. Contact support.',source:'Stored invoice amount',noProof:'Stored data needs review. Payment is not confirmed.'},
    kk:{title:'Платформа қызметтерін төлеу',prepare:'Шот дайындау',pay:'Telegram арқылы төлеу',refresh:'Төлемді тексеру',retry:'Сол сұрауды қайталау',newLink:'Жаңа сілтеме жасау',waiting:'Сервер төлемді әлі растаған жоқ.',creating:'Сілтеме дайындалып жатыр. Кейін тексеріңіз.',unknown:'Нәтиже белгісіз. Төлем автоматты қайталанбайды.',failed:'Сілтеме жасалмады. Қайта сұрауға болады.',paid:'Төлемді сервер растады',paused:'Жаңа қаржы әрекеттері тоқтатылған.',error:'Күй тексерілмеді. Жаңартып көріңіз.',storage:'Сұрау сақталмады. Қолданбаны қайта ашыңыз.',pending:'Төлем рұқсатының нәтижесі күтілуде. Қолдауға хабарласыңыз.',max:'Расталған байланыстырылған аккаунтпен Telegram арқылы төлеңіз.',link:'Тапсырысты Telegram ішінде ашу',unlinked:'Төлеу үшін Telegram аккаунтын қауіпсіз байланыстыру қажет. Қолдауға хабарласыңыз.',source:'Сақталған шот сомасы',noProof:'Сақталған дерек тексеруді қажет етеді. Төлем расталмаған.'},
    be:{title:'Аплата паслуг платформы',prepare:'Падрыхтаваць рахунак',pay:'Аплаціць у Telegram',refresh:'Праверыць аплату',retry:'Паўтарыць той жа запыт',newLink:'Стварыць новую спасылку',waiting:'Сервер яшчэ не пацвердзіў аплату.',creating:'Спасылка рыхтуецца. Праверце пазней.',unknown:'Вынік невядомы. Аплата аўтаматычна не паўтараецца.',failed:'Спасылка не створана. Можна паўтарыць запыт.',paid:'Аплату пацвердзіў сервер',paused:'Новыя фінансавыя дзеянні прыпынены.',error:'Не ўдалося праверыць стан. Абнавіце даныя.',storage:'Запыт не захаваны. Адкрыйце праграму зноў.',pending:'Дазвол аплаты чакае выніку. Звярніцеся ў падтрымку.',max:'Аплаціце ў Telegram праз пацверджаны звязаны акаўнт.',link:'Адкрыць заказ у Telegram',unlinked:'Для аплаты трэба бяспечна звязаць акаўнт Telegram. Звярніцеся ў падтрымку.',source:'Сума захаванага рахунку',noProof:'Захаваныя даныя патрабуюць праверкі. Аплата не пацверджана.'},
    uz:{title:'Platforma xizmatlari uchun to‘lov',prepare:'Hisob tayyorlash',pay:'Telegram orqali to‘lash',refresh:'To‘lovni tekshirish',retry:'Ayni so‘rovni takrorlash',newLink:'Yangi havola yaratish',waiting:'Server to‘lovni hali tasdiqlamadi.',creating:'Havola tayyorlanmoqda. Keyin tekshiring.',unknown:'Natija noma’lum. To‘lov avtomatik takrorlanmaydi.',failed:'Havola yaratilmadi. So‘rovni takrorlash mumkin.',paid:'To‘lov server tomonidan tasdiqlandi',paused:'Yangi moliyaviy amallar to‘xtatilgan.',error:'Holat tekshirilmadi. Yangilab ko‘ring.',storage:'So‘rov saqlanmadi. Ilovani qayta oching.',pending:'To‘lov ruxsati natijasi kutilmoqda. Yordam xizmatiga murojaat qiling.',max:'Tasdiqlangan bog‘langan hisob bilan Telegram orqali to‘lang.',link:'Buyurtmani Telegram ichida ochish',unlinked:'To‘lov uchun Telegram hisobini xavfsiz bog‘lash kerak. Yordamga murojaat qiling.',source:'Saqlangan hisob summasi',noProof:'Saqlangan ma’lumot tekshirilishi kerak. To‘lov tasdiqlanmagan.'}
  };
  var state={order:null,data:null,busy:false,pending:null,generation:0,timer:null,poll:0,nativeOpen:false};
  function words(){return copy[(window._me||{}).locale]||copy.ru;}
  function node(tag,id){var element=document.createElement(tag);if(id) element.id=id;return element;}
  var panel=node('article','umc-checkout');panel.className='umc-checkout';
  var linkAccount=node('button','umc-checkout-link-account');linkAccount.type='button';linkAccount.className='btn btn-secondary';linkAccount.hidden=true;
  var title=node('h2'),amount=node('p'),status=node('p','umc-checkout-status'),error=node('p','umc-checkout-error'),action=node('button','umc-checkout-action'),refresh=node('button','umc-checkout-refresh');
  status.setAttribute('role','status');status.setAttribute('aria-live','polite');error.className='error';action.className='btn';refresh.className='btn btn-secondary';action.type=refresh.type='button';panel.append(title,amount,status,error,action,linkAccount,refresh);
  function platform(){return window.__miniapp_platform||'telegram';}
  function host(){return platform()==='max'?window.WebApp:(window.Telegram||{}).WebApp;}
  function visible(){return panel.isConnected&&!document.hidden&&!!panel.closest('.screen.active')&&!panel.parentElement.hidden;}
  function sync(){if(window.UMCShell) window.UMCShell.syncControls();}
  function stop(){clearTimeout(state.timer);state.timer=null;state.poll=0;}
  function safeInvoice(url){return typeof url==='string'&&/^https:\/\/t\.me\/(?:\$|invoice\/)[A-Za-z0-9_-]{1,512}$/.test(url);}
  function safeHandoff(url){return typeof url==='string'&&/^https:\/\/t\.me\/[A-Za-z0-9_]{5,32}\?start=pay_[a-f0-9-]{36}$/.test(url);}
  function storageKey(){var user=(window._me||{}).user_id;if(!user) throw new Error('identity');return 'umc:checkout:'+platform()+':'+user+':'+state.order;}
  function pending(retry){
    if(state.pending) return state.pending;
    var key=crypto.randomUUID?crypto.randomUUID():Array.from(crypto.getRandomValues(new Uint8Array(16))).map(function(n){return n.toString(16).padStart(2,'0');}).join('');
    var value={operation_key:'miniapp:checkout:'+key};
    if(retry) value.previous_attempt_id=state.data.attempt_id;
    sessionStorage.setItem(storageKey(),JSON.stringify(value));state.pending=value;return value;
  }
  function render(){
    var c=words(),d=state.data||{};linkAccount.textContent=({ru:'Связать Telegram',en:'Link Telegram',kk:'Telegram байланыстыру',be:'Звязаць Telegram',uz:'Telegram hisobini bog‘lash'})[(window._me||{}).locale]||'Link Telegram';linkAccount.hidden=platform()!=='max'||!state.data||safeHandoff(d.telegram_handoff);linkAccount.disabled=state.busy;title.textContent=c.title;refresh.textContent=c.refresh;action.hidden=true;action.disabled=state.busy||state.nativeOpen;refresh.disabled=state.busy;
    amount.textContent=Number.isSafeInteger(d.amount_minor)&&d.amount_minor>0?c.source+': '+(d.amount_minor/100).toLocaleString((window._me||{}).locale||'ru',{minimumFractionDigits:2,maximumFractionDigits:2})+' '+d.currency:'';
    status.dataset.state=d.capture_state==='confirmed'?'confirmed':d.invoice_state||'unknown';
    status.textContent=d.capture_state==='confirmed'?c.paid+(d.captured_at?' · '+new Date(d.captured_at).toLocaleString():''):d.capture_state==='unavailable'?c.noProof:d.authorization_id?c.pending:d.writes_paused?c.paused:d.invoice_state==='creating'?c.creating:d.invoice_state==='unknown'?c.unknown:d.invoice_state==='failed'?c.failed:c.waiting;
    if(d.capture_state==='confirmed'||d.capture_state==='unavailable'||d.writes_paused||d.authorization_id){sync();return;}
    if(platform()==='max'){
      status.textContent=safeHandoff(d.telegram_handoff)?c.max:c.unlinked;
      if(safeHandoff(d.telegram_handoff)){action.textContent=c.link;action.hidden=false;}
    }else if(d.can_open&&safeInvoice(d.invoice_url)){action.textContent=c.pay;action.hidden=false;}
    else if(state.pending){action.textContent=c.retry;action.hidden=false;}
    else if(d.invoice_state==='not_requested'){action.textContent=c.prepare;action.hidden=false;}
    else if(['unknown','failed'].includes(d.invoice_state)&&d.attempt_id){action.textContent=c.newLink;action.hidden=false;}
    sync();
  }
  function apply(data,generation,resolvedCommand){if(generation!==state.generation||data.order_id!==state.order)return;var wasConfirmed=state.data&&state.data.capture_state==='confirmed';state.data=data;if(['ready','confirmed'].includes(data.invoice_state)||data.capture_state==='confirmed'||(resolvedCommand&&['failed','unknown'].includes(data.invoice_state)&&data.attempt_id)){state.pending=null;try{sessionStorage.removeItem(storageKey());}catch(_){/* Stored same-key replay remains safe. */}}render();if(!wasConfirmed&&data.capture_state==='confirmed')document.dispatchEvent(new CustomEvent('umc:checkout-confirmed',{detail:{order_id:state.order}}));}
  function poll(){if(!visible()||state.poll>=6||state.data&&state.data.capture_state==='confirmed'){stop();return;}var delay=[500,1000,2000,4000,8000,15000][state.poll++];state.timer=setTimeout(function(){load().finally(poll);},delay);}
  function load(){
    if(state.busy||!state.order)return Promise.resolve();var generation=state.generation;state.busy=true;error.textContent='';render();
    return bridge.request('/financial/orders/'+state.order+'/checkout-status',{}).then(function(data){apply(data,generation);}).catch(function(){if(generation===state.generation){state.data=null;error.textContent=words().error;}}).finally(function(){if(generation===state.generation){state.busy=false;render();}});
  }
  function create(){
    var payload;try{payload=pending(state.data&&['unknown','failed'].includes(state.data.invoice_state));}catch(_){error.textContent=words().storage;return;}
    var generation=state.generation;state.busy=true;error.textContent='';render();
    bridge.request('/financial/orders/'+state.order+(payload.previous_attempt_id?'/invoice/retry':'/invoice'),payload).then(function(data){apply(data,generation,true);}).catch(function(){if(generation===state.generation)error.textContent=words().unknown;}).finally(function(){if(generation===state.generation){state.busy=false;render();}});
  }
  action.addEventListener('click',function(){
    if(state.busy||state.nativeOpen||!state.data)return;var d=state.data,wa=host();
    if(platform()==='max'){if(safeHandoff(d.telegram_handoff)&&wa&&typeof wa.openLink==='function')wa.openLink(d.telegram_handoff);return;}
    if(d.can_open&&safeInvoice(d.invoice_url)){
      try{if(wa&&typeof wa.openInvoice==='function'){state.nativeOpen=true;render();wa.openInvoice(d.invoice_url,function(){state.nativeOpen=false;load();});}else if(wa&&typeof wa.openTelegramLink==='function')wa.openTelegramLink(d.invoice_url);else window.open(d.invoice_url,'_blank','noopener,noreferrer');stop();poll();}catch(_){state.nativeOpen=false;render();error.textContent=words().error;}
    }else create();
  });
  linkAccount.addEventListener('click',function(){if(platform()==='max'&&!state.busy)document.dispatchEvent(new CustomEvent('umc:messenger-linking-open'));});
  document.addEventListener('umc:messenger-linked',function(){if(platform()==='max'&&state.order)load();});
  refresh.addEventListener('click',function(){stop();load();});
  document.addEventListener('umc:checkout-order',function(event){
    stop();state.generation++;state.busy=false;state.nativeOpen=false;state.pending=null;state.data=null;state.order=event.detail.order_id;
    var mount=document.getElementById(event.detail.target);
    if(!mount||!state.order){panel.remove();return;}mount.appendChild(panel);
    try{var saved=JSON.parse(sessionStorage.getItem(storageKey())||'null');if(saved&&typeof saved.operation_key==='string')state.pending=saved;}catch(_){error.textContent=words().storage;}
    load();
  });
  document.addEventListener('visibilitychange',function(){if(document.hidden)stop();});
  new MutationObserver(function(){if(!visible())stop();}).observe(document.body,{subtree:true,attributes:true,attributeFilter:['class','hidden']});
})();

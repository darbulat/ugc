/* Operational admin decisions preserve unpaid sources and historical money. */
(function () {
  'use strict';
  var bridge=window.__umcAppBridge,host=document.getElementById('screen-partner');
  if(!bridge||!host||window.UMCPartnerAdmin)return;
  window.UMCPartnerAdmin=true;
  var labels={
    ru:{title:'Сопровождение и привязки',leads:'Заявки на сопровождение',pending:'Ожидают решения',accepted:'Принятые',rejected:'Отклонённые',all:'Все',accept:'Принять',reject:'Отклонить',reason:'Причина решения',managers:'ID менеджеров, по одному на строку',source:'Исходная заявка не подтверждает оплату',positions:'Позиции сопровождения',contact:'Контакт клиента',review:'Проверить решение',confirm:'Подтвердить',cancel:'Отменить проверку',saved:'Решение сохранено',unknown:'Результат неизвестен. Повторите исходную операцию.',retry:'Повторить исходную операцию',invalid:'Проверьте ID, список менеджеров и обязательную причину.',error:'Не удалось загрузить данные',storage:'Безопасное сохранение операции недоступно.',back:'Назад',refresh:'Обновить',next:'Следующие',previous:'Предыдущие',empty:'Заявок нет',binding:'Техническое исправление реферальной привязки',referred:'ID приглашённого',old:'Текущий ID партнёра',newPartner:'Исправленный ID партнёра',bindingNotice:'Исправление влияет на будущие операции. История атрибуции и снимки уже оплаченных заказов сохраняются.',assignmentNotice:'Принятие добавляет менеджеров к заказу. Оно не подтверждает оплату, успех автора или вознаграждение 600 ₽.',session:'Откройте приложение заново',loading:'Загрузка…'},
    en:{title:'Accompaniment and attribution',leads:'Accompaniment requests',pending:'Awaiting review',accepted:'Accepted',rejected:'Rejected',all:'All',accept:'Accept',reject:'Reject',reason:'Decision reason',managers:'Manager IDs, one per line',source:'The original request does not confirm payment',positions:'Accompaniment positions',contact:'Client contact',review:'Review decision',confirm:'Confirm',cancel:'Cancel review',saved:'Decision saved',unknown:'Result unknown. Retry the original operation.',retry:'Retry original operation',invalid:'Check IDs, managers and the required reason.',error:'Could not load data',storage:'Safe operation storage unavailable.',back:'Back',refresh:'Refresh',next:'Next',previous:'Previous',empty:'No requests',binding:'Technical referral attachment correction',referred:'Invited user ID',old:'Current partner ID',newPartner:'Correct partner ID',bindingNotice:'This affects future operations. Historical attribution and paid-order snapshots are preserved.',assignmentNotice:'Acceptance adds managers to the order. It confirms no payment, creator success or RUB600 reward.',session:'Reopen the app',loading:'Loading…'}
  };
  var screen=document.createElement('section');screen.id='screen-partner-admin';screen.className='screen';screen.dataset.umcSection='lilac';screen.style.overflowWrap='anywhere';host.parentNode.appendChild(screen);
  var bound=null,actor=null,busy=false,pending=null,review=null,back='screen-partner',page=0,status='pending',data=null,generation=0,storageBlocked=false;
  function c(){return labels[(window._me||{}).locale]||labels.ru;}
  function node(tag,text,cls){var el=document.createElement(tag);if(text!=null)el.textContent=text;if(cls)el.className=cls;return el;}
  function button(parent,label,id,action){var el=node('button',label,'btn btn-secondary');el.type='button';if(id)el.id=id;el.disabled=busy;el.addEventListener('click',action);parent.appendChild(el);return el;}
  function field(parent,label,id,area){var wrap=node('label',label),el=node(area?'textarea':'input');el.id=id;el.required=true;el.maxLength=4000;wrap.appendChild(el);parent.appendChild(wrap);return el;}
  function key(){return 'umc:partner-admin:v1:'+(window.__miniapp_platform||'telegram')+':'+actor;}
  function valid(b,g){if(b!==bound||g!==generation)return false;if(!b||!b.isCurrent()){invalidate();return false;}return true;}
  function invalidate(){generation++;if(bound)bound.dispose();bound=null;actor=null;busy=false;data=null;pending=null;review=null;screen.replaceChildren(node('p',c().session,'error'));}
  function fail(message){var el=document.getElementById('lead-admin-message');if(el)el.textContent=message;}
  function operation(){if(!crypto.getRandomValues)throw new Error();return 'partner-admin:'+Array.from(crypto.getRandomValues(new Uint8Array(16))).map(function(n){return n.toString(16).padStart(2,'0');}).join('');}
  function uuid(value){return /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(value);}
  function confirmDecision(path,values,summary){
    if(busy||pending||!bound||!bound.isCurrent())return;
    try{values.operation_key=operation();}catch(_){fail(c().storage);return;}
    review={path:path,values:values};var area=document.getElementById('lead-admin-decision');area.hidden=false;area.replaceChildren(node('h2',c().review),node('p',summary),node('p',values.reason));
    button(area,c().confirm,'lead-admin-confirm',function(){if(!review||busy||!bound||!bound.isCurrent())return;try{sessionStorage.setItem(key(),JSON.stringify(review));}catch(_){fail(c().storage);return;}pending=review;review=null;send();});
    button(area,c().cancel,'lead-admin-cancel',function(){review=null;area.hidden=true;});
  }
  function send(){
    if(busy||!pending||!bound||!bound.isCurrent())return;
    var b=bound,g=generation,original=pending;busy=true;render();
    b.request(original.path,original.values).then(function(result){
      if(!valid(b,g))return;if(result.operation_key!==original.values.operation_key)throw new Error('unknown');
      sessionStorage.removeItem(key());pending=null;busy=false;load(c().saved);
    }).catch(function(error){if(!valid(b,g))return;busy=false;if(error.status===401||error.status===403){invalidate();return;}render();fail(c().unknown);});
  }
  function leadDecision(row,action){
    if(busy||pending)return;
    var form=document.getElementById('lead-admin-form');form.replaceChildren(node('h2',c()[action]));
    form.appendChild(node('p',row.order_id,'umc-partner-reference'));form.appendChild(node('p',c().assignmentNotice,'hint'));
    var managers=action==='accept'?field(form,c().managers,'lead-manager-ids',true):null;
    var reason=field(form,c().reason,'lead-review-reason',true);
    button(form,c().review,'lead-review',function(){
      var ids=managers?managers.value.split(/[\s,]+/).filter(Boolean):[];
      if(!reason.value.trim()||(action==='accept'&&!ids.length)||ids.some(function(v){return !uuid(v);})||new Set(ids).size!==ids.length||ids.length>20){fail(c().invalid);return;}
      confirmDecision('/admin/partners/lead-command',{lead_id:row.lead_id,expected_version:row.version,action:action,manager_ids:ids,reason:reason.value.trim()},c()[action]+' · '+row.order_id+(ids.length?' · '+ids.join(', '):''));
    });
  }
  function render(message){
    screen.replaceChildren(node('h1',c().title));screen.setAttribute('aria-busy',String(busy));
    button(screen,c().back,'lead-admin-back',function(){invalidate();bridge.showScreen(back);});button(screen,c().refresh,'lead-admin-refresh',function(){load();});
    var feedback=node('p',message||'','hint');feedback.id='lead-admin-message';feedback.setAttribute('role','status');screen.appendChild(feedback);
    if(busy){feedback.textContent=c().loading;return;}if(storageBlocked){feedback.textContent=c().storage;return;}
    if(pending){feedback.textContent=c().unknown;button(screen,c().retry,'lead-admin-retry',send);return;}
    var filter=node('select');filter.id='lead-admin-filter';['pending','accepted','rejected','all'].forEach(function(value){var option=node('option',c()[value]);option.value=value;filter.appendChild(option);});filter.value=status;filter.addEventListener('change',function(){status=filter.value;page=0;load();});screen.appendChild(filter);
    screen.appendChild(node('h2',c().leads));
    if(data&&data.entries.length)data.entries.forEach(function(row){var item=node('article','','umc-partner-row');item.appendChild(node('h3',row.order_id,'umc-partner-reference'));item.appendChild(node('p',c().source,'hint'));item.appendChild(node('p',c().positions+': '+row.selected_ordinals.join(', ')));item.appendChild(node('p',c().contact+': '+row.contact_reference));if(row.version===0){button(item,c().accept,'lead-accept-'+row.lead_id,function(){leadDecision(row,'accept');});button(item,c().reject,'lead-reject-'+row.lead_id,function(){leadDecision(row,'reject');});}else{item.appendChild(node('p',(c()[row.review_state]||row.review_state)+' · '+row.reason));item.appendChild(node('p',row.actor_id+' · '+row.reviewed_at,'umc-partner-reference'));}screen.appendChild(item);});
    else screen.appendChild(node('p',c().empty,'hint'));
    if(page>0)button(screen,c().previous,'lead-previous',function(){page--;load();});if(data&&data.has_more)button(screen,c().next,'lead-next',function(){page++;load();});
    var form=node('section');form.id='lead-admin-form';screen.appendChild(form);
    var decision=node('section');decision.id='lead-admin-decision';decision.hidden=true;screen.appendChild(decision);
    var correction=node('details','','umc-partner-row');correction.appendChild(node('summary',c().binding));correction.appendChild(node('p',c().bindingNotice,'hint'));
    var referred=field(correction,c().referred,'binding-referred'),old=field(correction,c().old,'binding-old'),target=field(correction,c().newPartner,'binding-new'),reason=field(correction,c().reason,'binding-reason',true);
    button(correction,c().review,'binding-review',function(){var ids=[referred.value.trim(),old.value.trim(),target.value.trim()];if(ids.some(function(v){return !uuid(v);})||ids[0]===ids[2]||ids[1]===ids[2]||!reason.value.trim()){fail(c().invalid);return;}confirmDecision('/admin/partners/binding-command',{referred_id:ids[0],expected_referrer_id:ids[1],referrer_id:ids[2],reason:reason.value.trim()},ids[0]+' · '+ids[1]+' → '+ids[2]);});screen.appendChild(correction);
  }
  function load(message){
    if(busy||!bound||!bound.isCurrent())return;var b=bound,g=generation;busy=true;render();
    b.request('/admin/partners/leads',{page:page,status:status}).then(function(result){if(valid(b,g))data=result;}).catch(function(error){if(valid(b,g)){if(error.status===401||error.status===403)invalidate();else data=null;}}).finally(function(){if(valid(b,g)){busy=false;render(message||(!data?c().error:''));}});
  }
  function open(){
    var previous=document.querySelector('.screen.active');if(previous&&previous!==screen)back=previous.id;
    if(bound)bound.dispose();generation++;storageBlocked=false;bound=bridge.createRequestContext();var b=bound,g=generation;busy=true;data=null;render();bridge.showScreen(screen.id);
    b.request('/admin/partners/context',{}).then(function(context){
      if(!valid(b,g))return;actor=context.actor_id;if(!context.capabilities||!context.capabilities.review_leads){invalidate();return;}
      try{pending=JSON.parse(sessionStorage.getItem(key())||'null');if(pending&&(!pending.values||typeof pending.values.operation_key!=='string'||['/admin/partners/lead-command','/admin/partners/binding-command'].indexOf(pending.path)<0))throw new Error();}
      catch(_){busy=false;pending=null;storageBlocked=true;render(c().storage);return;}
      busy=false;load();
    }).catch(function(){if(valid(b,g))invalidate();});
  }
  function ready(){
    var b=bridge.createRequestContext();b.request('/admin/partners/context',{}).then(function(context){if(!b.isCurrent()||!context.capabilities||!context.capabilities.review_leads)return;if(!document.getElementById('partner-admin-open'))button(host,c().title,'partner-admin-open',open);}).catch(function(){}).finally(function(){b.dispose();});
  }
  document.addEventListener('umc:app-ready',ready);if(window.__umcAppReady)ready();
  document.addEventListener('visibilitychange',function(){if(bound&&!bound.isCurrent())invalidate();});window.addEventListener('focus',function(){if(bound&&!bound.isCurrent())invalidate();});window.addEventListener('pagehide',invalidate);
})();

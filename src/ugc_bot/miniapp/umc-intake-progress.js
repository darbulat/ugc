/* Per-account draft recovery and bounded, nonfinancial funnel observations. */
(function(){
  'use strict';
  var bridge=window.__umcAppBridge,form=document.getElementById('form-umc-intake');
  if(!bridge||!form)return;
  var copy={ru:['Бриф','Фильтры','Пакет и оплата','Черновик сохранён в этой сессии'],en:['Brief','Filters','Package and payment','Draft saved in this session'],kk:['Тапсырма','Сүзгілер','Пакет пен төлем','Осы сессияда жоба сақталды'],be:['Заданне','Фільтры','Пакет і аплата','Чарнавік захаваны ў гэтай сесіі'],uz:['Topshiriq','Filtrlar','Paket va to‘lov','Qoralama shu seansda saqlandi']};
  var navigation=document.createElement('nav'),status=document.createElement('p'),tracking=false,flow=null,observed={},restored=false,binding=null,context=null,generation=0,applying=false,submittedBinding=null;
  navigation.className='umc-selection-steps';status.className='hint';status.setAttribute('role','status');
  var ids=['intake-product','intake-min_followers','intake-policy'], stages=['brief','filters','package'];
  function words(){return copy[(window._me||{}).locale]||copy.en;}
  function identity(){var user=(window._me||{}).user_id;return typeof user==='string'&&user?'umc:intake-draft:'+(window.__miniapp_platform||'telegram')+':'+user:null;}
  function newContext(){if(context)context.dispose();context=bridge.createRequestContext?bridge.createRequestContext():null;generation++;tracking=false;observed={};}
  function bind(){
    var next=identity();
    if(next===binding){if(context&&!context.isCurrent())newContext();return false;}
    newContext();binding=next;flow=null;restored=false;status.textContent='';
    applying=true;try{form.reset();form.dispatchEvent(new Event('change',{bubbles:true}));}finally{applying=false;}
    restore(false);return true;
  }
  function operation(){if(!window.crypto||!crypto.getRandomValues)return null;return crypto.randomUUID?crypto.randomUUID():Array.from(crypto.getRandomValues(new Uint8Array(16))).map(function(n){return n.toString(16).padStart(2,'0');}).join('');}
  function observe(stage){
    bind();if(!binding||!tracking||!flow||observed[stage]||!context||!context.isCurrent())return;
    var owner=binding,ownFlow=flow,marks=observed,request=context,version=generation;
    marks[stage]=true;
    request.request('/financial/orders/funnel/stage',{funnel_id:ownFlow,stage:stage}).catch(function(){
      if(identity()===owner&&binding===owner&&flow===ownFlow&&observed===marks&&context===request&&generation===version&&request.isCurrent())delete marks[stage];
    });
  }
  function fields(){return Array.from(form.querySelectorAll('input,textarea,select')).filter(function(n){return n.id||(n.type==='radio'&&n.name);});}
  function fieldKey(n){return n.id||'radio:'+n.name+':'+n.value;}
  function save(){
    if(applying||bind()||!binding)return;
    try{var values={};fields().forEach(function(n){values[fieldKey(n)]={value:n.value,checked:n.checked};});sessionStorage.setItem(binding,JSON.stringify({values:values,flow:flow}));status.textContent=words()[3];}catch(_){/* Draft storage never replaces the safe command retry store. */}
  }
  function restore(final){
    if(restored||!binding)return;
    applying=true;
    try{
      var data=JSON.parse(sessionStorage.getItem(binding)||'null');
      if(data&&data.values){
        fields().forEach(function(n){var v=data.values[fieldKey(n)];if(!v||typeof v.value!=='string')return;if(n.type==='radio'){if(v.value===n.value&&v.checked===true)n.checked=true;return;}if(n.tagName==='SELECT'&&!Array.from(n.options).some(function(o){return o.value===v.value;}))return;n.value=v.value;if(n.type==='checkbox'&&typeof v.checked==='boolean')n.checked=v.checked;});
        if(typeof data.flow==='string'&&/^[0-9a-f-]{32,36}$/i.test(data.flow))flow=data.flow;
        form.dispatchEvent(new Event('change',{bubbles:true}));status.textContent=words()[3];
      }
    }catch(_){/* Corrupt or unavailable drafts remain isolated to this owner. */}
    finally{applying=false;if(final)restored=true;}
  }
  function localize(){Array.from(navigation.children).forEach(function(b,i){b.textContent=words()[i];});navigation.setAttribute('aria-label',words()[0]+' / '+words()[1]+' / '+words()[2]);}
  stages.forEach(function(stage,index){var b=document.createElement('button');b.type='button';b.className='btn btn-secondary';b.addEventListener('click',function(){var input=document.getElementById(ids[index]);if(input){input.scrollIntoView({block:'center',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});input.focus();observe(stage);}});navigation.appendChild(b);});form.prepend(navigation);form.appendChild(status);localize();
  form.addEventListener('input',save);
  form.addEventListener('change',save);
  form.addEventListener('focusin',function(e){var id=e.target.id||'';observe(id.indexOf('intake-min_')===0||id.indexOf('intake-max_')===0||id==='intake-gender'?'filters':id==='intake-policy'||id==='intake-all-manager'||id.indexOf('intake-position-')===0?'package':'brief');});
  document.addEventListener('umc:intake-policy-ready',function(e){bind();if(!binding)return;tracking=e.detail&&e.detail.tracking===true;restore(true);if(!flow)flow=operation();observe('opened');});
  function submitted(){bind();submittedBinding=binding;}
  form.addEventListener('submit',submitted,true);
  var retry=document.getElementById('btn-intake-retry');if(retry)retry.addEventListener('click',submitted,true);
  document.addEventListener('umc:intake-created',function(){if(bind()||!binding||(submittedBinding&&submittedBinding!==binding))return;try{sessionStorage.removeItem(binding);}catch(_){}flow=null;observed={};status.textContent='';restored=false;submittedBinding=null;});
  document.addEventListener('umc:app-ready',function(){bind();localize();});
  window.UMCIntakeProgress={funnel:function(){bind();if(tracking&&!flow)flow=operation();return binding&&tracking&&context&&context.isCurrent()?flow:null;}};
})();

/* Per-account draft recovery and bounded, nonfinancial funnel observations. */
(function(){
  'use strict';
  var bridge=window.__umcAppBridge,form=document.getElementById('form-umc-intake');
  if(!bridge||!form)return;
  var copy={ru:['Бриф','Фильтры','Пакет и оплата','Черновик сохранён на этом устройстве','Черновик сохранён в этой сессии'],en:['Brief','Filters','Package and payment','Draft saved on this device','Draft saved in this session'],kk:['Тапсырма','Сүзгілер','Пакет пен төлем','Жоба осы құрылғыда сақталды','Осы сессияда жоба сақталды'],be:['Заданне','Фільтры','Пакет і аплата','Чарнавік захаваны на гэтай прыладзе','Чарнавік захаваны ў гэтай сесіі'],uz:['Topshiriq','Filtrlar','Paket va to‘lov','Qoralama ushbu qurilmada saqlandi','Qoralama shu seansda saqlandi']};
  var navigation=document.createElement('nav'),status=document.createElement('p'),tracking=false,flow=null,observed={},restored=false,binding=null,context=null,generation=0,applying=false,submittedBinding=null;
  var draftLoad=null,draftDirty=false,lastSnapshot=null,writers={},queued={},ownKey=null,sources=[],draftGroup=null;
  navigation.className='umc-selection-steps';status.className='hint';status.setAttribute('role','status');
  var ids=['intake-product','intake-min_followers','intake-policy'], stages=['brief','filters','package'];
  function words(){return copy[(window._me||{}).locale]||copy.en;}
  function identity(){var user=(window._me||{}).user_id;return typeof user==='string'&&user?'umc:intake-draft:'+(window.__miniapp_platform||'telegram')+':'+user:null;}
  function newContext(){if(context)context.dispose();context=bridge.createRequestContext?bridge.createRequestContext():null;generation++;tracking=false;observed={};}
  function bind(){
    var next=identity();
    if(next===binding){if(context&&!context.isCurrent())return true;return false;}
    newContext();binding=next;flow=null;restored=false;draftLoad=null;draftDirty=false;lastSnapshot=null;ownKey=null;sources=[];draftGroup=null;status.textContent='';
    applying=true;try{form.reset();if(window.UMCSelection)window.UMCSelection.rebuildPositions();form.dispatchEvent(new Event('change',{bubbles:true}));}finally{applying=false;}
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
  function fields(){return Array.from(form.querySelectorAll('input,textarea,select')).filter(function(n){return n.type!=='file'&&(n.id||(n.type==='radio'&&n.name));});}
  function fieldKey(n){return n.id||'radio:'+n.name+':'+n.value;}
  function queueDraft(owner,raw){
    queued[owner]=raw;
    if(writers[owner])return writers[owner];
    function drain(){
      var value=queued[owner];delete queued[owner];
      var store=window.UMCIntakeStore;
      return (store?store.writeDraft(owner,value):Promise.reject(new Error('storage_unavailable'))).then(function(stored){
        if(binding===owner&&lastSnapshot===value){try{status.textContent=words()[stored||(ownKey&&localStorage.getItem(ownKey)===value)?3:4];}catch(_){status.textContent=words()[stored?3:4];}}
      }).catch(function(){
        if(binding===owner&&lastSnapshot===value){try{status.textContent=words()[ownKey&&localStorage.getItem(ownKey)===value?3:4];}catch(_){status.textContent=words()[4];}}
      }).then(function(){if(Object.prototype.hasOwnProperty.call(queued,owner))return drain();});
    }
    writers[owner]=Promise.resolve().then(drain).finally(function(){delete writers[owner];});
    return writers[owner];
  }
  function localPrefix(owner){return owner+':v:';}
  function validVersion(value){return typeof value==='string'&&/^[0-9a-f-]{32,36}$/i.test(value);}
  function latestLocal(owner){
    var prefix=localPrefix(owner),latest=null;
    try{
      for(var i=0;i<localStorage.length;i++){
        var name=localStorage.key(i);if(!name||name.indexOf(prefix)!==0)continue;
        var version=name.slice(prefix.length);if(!validVersion(version))continue;
        var raw=localStorage.getItem(name),data;
        try{data=JSON.parse(raw||'null');}catch(_){continue;}
        if(!data||data.draft_id!==version||typeof data.updated_at!=='number'||!Number.isFinite(data.updated_at))continue;
        if(!latest||data.updated_at>latest.time||(data.updated_at===latest.time&&version>latest.version))latest={raw:raw,time:data.updated_at,version:version};
      }
    }catch(_){return null;}
    return latest?latest.raw:null;
  }
  function latestDraft(local,stored){
    if(!local)return stored;
    if(!stored)return local;
    try{
      var a=JSON.parse(local),b=JSON.parse(stored);
      var left=Number(a.updated_at)||0,right=Number(b.updated_at)||0;
      return right>left||(right===left&&String(b.draft_id||'')>String(a.draft_id||''))?stored:local;
    }catch(_){return local;}
  }
  function save(){
    if(applying||bind()||!binding)return;
    var values={};fields().forEach(function(n){values[fieldKey(n)]={value:n.value,checked:n.checked};});
    try{var previous=JSON.parse(lastSnapshot||'null');if(previous&&previous.flow===flow&&JSON.stringify(previous.values)===JSON.stringify(values))return;}catch(_){}
    var version=operation(),now=window.performance&&performance.timeOrigin?performance.timeOrigin+performance.now():Date.now();
    if(!draftGroup)draftGroup=operation();
    var history=sources.slice(),previousKey=ownKey,previousVersion=previousKey&&previousKey.slice(localPrefix(binding).length);
    if(validVersion(previousVersion)&&!history.includes(previousVersion))history.push(previousVersion);
    var raw=JSON.stringify({values:values,flow:flow,draft_id:version,draft_group:draftGroup,sources:history,updated_at:now});lastSnapshot=raw;draftDirty=true;
    try{sessionStorage.setItem(binding,raw);status.textContent=words()[4];}catch(_){status.textContent='';}
    if(version)try{
      var key=localPrefix(binding)+version;
      localStorage.setItem(key,raw);ownKey=key;
      if(previousKey&&previousKey!==key)try{localStorage.removeItem(previousKey);}catch(_){if(validVersion(previousVersion)&&!sources.includes(previousVersion))sources.push(previousVersion);}
      status.textContent=words()[3];
    }catch(_){/* The session and IndexedDB remain available. */}
    queueDraft(binding,raw);
  }
  function restore(final){
    if(restored||!binding)return Promise.resolve();
    var owner=binding,version=generation;
    if(!draftLoad){
      var session=null,legacy=false;
      try{
        session=sessionStorage.getItem(owner);
        var old=JSON.parse(session||'null');
        if(old&&old.values&&!validVersion(old.draft_id)){
          var migration=operation();
          if(migration){session=JSON.stringify({values:old.values,flow:old.flow,draft_id:migration,draft_group:'00000000000000000000000000000000',sources:[],updated_at:0});legacy=true;sessionStorage.setItem(owner,session);}
        }
      }catch(_){}
      var local=latestLocal(owner),store=window.UMCIntakeStore;
      if(session&&legacy){
        var localSaved=false;
        try{var migrated=JSON.parse(session);localStorage.setItem(localPrefix(owner)+migrated.draft_id,session);localSaved=true;}catch(_){}
        draftLoad=(store?store.writeDraft(owner,session).catch(function(){return false;}):Promise.resolve(false)).then(function(stored){return {raw:session,durable:localSaved||stored===true};});
      }else draftLoad=session?Promise.resolve({raw:session,durable:false}):(store?store.readDraft(owner).catch(function(){return null;}):Promise.resolve(null)).then(function(raw){return {raw:latestDraft(local,raw),durable:true};});
    }
    return draftLoad.then(function(saved){
      if(binding!==owner||identity()!==owner||version!==generation||draftDirty||!context||!context.isCurrent())return;
      applying=true;
      try{
        var raw=saved.raw,data=JSON.parse(raw||'null');
        if(data&&data.values){
          // Build dependent controls before applying their saved checked states.
          var savedCount=data.values['intake-count'],count=savedCount&&Number(savedCount.value);
          if(Number.isInteger(count)&&count>=10&&count<=200)document.getElementById('intake-count').value=String(count);
          if(window.UMCSelection)window.UMCSelection.rebuildPositions();
          fields().forEach(function(n){var v=data.values[fieldKey(n)];if(!v||typeof v.value!=='string')return;if(n.type==='radio'){if(v.value===n.value&&v.checked===true)n.checked=true;return;}if(n.tagName==='SELECT'&&!Array.from(n.options).some(function(o){return o.value===v.value;}))return;n.value=v.value;if(n.type==='checkbox'&&typeof v.checked==='boolean')n.checked=v.checked;});
          if(typeof data.flow==='string'&&/^[0-9a-f-]{32,36}$/i.test(data.flow))flow=data.flow;
          lastSnapshot=raw;draftGroup=validVersion(data.draft_group)?data.draft_group:validVersion(data.draft_id)?data.draft_id:operation();
          sources=Array.isArray(data.sources)?data.sources.filter(validVersion):[];
          if(validVersion(data.draft_id)&&!sources.includes(data.draft_id))sources.push(data.draft_id);
          if(saved.durable)try{sessionStorage.setItem(owner,raw);}catch(_){}
          form.dispatchEvent(new Event('change',{bubbles:true}));status.textContent=words()[saved.durable?3:4];
        }
      }catch(_){/* Corrupt drafts stay isolated to this owner. */}
      finally{applying=false;if(final)restored=true;}
    });
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
  function complete(snapshot){
    if(bind()||!binding||(submittedBinding&&submittedBinding!==binding))return Promise.reject(new Error('context_changed'));
    var owner=binding,problem=null;
    if(typeof snapshot!=='string'){submittedBinding=null;return Promise.resolve();}
    try{if(sessionStorage.getItem(owner)===snapshot)sessionStorage.removeItem(owner);}catch(error){problem=error;}
    try{
      var data=JSON.parse(snapshot),versions=Array.isArray(data.sources)?data.sources.filter(validVersion):[];
      if(validVersion(data.draft_id))versions.push(data.draft_id);
      versions.forEach(function(version){localStorage.removeItem(localPrefix(owner)+version);});
    }catch(error){problem=error;}
    var store=window.UMCIntakeStore;
    if(!store)return Promise.reject(new Error('storage_unavailable'));
    return (writers[owner]||Promise.resolve()).then(function(){return store.clearDraft(owner,snapshot);}).then(function(){
      if(problem)throw problem;
      if(lastSnapshot===snapshot){flow=null;observed={};status.textContent='';lastSnapshot=null;draftLoad=null;restored=false;draftDirty=false;ownKey=null;sources=[];draftGroup=null;}
      submittedBinding=null;
    });
  }
  document.addEventListener('umc:app-ready',function(){if(context&&!context.isCurrent())binding=null;bind();localize();});
  window.UMCIntakeProgress={
    prepare:function(){bind();return restore(true);},
    startNew:function(){
      if(bind()||!binding||!context||!context.isCurrent())return false;
      var nextGroup=operation();if(!nextGroup)return false;
      flow=tracking?operation():null;observed={};lastSnapshot=null;draftLoad=null;restored=true;draftDirty=false;sources=[];draftGroup=nextGroup;status.textContent='';save();return true;
    },
    complete:complete,
    flush:function(){bind();return writers[binding]||Promise.resolve();},
    snapshot:function(){bind();return lastSnapshot;},
    funnel:function(){bind();if(tracking&&!flow)flow=operation();return binding&&tracking&&context&&context.isCurrent()?flow:null;}
  };
})();

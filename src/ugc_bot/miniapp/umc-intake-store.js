/* Durable owner-scoped drafts and atomic recovery of uncertain intake commands. */
(function () {
  'use strict';

  function database() {
    return new Promise(function (resolve, reject) {
      if (!window.indexedDB) { reject(new Error('storage_unavailable')); return; }
      var request;
      try { request=window.indexedDB.open('umc-intake-recovery',1); }
      catch (error) { reject(error); return; }
      request.onupgradeneeded=function () {
        var db=request.result;
        if(!db.objectStoreNames.contains('pending')) db.createObjectStore('pending');
        if(!db.objectStoreNames.contains('drafts')) db.createObjectStore('drafts');
      };
      request.onerror=function () { reject(request.error || new Error('storage_unavailable')); };
      request.onblocked=function () { reject(new Error('storage_blocked')); };
      request.onsuccess=function () { resolve(request.result); };
    });
  }

  // A read and its conditional write share one transaction across WebViews.
  function update(name, owner, change) {
    return database().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx, result, problem;
        try {
          tx=db.transaction(name,'readwrite');
          var store=tx.objectStore(name), request=store.get(owner);
          request.onsuccess=function () {
            try {
              var next=change(request.result);
              result=next.result;
              if(next.write==='put') store.put(next.value,owner);
              else if(next.write==='delete') store.delete(owner);
            } catch (error) { problem=error; tx.abort(); }
          };
          tx.oncomplete=function () { db.close(); resolve(result); };
          tx.onabort=function () { db.close(); reject(problem || tx.error || new Error('storage_aborted')); };
          tx.onerror=function () { /* onabort reports the failure. */ };
        } catch (error) { db.close(); reject(error); }
      });
    });
  }

  function validPayload(payload) {
    return payload && typeof payload==='object' && !Array.isArray(payload) &&
      typeof payload.operation_key==='string' && payload.operation_key.length>0 &&
      typeof payload.policy_version==='string' &&
      ['self_service','with_manager'].includes(payload.service_mode) &&
      !Object.prototype.hasOwnProperty.call(payload,'init_data') &&
      !Object.prototype.hasOwnProperty.call(payload,'platform');
  }
  function validGroup(value) { return typeof value==='string' && /^[0-9a-f-]{32,36}$/i.test(value); }
  function group(snapshot) {
    var legacy='00000000000000000000000000000000';
    try { var data=JSON.parse(snapshot); return data && validGroup(data.draft_group)?data.draft_group:legacy; }
    catch (_) { return legacy; }
  }
  function queue(value) {
    if(value===undefined) return [];
    if(!Array.isArray(value)) throw new Error('invalid_saved_requests');
    value.forEach(function (entry) {
      if(!entry) throw new Error('invalid_saved_request');
      if(entry.settled_key) {
        if(typeof entry.settled_key!=='string' || !['confirmed','rejected'].includes(entry.outcome) ||
            (entry.draft_group!==null && !validGroup(entry.draft_group))) throw new Error('invalid_saved_request');
      } else if(!validPayload(entry.payload) || (entry.snapshot!==null && typeof entry.snapshot!=='string') ||
          (entry.retried!==undefined && typeof entry.retried!=='boolean')) throw new Error('invalid_saved_request');
    });
    return value;
  }
  function active(entries, key) {
    return entries.find(function (entry) { return entry.payload && (!key || entry.payload.operation_key===key); });
  }
  function marker(entries, key) { return entries.find(function (entry) { return entry.settled_key===key; }); }
  function ensureMatch(entry, payload) {
    if(entry && JSON.stringify(entry.payload)!==JSON.stringify(payload)) throw new Error('conflicting_saved_request');
  }
  function addLegacy(entries, stored) {
    if(!stored) return null;
    var isMirror=stored.__umcIntakeMirror===1, legacy=isMirror?stored.payload:stored;
    if(!validPayload(legacy)) throw new Error('invalid_saved_request');
    var match=active(entries,legacy.operation_key);ensureMatch(match,legacy);
    if(!match && !marker(entries,legacy.operation_key)) {
      var snapshot=isMirror && typeof stored.snapshot==='string'?stored.snapshot:null;
      match={payload:legacy,snapshot:snapshot,retried:isMirror};entries.push(match);
    }
    return match || null;
  }
  function pending(owner, legacy, proposed) {
    return update('pending',owner,function (value) {
      var entries=queue(value), previous=entries.length, own=addLegacy(entries,legacy), selected=own || active(entries), created=false, submitted=false;
      if(!selected && proposed) {
        if(!validPayload(proposed.payload) || (proposed.snapshot!==null && typeof proposed.snapshot!=='string')) throw new Error('invalid_saved_request');
        var draftGroup=group(proposed.snapshot);
        submitted=!!draftGroup && entries.some(function (entry) { return entry.outcome==='confirmed' && entry.draft_group===draftGroup; });
        if(!submitted) { selected=proposed; entries.push(selected); created=true; }
      }
      return {write:entries.length!==previous?'put':null,value:entries,result:{entry:selected || null,created:created,submitted:submitted}};
    });
  }
  function beginSend(owner, entry, retry) {
    return update('pending',owner,function (value) {
      var entries=queue(value), match=active(entries,entry.payload.operation_key), settled=marker(entries,entry.payload.operation_key);
      ensureMatch(match,entry.payload);
      if(!match && !settled){
        if(!validPayload(entry.payload)||(entry.snapshot!==null&&typeof entry.snapshot!=='string'))throw new Error('invalid_saved_request');
        entries.push({payload:entry.payload,snapshot:entry.snapshot,retried:true});
        return {write:'put',value:entries,result:{active:true}};
      }
      if(!match)return {result:{active:false,outcome:settled.outcome}};
      if(retry && !match.retried) { match.retried=true; return {write:'put',value:entries,result:{active:true}}; }
      return {result:{active:true}};
    });
  }
  function confirm(owner, entry) {
    return update('pending',owner,function (value) {
      var entries=queue(value),match=active(entries,entry.payload.operation_key),settled=marker(entries,entry.payload.operation_key);
      ensureMatch(match,entry.payload);
      if(settled && settled.outcome!=='confirmed') throw new Error('conflicting_settlement');
      if(!settled)entries.push({settled_key:entry.payload.operation_key,outcome:'confirmed',draft_group:group(entry.snapshot)});
      return {write:settled?null:'put',value:entries,result:null};
    });
  }
  function retire(owner, entry, outcome) {
    return update('pending',owner,function (value) {
      var entries=queue(value),match=active(entries,entry.payload.operation_key),settled=marker(entries,entry.payload.operation_key);
      ensureMatch(match,entry.payload);
      if(settled && settled.outcome!==outcome)throw new Error('conflicting_settlement');
      if(outcome==='rejected' && match && match.retried)return {result:{retained:true}};
      if(!settled)entries.push({settled_key:entry.payload.operation_key,outcome:outcome,draft_group:outcome==='confirmed'?group(entry.snapshot):null});
      var remaining=entries.filter(function (item) { return item!==match; });
      return {write:'put',value:remaining,result:{retained:false}};
    });
  }
  function draftOrder(raw) {
    try {
      var data=JSON.parse(raw);
      return {time:typeof data.updated_at==='number'&&Number.isFinite(data.updated_at)?data.updated_at:0,id:typeof data.draft_id==='string'?data.draft_id:''};
    } catch (_) { return {time:0,id:''}; }
  }
  window.UMCIntakeStore={
    pending:pending,
    beginSend:beginSend,
    confirm:confirm,
    retire:retire,
    readDraft:function (owner) { return update('drafts',owner,function (value) { if(value!==undefined && typeof value!=='string') throw new Error('invalid_draft'); return {result:value || null}; }); },
    writeDraft:function (owner, value) { return update('drafts',owner,function (current) {
      var incoming=draftOrder(value), existing=draftOrder(current);
      var newer=current===undefined || incoming.time>existing.time || (incoming.time===existing.time && incoming.id>=existing.id);
      return {write:newer?'put':null,value:value,result:newer};
    }); },
    clearDraft:function (owner, expected) { return update('drafts',owner,function (value) {
      var remove=!!expected && value===expected;
      try{
        var submitted=JSON.parse(expected), current=JSON.parse(value);
        var versions=Array.isArray(submitted.sources)?submitted.sources.slice():[];
        versions.push(submitted.draft_id);
        if(current && typeof current.draft_id==='string' && versions.includes(current.draft_id))remove=true;
      }catch(_){}
      return {write:remove?'delete':null,result:null};
    }); }
  };
})();

/* Original JPEG upload; browser preview is never server validation. */
(function(){
  'use strict';
  var bridge=window.__umcAppBridge,input=document.getElementById('intake-image');
  if(!bridge||!input)return;
  var token=document.getElementById('intake-image-token'),preview=document.getElementById('intake-image-preview'),remove=document.getElementById('intake-image-remove'),error=document.getElementById('intake-image-error');
  var generation=0,uploading=false,context=null,owner=null;
  var copy={ru:{large:'Изображение должно весить до 5 МБ.',jpeg:'Выберите JPEG 1080 × 1080 px.',dimensions:'Нужен квадратный JPEG 1080 × 1080 px.',invalid:'Не удалось прочитать JPEG. Выберите другой файл.',expired:'Изображение устарело. Прикрепите его ещё раз.',failed:'Изображение не загрузилось. Повторите попытку.',busy:'Загружаем изображение…'},en:{large:'The image must be at most 5 MB.',jpeg:'Choose a 1080 × 1080 JPEG.',dimensions:'Choose a square 1080 × 1080 JPEG.',invalid:'The JPEG could not be read. Choose another file.',expired:'Upload this image again.',failed:'Upload failed. Try again.',busy:'Uploading image…'},kk:{large:'Сурет 5 МБ-тан аспауы керек.',jpeg:'1080 × 1080 JPEG таңдаңыз.',dimensions:'1080 × 1080 шаршы JPEG керек.',invalid:'JPEG оқылмады. Басқа файл таңдаңыз.',expired:'Суретті қайта тіркеңіз.',failed:'Сурет жүктелмеді. Қайталаңыз.',busy:'Сурет жүктелуде…'},be:{large:'Выява павінна быць да 5 МБ.',jpeg:'Выберыце JPEG 1080 × 1080 px.',dimensions:'Патрэбны квадратны JPEG 1080 × 1080 px.',invalid:'JPEG не прачытаны. Выберыце іншы файл.',expired:'Прымацуйце выяву яшчэ раз.',failed:'Выява не загрузілася. Паўтарыце.',busy:'Загрузка выявы…'},uz:{large:'Rasm hajmi 5 MB gacha bo‘lishi kerak.',jpeg:'1080 × 1080 JPEG tanlang.',dimensions:'1080 × 1080 kvadrat JPEG kerak.',invalid:'JPEG o‘qilmadi. Boshqa fayl tanlang.',expired:'Rasmni qayta yuklang.',failed:'Rasm yuklanmadi. Qayta urining.',busy:'Rasm yuklanmoqda…'}};
  function words(){return copy[(window._me||{}).locale]||copy.en;}
  function identity(){return (window.__miniapp_platform||'telegram')+':'+((window._me||{}).user_id||'');}
  function busy(value){uploading=value;var submit=document.getElementById('btn-intake-create');submit.disabled=value||document.getElementById('screen-intake').getAttribute('aria-busy')==='true';if(window.UMCShell)window.UMCShell.syncControls();}
  function changed(){token.dispatchEvent(new Event('input',{bubbles:true}));}
  function clear(){generation++;if(context)context.dispose();context=null;busy(false);input.value='';token.value='';preview.removeAttribute('src');preview.hidden=true;remove.hidden=true;error.textContent='';}
  function active(g,who,ctx){return generation===g&&identity()===who&&(!ctx||ctx.isCurrent());}
  function message(e){var code=e&&e.message||'';return code.indexOf('image_too_large')>=0?words().large:code.indexOf('image_jpeg_required')>=0?words().jpeg:code.indexOf('image_dimensions')>=0?words().dimensions:code.indexOf('image_expired')>=0?words().expired:code.indexOf('image_invalid')>=0?words().invalid:words().failed;}
  input.addEventListener('change',function(){
    var file=input.files[0];if(!file)return;
    clear();changed();if(file.size>5000000){error.textContent=words().large;return;}if(file.type&&file.type!=='image/jpeg'){error.textContent=words().jpeg;return;}
    var g=++generation,who=identity(),ctx=bridge.createRequestContext?bridge.createRequestContext():null;context=ctx;owner=who;busy(true);remove.hidden=false;error.textContent=words().busy;
    var reader=new FileReader();reader.onerror=function(){if(active(g,who,ctx)){busy(false);error.textContent=words().failed;}};
    reader.onload=function(){if(!active(g,who,ctx))return;var result=String(reader.result),request=ctx||bridge;request.request('/orders/images',{image_base64:result.slice(result.indexOf(',')+1)}).then(function(data){if(!active(g,who,ctx))return;token.value=data.image_token;preview.src=result;preview.hidden=false;remove.hidden=false;error.textContent='';busy(false);changed();}).catch(function(e){if(active(g,who,ctx))error.textContent=message(e);}).finally(function(){if(active(g,who,ctx))busy(false);});};reader.readAsDataURL(file);
  });
  remove.addEventListener('click',function(){clear();changed();});
  document.getElementById('form-umc-intake').addEventListener('reset',clear);
  document.addEventListener('umc:app-ready',function(){if(owner&&identity()!==owner)clear();owner=identity();});
  document.addEventListener('umc:intake-policy-ready',function(){
    if(uploading||!token.value||!preview.hidden)return;var g=++generation,who=identity(),ctx=bridge.createRequestContext?bridge.createRequestContext():null;context=ctx;
    (ctx||bridge).request('/orders/images/content',{image_token:token.value}).then(function(data){if(!active(g,who,ctx))return;preview.src='data:image/jpeg;base64,'+data.image_base64;preview.hidden=false;remove.hidden=false;}).catch(function(e){if(active(g,who,ctx)){token.value='';error.textContent=message(e);changed();}});
  });
  var viewContext=null,viewGeneration=0;
  function clearViews(){viewGeneration++;if(viewContext)viewContext.dispose();viewContext=null;document.querySelectorAll('[data-order-image-view]').forEach(function(n){n.remove();});}
  function imageView(host,source){var img=document.createElement('img');img.dataset.orderImageView='';img.alt=({ru:'Изображение задания',en:'Brief image',kk:'Тапсырма суреті',be:'Выява задання',uz:'Topshiriq rasmi'})[(window._me||{}).locale]||'Brief image';img.width=280;img.height=280;img.style.cssText='max-width:100%;height:auto;object-fit:contain;border-radius:12px';img.src=source;host.appendChild(img);}
  document.addEventListener('umc:intake-created',function(){document.querySelectorAll('#intake-result [data-order-image-view]').forEach(function(n){n.remove();});if(token.value&&!preview.hidden)imageView(document.getElementById('intake-result'),preview.src);});
  document.addEventListener('umc:selection-view',function(event){clearViews();var data=event.detail;if(!data||!data.image_token)return;var g=viewGeneration,who=identity(),ctx=bridge.createRequestContext();viewContext=ctx;ctx.request('/orders/images/content',{image_token:data.image_token}).then(function(value){if(g!==viewGeneration||who!==identity()||!ctx.isCurrent())return;imageView(document.getElementById('screen-selection'),'data:image/jpeg;base64,'+value.image_base64);}).catch(function(){if(g!==viewGeneration||!ctx.isCurrent())return;var status=document.createElement('p');status.dataset.orderImageView='';status.className='error';status.textContent=words().failed;document.getElementById('screen-selection').appendChild(status);});});
  document.addEventListener('umc:app-ready',clearViews);
  document.addEventListener('umc:screen-change',function(event){if(event.detail&&event.detail.screen!=='screen-selection'&&viewContext){viewContext.dispose();viewContext=null;viewGeneration++;}});
  window.UMCOrderImages={busy:function(){return uploading;}};
})();

/* Prepare order photos in the browser and upload the previewed JPEG. */
(function(){
  'use strict';
  var bridge=window.__umcAppBridge,input=document.getElementById('intake-image');
  if(!bridge||!input)return;
  var token=document.getElementById('intake-image-token'),preview=document.getElementById('intake-image-preview'),remove=document.getElementById('intake-image-remove'),error=document.getElementById('intake-image-error');
  var generation=0,uploading=false,context=null,owner=null;
  var IMAGE_SIZE = 1080;
  var MAX_IMAGE_BYTES = 5000000;
  var copy = {
    ru: {
      large: 'Не удалось сжать фото. Выберите другое изображение.',
      invalid: 'Не удалось открыть фото. Попробуйте выбрать JPEG или PNG.',
      expired: 'Изображение устарело. Прикрепите его ещё раз.',
      failed: 'Фото не загрузилось. Выберите его ещё раз.',
      busy: 'Подготавливаем и загружаем фото…'
    },
    en: {
      large: 'The photo could not be compressed. Choose another image.',
      invalid: 'The photo could not be opened. Try a JPEG or PNG.',
      expired: 'Upload this image again.',
      failed: 'The photo could not be uploaded. Choose it again.',
      busy: 'Preparing and uploading the photo…'
    },
    kk: {
      large: 'Фотоны сығу мүмкін болмады. Басқа сурет таңдаңыз.',
      invalid: 'Фото ашылмады. JPEG немесе PNG таңдап көріңіз.',
      expired: 'Суретті қайта тіркеңіз.',
      failed: 'Фото жүктелмеді. Оны қайта таңдаңыз.',
      busy: 'Фото дайындалып, жүктелуде…'
    },
    be: {
      large: 'Не ўдалося сціснуць фота. Выберыце іншую выяву.',
      invalid: 'Не ўдалося адкрыць фота. Паспрабуйце выбраць JPEG або PNG.',
      expired: 'Прымацуйце выяву яшчэ раз.',
      failed: 'Фота не загрузілася. Выберыце яго яшчэ раз.',
      busy: 'Рыхтуем і загружаем фота…'
    },
    uz: {
      large: 'Suratni siqib bo‘lmadi. Boshqa rasm tanlang.',
      invalid: 'Surat ochilmadi. JPEG yoki PNG faylini tanlab ko‘ring.',
      expired: 'Rasmni qayta yuklang.',
      failed: 'Surat yuklanmadi. Uni qayta tanlang.',
      busy: 'Surat tayyorlanmoqda va yuklanmoqda…'
    }
  };
  function words(){return copy[(window._me||{}).locale]||copy.en;}
  function identity(){return (window.__miniapp_platform||'telegram')+':'+((window._me||{}).user_id||'');}
  function busy(value){uploading=value;var submit=document.getElementById('btn-intake-create');submit.disabled=value||document.getElementById('screen-intake').getAttribute('aria-busy')==='true';if(window.UMCShell)window.UMCShell.syncControls();}
  function changed(){token.dispatchEvent(new Event('input',{bubbles:true}));}
  function clear(){generation++;if(context)context.dispose();context=null;busy(false);input.value='';token.value='';hidePreview();error.textContent='';}
  function active(g,who,ctx){return generation===g&&identity()===who&&(!ctx||ctx.isCurrent());}
  function hidePreview() {
    preview.removeAttribute('src');
    preview.hidden = true;
    remove.hidden = true;
  }

  function message(error) {
    var code = error && error.message || '';
    if (code.indexOf('image_invalid') >= 0) return words().invalid;
    if (code.indexOf('image_too_large') >= 0) return words().large;
    if (code.indexOf('image_expired') >= 0) return words().expired;
    return words().failed;
  }

  async function preparePhoto(file) {
    var image = new Image();
    var canvas = document.createElement('canvas');
    canvas.width = canvas.height = IMAGE_SIZE;
    var drawing = canvas.getContext('2d');
    var source = URL.createObjectURL(file);

    try {
      image.src = source;
      try {
        await image.decode();
      } catch (_) {
        throw new Error('image_invalid');
      }

      var scale = IMAGE_SIZE / Math.max(image.naturalWidth, image.naturalHeight);
      var width = Math.max(1, Math.round(image.naturalWidth * scale));
      var height = Math.max(1, Math.round(image.naturalHeight * scale));
      drawing.fillStyle = '#fff';
      drawing.fillRect(0, 0, IMAGE_SIZE, IMAGE_SIZE);
      drawing.imageSmoothingQuality = 'high';
      drawing.drawImage(image, Math.floor((IMAGE_SIZE - width) / 2),
        Math.floor((IMAGE_SIZE - height) / 2), width, height);
    } finally {
      image.removeAttribute('src');
      URL.revokeObjectURL(source);
    }

    var jpeg = await new Promise(function (resolve) {
      canvas.toBlob(resolve, 'image/jpeg', 0.86);
    });
    if (!jpeg || jpeg.type !== 'image/jpeg') throw new Error('image_encoding_failed');
    if (jpeg.size > MAX_IMAGE_BYTES) throw new Error('image_too_large');

    return new Promise(function (resolve, reject) {
      var reader = new FileReader();
      reader.onload = function () { resolve(String(reader.result)); };
      reader.onerror = function () { reject(reader.error); };
      reader.readAsDataURL(jpeg);
    });
  }

  input.addEventListener('change', async function () {
    var file = input.files[0];
    if (!file) return;

    clear();
    changed();
    var currentGeneration = generation;
    var who = identity();
    var ctx = bridge.createRequestContext();
    context = ctx;
    owner = who;
    busy(true);
    remove.hidden = false;
    error.textContent = words().busy;

    try {
      var result = await preparePhoto(file);
      if (!active(currentGeneration, who, ctx)) return;
      preview.src = result;
      preview.hidden = false;

      var data = await ctx.request('/orders/images', {
        image_base64: result.slice(result.indexOf(',') + 1)
      });
      if (!active(currentGeneration, who, ctx)) return;
      token.value = data.image_token;
      error.textContent = '';
      changed();
    } catch (failure) {
      if (active(currentGeneration, who, ctx)) {
        hidePreview();
        error.textContent = message(failure);
      }
    } finally {
      if (active(currentGeneration, who, ctx)) busy(false);
    }
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

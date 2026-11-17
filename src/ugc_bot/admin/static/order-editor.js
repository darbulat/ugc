const editor = document.querySelector("#order-edit-form");

const closureField = document.getElementById("order-closure-field");
if (closureField) {
  const status = editor.elements.namedItem("status");
  const reason = editor.elements.namedItem("closure_reason");
  const updateClosureField = () => {
    const closing = status.value === "closed";
    closureField.hidden = !closing;
    reason.required = closing && closureField.dataset.reasonRequired === "1";
  };
  status.addEventListener("change", updateClosureField);
  updateClosureField();
}

for (const counter of editor.querySelectorAll("[data-character-limit]")) {
  const field = document.getElementById(counter.dataset.field);
  const limit = Number(counter.dataset.characterLimit);
  const saved = field.value;
  const update = () => {
    const length = Array.from(field.value).length;
    const exceeded = length > limit;
    counter.textContent = exceeded
      ? `${length} / ${limit} · превышение на ${length - limit}`
      : `${length} / ${limit}`;
    counter.classList.toggle("text-danger", exceeded);
    field.setCustomValidity(exceeded && field.value !== saved
      ? `Максимум ${limit} символов.`
      : "");
  };
  field.addEventListener("input", update);
  update();
}

const audience = document.getElementById("order-edit-audience");
const watched = [...audience.querySelectorAll("input, select, textarea"),
  editor.elements.namedItem("order_type"), editor.elements.namedItem("price")];
const savedAudience = watched.map(readValue);
const savedCount = document.getElementById("order-audience-saved");
const savedCountValue = document.getElementById("order-audience-saved-count");
const savedCountCaption = document.getElementById("order-audience-saved-caption");
const savedCountHint = document.getElementById("order-audience-saved-hint");
const preview = document.getElementById("order-audience-preview");
const previewCount = document.getElementById("order-audience-count");
const previewCaption = document.getElementById("order-audience-caption");
const previewHint = document.getElementById("order-audience-hint");
const {previewUrl, needed} = preview.parentElement.dataset;
let audienceTimer;
let audienceRequest;

for (const field of watched) field.addEventListener("input", scheduleAudiencePreview);

function scheduleAudiencePreview() {
  clearTimeout(audienceTimer);
  audienceRequest?.abort();
  const changed = watched.some((item, i) => readValue(item) !== savedAudience[i]);
  savedCount.hidden = changed;
  preview.hidden = !changed;
  if (!changed) {
    if (!savedCount.dataset.loaded) updateAudiencePreview(true);
    return;
  }
  previewCount.hidden = true;
  previewCaption.textContent = "Считаем выборку…";
  previewHint.textContent = "По фильтрам в редакторе";
  previewCaption.classList.remove("text-danger");
  audienceTimer = setTimeout(() => updateAudiencePreview(false), 450);
}

async function updateAudiencePreview(saved) {
  const count = saved ? savedCountValue : previewCount;
  const caption = saved ? savedCountCaption : previewCaption;
  const hint = saved ? savedCountHint : previewHint;
  const controller = new AbortController();
  audienceRequest = controller;
  const url = new URL(previewUrl, location.href);
  for (const field of watched) {
    const value = field.tagName === "SELECT" && field.value === "__None" ? "" : readValue(field);
    url.searchParams.set(field.name, value);
  }
  try {
    const response = await fetch(url, {signal: controller.signal, cache: "no-store"});
    const result = await response.json();
    if (controller.signal.aborted) return;
    if (!response.ok) throw new Error(result.detail);
    const shortage = result.count < Number(needed);
    count.textContent = result.count;
    count.classList.toggle("order-editor__audience-value--short", shortage);
    count.hidden = false;
    caption.textContent = "Подходящие креаторы";
    caption.classList.remove("text-danger");
    hint.textContent = saved
      ? (shortage ? `По сохранённым фильтрам. В заказе нужно ${needed}.` : "По сохранённым фильтрам")
      : (shortage ? `В заказе нужно ${needed}. Фильтры ещё не сохранены.` : "По несохранённым фильтрам");
    if (saved) savedCount.dataset.loaded = "true";
  } catch (error) {
    if (controller.signal.aborted) return;
    caption.textContent = "Выборка недоступна";
    caption.classList.add("text-danger");
    hint.textContent = error.message || "Проверьте фильтры.";
  }
}

updateAudiencePreview(true);

function readValue(field) {
  return field.type === "checkbox" ? field.checked : field.value;
}

editor.addEventListener("submit", (event) => {
  if (event.submitter?.value === "Activate order" &&
      !window.confirm("Активировать заказ? Подходящим креаторам будет отправлено предложение.")) {
    event.preventDefault();
  }
});

const briefLink = editor.elements.namedItem("brief_link");
const offerText = editor.elements.namedItem("offer_text");
const photoId = editor.elements.namedItem("product_photo_file_id");
const photoPrompt = document.getElementById("order-photo-prompt");
const promptText = document.getElementById("order-photo-prompt-text");
const promptFeedback = document.getElementById("order-photo-prompt-feedback");

function updateMaterials() {
  const hasPhoto = Boolean(photoId.value.trim());
  document.getElementById("order-brief-missing").hidden = Boolean(briefLink.value.trim());
  document.getElementById("order-photo-missing").hidden = hasPhoto;
  const brief = offerText.value.trim();
  promptText.value = [
    "Создай квадратную обложку 1:1 для объявления о поиске UGC-креаторов в Telegram.",
    "Выбери один сюжет из задания. Покажи продукт или его использование в естественной обстановке, с ясным главным объектом и читаемой композицией на экране телефона.",
    "Изображение без надписей, водяных знаков, выдуманных логотипов и интерфейсов. Исключи личные данные и иллюстрации условий оплаты.",
    brief && `Бриф для визуального контекста:\n${brief}`,
  ].filter(Boolean).join("\n\n");
  promptFeedback.textContent = "";
}

for (const field of [briefLink, offerText, photoId]) field.addEventListener("input", updateMaterials);
updateMaterials();
document.getElementById("order-photo-prompt-copy").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(promptText.value);
    promptFeedback.textContent = "Промпт скопирован.";
  } catch {
    photoPrompt.open = true;
    promptText.select();
    promptFeedback.textContent = "Скопируйте выделенный текст.";
  }
});

  document.getElementById('order-photo-upload-button')?.addEventListener('click', async () => {
    const picker = document.getElementById('order-photo-upload');
    const status = document.getElementById('order-photo-upload-status');
    const button = document.getElementById('order-photo-upload-button');
    if (!picker.files.length) { status.textContent = 'Сначала выберите изображение.'; return; }
    const data = new FormData(); data.append('photo', picker.files[0]);
    button.disabled = true; status.textContent = 'Загружаю в Telegram…';
    try {
      const response = await fetch('/admin/order-photo-upload', {method: 'POST', body: data, credentials: 'same-origin'});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Не удалось загрузить фото');
      const field = document.querySelector('[name="product_photo_file_id"]');
      if (!field) throw new Error('Не найдено поле Telegram file_id');
      field.value = result.file_id;
      updateMaterials();
      status.textContent = 'Готово. Сохраните заказ, чтобы применить картинку.';
    } catch (error) { status.textContent = error.message; }
    finally { button.disabled = false; }
  });

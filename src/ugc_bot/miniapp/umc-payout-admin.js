/* Protected payout administration. All form and read state dies with this view. */
(function () {
  'use strict';
  var screen = document.getElementById('screen-payout-admin');
  var bridge = window.__umcAppBridge, ids = window.UMCPayoutState, money = window.UMCPayoutMoney;
  if (!screen || !bridge || !bridge.createRequestContext || !ids || !money) return;
  var copy = {
    en: {
      title:'Payout administration',queue:'Request queue',requirements:'Requirements',back:'Back',refresh:'Refresh',next:'Next',loading:'Loading…',error:'Confirmed data unavailable. Refresh the protected status.',forbidden:'Current administrator access is required.',session:'The account or session changed. Reopen this view.',empty:'No records.',asof:'Observed at',paused:'New financial operations are paused. Reporting an actual bank observation may remain available.'
    }, ru: {
      title:'Управление выплатами',queue:'Очередь заявок',requirements:'Требования',back:'Назад',refresh:'Обновить',next:'Следующие',loading:'Загрузка…',error:'Подтверждённые данные недоступны. Обновите защищённый статус.',forbidden:'Нужны действующие права администратора.',session:'Аккаунт или сессия изменились. Откройте экран заново.',empty:'Записей нет.',asof:'Данные на',paused:'Новые финансовые операции приостановлены. Запись фактического банковского наблюдения может оставаться доступной.'
    }, kk: {
      title:'Төлемдерді басқару',queue:'Өтінімдер кезегі',requirements:'Талаптар',back:'Артқа',refresh:'Жаңарту',next:'Келесі',loading:'Жүктелуде…',error:'Расталған деректер қолжетімсіз. Қорғалған мәртебені жаңартыңыз.',forbidden:'Әкімшінің ағымдағы рұқсаты қажет.',session:'Аккаунт немесе сессия өзгерді. Экранды қайта ашыңыз.',empty:'Жазбалар жоқ.',asof:'Деректер уақыты',paused:'Жаңа қаржылық операциялар тоқтатылған. Нақты банк дерегін тіркеу қолжетімді болуы мүмкін.'
    }, be: {
      title:'Кіраванне выплатамі',queue:'Чарга заявак',requirements:'Патрабаванні',back:'Назад',refresh:'Абнавіць',next:'Наступныя',loading:'Загрузка…',error:'Пацверджаныя даныя недаступныя. Абнавіце абаронены статус.',forbidden:'Патрэбны дзейныя правы адміністратара.',session:'Акаўнт або сесія змяніліся. Адкрыйце экран зноў.',empty:'Запісаў няма.',asof:'Даныя на',paused:'Новыя фінансавыя аперацыі прыпыненыя. Запіс фактычнага банкаўскага назірання можа заставацца даступным.'
    }, uz: {
      title:'To‘lovlarni boshqarish',queue:'Arizalar navbati',requirements:'Talablar',back:'Orqaga',refresh:'Yangilash',next:'Keyingi',loading:'Yuklanmoqda…',error:'Tasdiqlangan ma’lumotlar mavjud emas. Himoyalangan holatni yangilang.',forbidden:'Amaldagi administrator huquqi kerak.',session:'Hisob yoki sessiya o‘zgardi. Oynani qayta oching.',empty:'Yozuvlar yo‘q.',asof:'Ma’lumot vaqti',paused:'Yangi moliyaviy operatsiyalar to‘xtatilgan. Haqiqiy bank kuzatuvini qayd etish mavjud bo‘lishi mumkin.'
    }
  };
  var s = {
    life:0, selection:0, formGeneration:0, bound:null, context:null, actor:null, mode:'queue', selected:null, detail:null, reads:{
    }, form:null, operation:null, unresolved:null
  };
  var formCleanups=new WeakMap();
  function c() {
    return copy[(window._me || {
    }).locale] || copy.ru;
  }
  var unavailableCopy={
    ru:'Шифрование недоступно. Защищённые исторические чтения остаются независимыми.',
    en:'Encryption is unavailable. Protected historical reads remain independent.',
    kk:'Шифрлау қолжетімсіз. Қорғалған тарихи оқу тәуелсіз қалады.',
    be:'Шыфраванне недаступнае. Абароненыя гістарычныя чытанні застаюцца незалежнымі.',
    uz:'Shifrlash mavjud emas. Himoyalangan tarixiy o‘qish mustaqil qoladi.'
  };
  function safeMessage(code) {
    if(code==='financial_payouts_disabled')return c().paused;
    if(['payout_encryption_configuration_required','payout_requisites_authentication_failed'].indexOf(code)>=0)return unavailableCopy[(window._me||{}).locale]||unavailableCopy.ru;
    if(['payout_version_conflict','payout_requirements_changed','payout_document_mismatch','payout_stale_execution'].indexOf(code)>=0)return t('changed');
    if(['payout_bank_reference_reused','payout_bank_amount_or_currency_mismatch','payout_bank_account_mismatch','payout_bank_recipient_mismatch','payout_bank_settlement_proof_incomplete','payout_money_application_review_required'].indexOf(code)>=0)return t('reviewRequired');
    return c().error;
  }
  var flagCopy={
    ru:['Включено','Приостановлено'],en:['Enabled','Suspended'],
    kk:['Қосылған','Тоқтатылған'],be:['Уключана','Прыпынена'],
    uz:['Yoqilgan','To‘xtatilgan']
  };
  var secureKeyCopy={
    ru:'Безопасное создание ключа операции недоступно. Чтения остаются доступны.',
    en:'Secure operation keys are unavailable. Reads remain available.',
    kk:'Қауіпсіз операция кілттері қолжетімсіз. Оқу қолжетімді.',
    be:'Бяспечныя ключы аперацый недаступныя. Чытанні застаюцца даступнымі.',
    uz:'Xavfsiz operatsiya kalitlari mavjud emas. O‘qish mavjud.'
  };
  var vocabulary={
    effective:['Действующая публикация',
    'Effective publication',
    'Қолданыстағы жарияланым',
    'Дзейная публікацыя',
    'Amaldagi nashr'],latest:['Последняя публикация, включая будущую',
    'Latest publication, including future',
    'Соңғы, соның ішінде болашақ жарияланым',
    'Апошняя публікацыя, уключна з будучай',
    'So‘nggi, kelajakdagi nashr ham'], newPublication:['Новая публикация',
    'New publication',
    'Жаңа жарияланым',
    'Новая публікацыя',
    'Yangi nashr'],draft:['Использовать как черновик',
    'Use as draft',
    'Нобай ретінде пайдалану',
    'Выкарыстаць як чарнавік',
    'Qoralama sifatida ishlatish'],enabled:['Разрешить новые заявки',
    'Enable new requests',
    'Жаңа өтінімдерге рұқсат',
    'Дазволіць новыя заяўкі',
    'Yangi arizalarga ruxsat'],effective_from:['Время вступления в силу с часовым поясом',
    'Effective time with time zone',
    'Күшіне ену уақыты және белдеуі',
    'Час уступлення ў сілу з часавым поясам',
    'Kuchga kirish vaqti va mintaqasi'], reason:['Причина',
    'Reason',
    'Себеп',
    'Прычына',
    'Sabab'],legal_reference:['Правовое основание, ссылка-идентификатор',
    'Legal reference',
    'Құқықтық негіз сілтемесі',
    'Прававая спасылка',
    'Huquqiy havola'],terms_reference:['Идентификатор условий',
    'Terms reference',
    'Шарттар сілтемесі',
    'Спасылка на ўмовы',
    'Shartlar havolasi'],evidence_reference:['Ссылка на фактическое подтверждение',
    'Actual evidence reference',
    'Нақты дәлел сілтемесі',
    'Спасылка на фактычны доказ',
    'Haqiqiy dalil havolasi'], required_fields:['Ключи обязательных полей, по одному на строку',
    'Required field keys, one per line',
    'Міндетті өріс кілттері, әр жолда біреу',
    'Ключы абавязковых палёў, па адным на радок',
    'Majburiy maydon kalitlari, har satrda bitta'],definitions:['Определения полей: JSON ключей, подписей, пояснений и допустимых значений',
    'Field definitions: JSON keys, labels, help and permitted values',
    'Өріс анықтамалары: JSON кілттері, атаулар, көмек және рұқсат етілген мәндер',
    'Вызначэнні палёў: JSON ключоў, подпісаў, даведкі і дазволеных значэнняў',
    'Maydon ta’riflari: JSON kalitlar, nomlar, izohlar va ruxsat etilgan qiymatlar'], document:['Полный текст документа',
    'Full document text',
    'Құжаттың толық мәтіні',
    'Поўны тэкст дакумента',
    'Hujjatning to‘liq matni'],source_locale:['Язык исходного документа',
    'Document source language',
    'Құжаттың бастапқы тілі',
    'Мова зыходнага дакумента',
    'Hujjatning asl tili'],documentMode:['Источник документа',
    'Document source',
    'Құжат көзі',
    'Крыніца дакумента',
    'Hujjat manbasi'],newDocument:['Новый документ',
    'New document',
    'Жаңа құжат',
    'Новы дакумент',
    'Yangi hujjat'],reuse:['Существующий неизменяемый документ',
    'Existing immutable document',
    'Бар өзгермейтін құжат',
    'Існуючы нязменны дакумент',
    'Mavjud o‘zgarmas hujjat'],none:['Без документа: только приостановка',
    'No document: suspension only',
    'Құжатсыз: тек тоқтату',
    'Без дакумента: толькі прыпыненне',
    'Hujjatsiz: faqat to‘xtatish'], review:['Проверить решение',
    'Review decision',
    'Шешімді тексеру',
    'Праверыць рашэнне',
    'Qarorni tekshirish'],publish:['Опубликовать требования',
    'Publish requirements',
    'Талаптарды жариялау',
    'Апублікаваць патрабаванні',
    'Talablarni nashr etish'],suspend:['Опубликовать приостановку',
    'Publish suspension',
    'Тоқтатуды жариялау',
    'Апублікаваць прыпыненне',
    'To‘xtatishni nashr etish'],receipt:['Исходный ответ операции',
    'Original operation reply',
    'Операцияның бастапқы жауабы',
    'Зыходны адказ аперацыі',
    'Operatsiyaning dastlabki javobi'],unknown:['Результат неизвестен. Проверьте защищённую историю. Повторная операция не отправляется.',
    'Result unknown. Check protected history. No replacement operation will be sent.',
    'Нәтиже белгісіз. Қорғалған тарихты тексеріңіз. Қайталама операция жіберілмейді.',
    'Вынік невядомы. Праверце абароненую гісторыю. Паўторная аперацыя не адпраўляецца.',
    'Natija noma’lum. Himoyalangan tarixni tekshiring. Takroriy operatsiya yuborilmaydi.'],invalid:['Проверьте обязательные поля и точный формат данных.',
    'Check required fields and exact data formats.',
    'Міндетті өрістер мен нақты пішімді тексеріңіз.',
    'Праверце абавязковыя палі і дакладны фармат даных.',
    'Majburiy maydonlar va aniq ma’lumot formatini tekshiring.'],changed:['Данные изменились. Обновите статус и примите новое явное решение.',
    'Data changed. Refresh status and make a new explicit decision.',
    'Деректер өзгерді. Мәртебені жаңартып, жаңа шешім қабылдаңыз.',
    'Даныя змяніліся. Абнавіце статус і прыміце новае яўнае рашэнне.',
    'Ma’lumot o‘zgardi. Holatni yangilab, yangi aniq qaror qabul qiling.']
  };
  function t(key) {
    var index=['ru',
    'en',
    'kk',
    'be',
    'uz'].indexOf((window._me||{
    }).locale);
    return vocabulary[key]?vocabulary[key][index<0?0:index]:key;
  }
  Object.assign(vocabulary,{
    approve:['Одобрить заявку',
    'Approve request',
    'Өтінімді мақұлдау',
    'Ухваліць заяўку',
    'Arizani tasdiqlash'],reject:['Отклонить заявку',
    'Reject request',
    'Өтінімді қабылдамау',
    'Адхіліць заяўку',
    'Arizani rad etish'],start:['Подготовить ручной перевод',
    'Prepare manual transfer',
    'Қолмен аударымды дайындау',
    'Падрыхтаваць ручны перавод',
    'Qo‘lda o‘tkazmani tayyorlash'],escalate:['Зафиксировать просроченную проверку',
    'Record overdue escalation',
    'Кешіккен тексеруді тіркеу',
    'Зафіксаваць пратэрмінаваную праверку',
    'Kechikkan tekshiruvni qayd etish'],reveal_requisites:['Показать защищённые реквизиты',
    'Reveal protected requisites',
    'Қорғалған деректемелерді көрсету',
    'Паказаць абароненыя рэквізіты',
    'Himoyalangan rekvizitlarni ko‘rsatish'],hide:['Скрыть реквизиты',
    'Hide requisites',
    'Деректемелерді жасыру',
    'Схаваць рэквізіты',
    'Rekvizitlarni yashirish'], prepareNotice:['Создаётся только запись исполнения. Деньги переводятся вне UMC. Это действие не отправляет банковский платёж.',
    'This creates an execution record only. Money is handled outside UMC. This action does not send a bank payment.',
    'Тек орындау жазбасы жасалады. Ақша UMC-ден тыс аударылады. Бұл әрекет банк төлемін жібермейді.',
    'Ствараецца толькі запіс выканання. Грошы пераводзяцца па-за UMC. Гэта дзеянне не адпраўляе банкаўскі плацёж.',
    'Faqat ijro yozuvi yaratiladi. Pul UMC tashqarisida o‘tkaziladi. Bu amal bank to‘lovini yubormaydi.'], revealNotice:['Просмотр будет записан с вашей причиной. Показанные реквизиты — ожидаемые данные, не банковское подтверждение.',
    'This view is audited with your reason. Revealed requisites are expected data, not bank evidence.',
    'Қарау себебіңізбен тіркеледі. Көрсетілген деректемелер — күтілетін дерек, банк дәлелі емес.',
    'Прагляд запісваецца з вашай прычынай. Рэквізіты — чаканыя даныя, а не банкаўскі доказ.',
    'Ko‘rish sababingiz bilan qayd etiladi. Ko‘rsatilgan rekvizitlar kutilgan ma’lumot, bank dalili emas.'], currentExecution:['Текущее подтверждённое исполнение',
    'Current authoritative execution',
    'Ағымдағы расталған орындау',
    'Бягучае пацверджанае выкананне',
    'Joriy tasdiqlangan ijro'],requested_at:['Исходное время заявки',
    'Original request time',
    'Бастапқы өтінім уақыты',
    'Зыходны час заяўкі',
    'Dastlabki ariza vaqti'],deadline_at:['Исходный срок проверки',
    'Original review deadline',
    'Бастапқы тексеру мерзімі',
    'Зыходны тэрмін праверкі',
    'Dastlabki tekshiruv muddati'],overdue:['Срок проверки истёк по данным сервера',
    'Review overdue according to server',
    'Сервер бойынша тексеру мерзімі өтті',
    'Тэрмін праверкі мінуў паводле сервера',
    'Serverga ko‘ra tekshiruv muddati o‘tgan'],readAttempt:['Защищённые чтения завершены. Отсутствие записи не доказывает отсутствие отложенной операции.',
    'Protected read attempts completed. An absent record does not prove a delayed operation cannot arrive.',
    'Қорғалған оқу аяқталды. Жазбаның жоқтығы кешіккен операция болмайтынын дәлелдемейді.',
    'Абароненыя чытанні завершаныя. Адсутнасць запісу не даказвае адсутнасць адкладзенай аперацыі.',
    'Himoyalangan o‘qish tugadi. Yozuv yo‘qligi kechikkan operatsiya kelmasligini isbotlamaydi.']
  });
  Object.assign(vocabulary,{
    requirements_id:['Публикация требований',
    'Requirements publication',
    'Талаптар жарияланымы',
    'Публікацыя патрабаванняў',
    'Talablar nashri'],stateReserved:['Зарезервировано, в обработке',
    'Reserved, processing',
    'Резервтелген, өңделуде',
    'Зарэзервавана, у апрацоўцы',
    'Zaxiralangan, ko‘rib chiqilmoqda'],stateApproved:['Одобрено, в обработке',
    'Approved, processing',
    'Мақұлданған, өңделуде',
    'Ухвалена, у апрацоўцы',
    'Tasdiqlangan, ko‘rib chiqilmoqda'],stateExecuting:['Исполнение подготовлено, в обработке',
    'Execution prepared, processing',
    'Орындау дайындалған, өңделуде',
    'Выкананне падрыхтаванае, у апрацоўцы',
    'Ijro tayyorlangan, ko‘rib chiqilmoqda'],originAccount:['Ожидаемый исходный банковский счёт/область',
    'Expected origin bank account/scope',
    'Күтілетін бастапқы банк шоты/аясы',
    'Чаканы зыходны банкаўскі рахунак/вобласць',
    'Kutilgan boshlang‘ich bank hisobi/doirasi'],destination:['Маска реквизитов',
    'Masked destination',
    'Деректемелер маскасы',
    'Маска рэквізітаў',
    'Rekvizitlar niqobi']
  });
  Object.assign(vocabulary,{
    events:['События',
    'Events',
    'Оқиғалар',
    'Падзеі',
    'Hodisalar'],intents:['Подготовленные исполнения',
    'Prepared executions',
    'Дайындалған орындаулар',
    'Падрыхтаваныя выкананні',
    'Tayyorlangan ijrolar'],outcomes:['Банковские наблюдения',
    'Bank observations',
    'Банк бақылаулары',
    'Банкаўскія назіранні',
    'Bank kuzatuvlari'],settlements:['Применённые расчёты',
    'Applied settlements',
    'Қолданылған есеп айырысулар',
    'Ужытыя разлікі',
    'Qo‘llangan hisob-kitoblar'], request_id:['Заявка',
    'Request',
    'Өтінім',
    'Заяўка',
    'Ariza'],version:['Версия записи',
    'Record version',
    'Жазба нұсқасы',
    'Версія запісу',
    'Yozuv versiyasi'],state:['Текущий статус',
    'Current status',
    'Ағымдағы мәртебе',
    'Бягучы статус',
    'Joriy holat'],action:['Действие',
    'Action',
    'Әрекет',
    'Дзеянне',
    'Amal'],actor_id:['Оператор',
    'Operator',
    'Оператор',
    'Аператар',
    'Operator'],execution_id:['Исполнение',
    'Execution',
    'Орындау',
    'Выкананне',
    'Ijro'],fence:['Защитный идентификатор исполнения',
    'Execution fence',
    'Орындаудың қорғаныс идентификаторы',
    'Ахоўны ідэнтыфікатар выканання',
    'Ijroning himoya identifikatori'],prepared_at:['Подготовлено',
    'Prepared at',
    'Дайындалған уақыт',
    'Падрыхтавана',
    'Tayyorlangan vaqt'], bank_account:['Фактический банковский счёт/область',
    'Actual bank account/scope',
    'Нақты банк шоты/аясы',
    'Фактычны банкаўскі рахунак/вобласць',
    'Haqiqiy bank hisobi/doirasi'],bank_reference:['Фактическая банковская ссылка',
    'Actual bank reference',
    'Нақты банк сілтемесі',
    'Фактычная банкаўская спасылка',
    'Haqiqiy bank havolasi'],amount_minor:['Сумма в минимальных единицах',
    'Amount in minor units',
    'Ең кіші бірліктегі сома',
    'Сума ў найменшых адзінках',
    'Eng kichik birlikdagi summa'],currency:['Валюта',
    'Currency',
    'Валюта',
    'Валюта',
    'Valyuta'],status:['Наблюдаемый результат',
    'Observed result',
    'Бақыланған нәтиже',
    'Назіраны вынік',
    'Kuzatilgan natija'],settled_at:['Фактическое время расчёта с часовым поясом',
    'Actual settlement time with time zone',
    'Нақты есеп айырысу уақыты мен белдеуі',
    'Фактычны час разліку з часавым поясам',
    'Haqiqiy hisob-kitob vaqti va mintaqasi'],evidence_hash:['SHA-256 фактического подтверждения',
    'Actual evidence SHA-256',
    'Нақты дәлелдің SHA-256',
    'SHA-256 фактычнага доказу',
    'Haqiqiy dalil SHA-256'],recorded_at:['Записано',
    'Recorded at',
    'Тіркелген уақыт',
    'Запісана',
    'Qayd etilgan vaqt'],applied:['Применено к деньгам',
    'Applied to money',
    'Ақшаға қолданылды',
    'Ужыта да грошай',
    'Pulga qo‘llangan'],review_reason:['Причина проверки',
    'Review reason',
    'Тексеру себебі',
    'Прычына праверкі',
    'Tekshiruv sababi'],outcome_id:['Наблюдение',
    'Observation',
    'Бақылау',
    'Назіранне',
    'Kuzatuv'],expected_version:['Ожидаемая версия для записи',
    'Expected record version',
    'Күтілетін жазба нұсқасы',
    'Чаканая версія для запісу',
    'Kutilgan yozuv versiyasi'],version_provenance:['Источник версии',
    'Version provenance',
    'Нұсқа көзі',
    'Крыніца версіі',
    'Versiya manbasi'], record_observation:['Записать банковское наблюдение',
    'Record bank observation',
    'Банк бақылауын тіркеу',
    'Запісаць банкаўскае назіранне',
    'Bank kuzatuvini qayd etish'],retained:['Сохранённое исполнение для фактического отчёта',
    'Retained execution for actual reporting',
    'Нақты есепке сақталған орындау',
    'Захаванае выкананне для фактычнай справаздачы',
    'Haqiqiy hisobot uchun saqlangan ijro'],current_authority:['Текущее подтверждённое состояние',
    'Current authoritative state',
    'Ағымдағы расталған күй',
    'Бягучы пацверджаны стан',
    'Joriy tasdiqlangan holat'],retained_event:['Неизменяемое событие этого исполнения',
    'Immutable event for this execution',
    'Осы орындаудың өзгермейтін оқиғасы',
    'Нязменная падзея гэтага выканання',
    'Ushbu ijroning o‘zgarmas hodisasi'],retained_version_required:['Подтверждённая сохранённая версия недоступна',
    'Proven retained version unavailable',
    'Расталған сақталған нұсқа қолжетімсіз',
    'Пацверджаная захаваная версія недаступная',
    'Tasdiqlangan saqlangan versiya mavjud emas'],operatorVersion:['Ожидаемая версия, записанная оператором; текущие полномочия не подтверждены',
    'Operator-recorded expected version; current authority is unproven',
    'Оператор жазған күтілетін нұсқа; ағымдағы өкілеттік расталмаған',
    'Чаканая версія, запісаная аператарам; бягучыя паўнамоцтвы не пацверджаныя',
    'Operator qayd etgan kutilgan versiya; joriy vakolat tasdiqlanmagan'], observationNotice:['Записывайте только фактически наблюдавшиеся данные. Ожидаемые реквизиты не являются доказательством. Неполное подтверждение сохраняется для проверки и может не примениться к деньгам. Это действие не отправляет перевод.',
    'Record only facts actually observed. Expected requisites are not evidence. Incomplete proof is retained for review and may not apply to money. This action sends no transfer.',
    'Тек нақты бақыланған деректерді жазыңыз. Күтілетін деректемелер дәлел емес. Толық емес дәлел тексеруге сақталып, ақшаға қолданылмауы мүмкін. Бұл әрекет аударым жібермейді.',
    'Запісвайце толькі фактычна назіраныя даныя. Чаканыя рэквізіты не з’яўляюцца доказам. Няпоўны доказ захоўваецца для праверкі і можа не прымяніцца да грошай. Дзеянне не адпраўляе перавод.',
    'Faqat haqiqatda kuzatilgan ma’lumotni yozing. Kutilgan rekvizitlar dalil emas. To‘liq bo‘lmagan dalil tekshiruvga saqlanadi va pulga qo‘llanmasligi mumkin. Bu amal o‘tkazma yubormaydi.'],expectedScope:['Ожидаемая область исполнения, не фактическое подтверждение',
    'Expected execution scope, not actual evidence',
    'Күтілетін орындау аясы, нақты дәлел емес',
    'Чаканая вобласць выканання, не фактычны доказ',
    'Kutilgan ijro doirasi, haqiqiy dalil emas'],notRecorded:['Не записано',
    'Not recorded',
    'Тіркелмеген',
    'Не запісана',
    'Qayd etilmagan'],notApplied:['Не применено',
    'Not applied',
    'Қолданылмаған',
    'Не ўжыта',
    'Qo‘llanmagan'],appliedYes:['Применено',
    'Applied',
    'Қолданылған',
    'Ужыта',
    'Qo‘llangan'],reviewRequired:['Записано для проверки',
    'Recorded for review',
    'Тексеруге тіркелді',
    'Запісана для праверкі',
    'Tekshirish uchun qayd etilgan'],recipientKey:['Фактический ключ поля получателя',
    'Actual recipient field key',
    'Нақты алушы өрісінің кілті',
    'Фактычны ключ поля атрымальніка',
    'Haqiqiy oluvchi maydoni kaliti'],recipientValue:['Фактически подтверждённое значение',
    'Actually evidenced value',
    'Нақты дәлелденген мән',
    'Фактычна пацверджанае значэнне',
    'Haqiqatda tasdiqlangan qiymat'],addRecipient:['Добавить фактическое поле получателя',
    'Add actual recipient field',
    'Нақты алушы өрісін қосу',
    'Дадаць фактычнае поле атрымальніка',
    'Haqiqiy oluvchi maydonini qo‘shish'],remove:['Удалить поле',
    'Remove field',
    'Өрісті жою',
    'Выдаліць поле',
    'Maydonni o‘chirish']
  });
  function node(tag,text,id,className) {
    var n=document.createElement(tag);
    if(text!=null)n.textContent=String(text);
    if(id)n.id=id;
    if(className)n.className=className;
    return n;
  }
  function region(id) {
    return document.getElementById(id);
  }
  function sync() {
    if(window.UMCShell)window.UMCShell.syncControls();
  }
  function active() {
    return screen.classList.contains('active');
  }
  function button(text,id,fn) {
    var b=node('button',text,id,'btn btn-secondary');
    b.type='button';
    b.addEventListener('click',function(){
      if(active()&&!b.disabled)fn();
    });
    return b;
  }
  function message(text) {
    var n=region('admin-error');
    if(n){
      n.textContent=text;
      n.focus();
    }
  }
  function wipe(value) {
    if(!value || typeof value!=='object')return;
    Object.keys(value).forEach(function(k){
      if(value[k]&&typeof value[k]==='object')wipe(value[k]);
      delete value[k];
    });
  }
  function clearReveal() {
    var r=region('admin-reveal');
    if(r){
      r.textContent='';
      r.replaceChildren();
    }
  }
  function clearForm() {
    s.formGeneration++;
    if(s.form){
      var cleanup=formCleanups.get(s.form);
      if(cleanup)cleanup();
      formCleanups.delete(s.form);
      s.form.querySelectorAll('input,textarea,select').forEach(function(n){
        n.value='';
      });
      s.form.textContent='';
      s.form.remove();
      s.form=null;
    }
    if(s.operation){
      if(s.operation.kind!=='reveal')s.unresolved={
        key:s.operation.key,kind:s.operation.kind,request_id:s.selected
      };
      wipe(s.operation.payload);
      s.operation.key=null;
      s.operation=null;
    }
    clearReveal();
    screen.setAttribute('aria-busy','false');
    sync();
  }
  function invalidate(text) {
    clearForm();
    s.life++;
    s.selection++;
    if(s.bound)s.bound.dispose();
    s.bound=null;
    s.context=null;
    s.actor=null;
    s.selected=null;
    s.detail=null;
    s.reads={
    };
    s.unresolved=null;
    ['admin-context',
    'admin-list',
    'admin-detail',
    'admin-history',
    'admin-form',
    'admin-reveal',
    'admin-receipt'].forEach(function(id){
      var r=region(id);
      if(r)r.replaceChildren();
    });
    if(text)message(text);
    sync();
  }
  function valid(life,bound,selection) {
    if(!active()||life!==s.life||bound!==s.bound)return false;
    if(!bound||!bound.isCurrent()){
      invalidate(c().session);
      return false;
    }
    return selection==null||selection===s.selection;
  }
  function guard() {
    return valid(s.life,s.bound);
  }
  function authorityFailure(e) {
    return e&&(e.status===401||e.status===403||e.code==='payout_context_changed');
  }
  function failure(e) {
    if(e&&(e.status===401||e.code==='payout_context_changed')){
      invalidate(c().session);
      return;
    }
    if(e&&e.status===403){
      invalidate(c().forbidden);
      return;
    }
    message(c().error);
  }
  function read(key,path,body,apply,selection,protectedDetail) {
    if(!guard())return Promise.resolve();
    var life=s.life,bound=s.bound,token=(s.reads[key]||0)+1;
    s.reads[key]=token;
    var live=region('admin-live');
    if(live)live.textContent=c().loading;
    return bound.request(path,body).then(function(data){
      if(!valid(life,bound))return;
      // Current-context authority loss applies even to an older selection/read.
      if(protectedDetail&&(!data||!data.observation||!data.action_blockers||!Array.isArray(data.allowed_actions))){
        invalidate(c().forbidden);
        return;
      }
      if(valid(life,bound,selection)&&s.reads[key]===token){
        if(live)live.textContent='';
        return apply(data);
      }
    }).catch(function(e){
      if(!valid(life,bound))return;
      if(authorityFailure(e)){
        failure(e);
        return;
      }
      if(valid(life,bound,selection)&&s.reads[key]===token)failure(e);
    });
  }
  function pageBody(cursor) {
    return {
      limit:20,cursor:cursor||null
    };
  }
  function checkPage(data) {
    if(!data||!Array.isArray(data.entries)||typeof data.has_more!=='boolean'||(data.has_more&&typeof data.next_cursor!=='string'))throw new Error();
    return data;
  }
  var stateNames={
    en:['Processing',
    'Paid',
    'Rejected',
    'Review required',
    'Failed',
    'Unknown',
    'Status unavailable'],ru:['В обработке',
    'Выплачено',
    'Отклонено',
    'Требуется проверка',
    'Не выполнено',
    'Неизвестно',
    'Статус недоступен'],kk:['Өңделуде',
    'Төленді',
    'Қабылданбады',
    'Тексеру қажет',
    'Орындалмады',
    'Белгісіз',
    'Мәртебе қолжетімсіз'],be:['У апрацоўцы',
    'Выплачана',
    'Адхілена',
    'Патрэбна праверка',
    'Не выканана',
    'Невядома',
    'Статус недаступны'],uz:['Ko‘rib chiqilmoqda',
    'To‘langan',
    'Rad etilgan',
    'Tekshirish kerak',
    'Bajarilmadi',
    'Noma’lum',
    'Holat mavjud emas']
  };
  function names() {
    return stateNames[(window._me||{
    }).locale]||stateNames.ru;
  }
  function stateLabel(value) {
    if(value==='reserved')return t('stateReserved');
    if(value==='approved')return t('stateApproved');
    if(value==='executing')return t('stateExecuting');
    var index={
      paid:1,rejected:2,blocked:3,failed:4,unknown:5,unavailable:6
    }
    [value];
    return names()[index==null?6:index];
  }
  function pair(parent,label,value) {
    var dl=node('dl');
    dl.appendChild(node('dt',label));
    dl.appendChild(node('dd',value==null?c().empty:value));
    parent.appendChild(dl);
  }
  function requestSummary(row,parent) {
    pair(parent,'ID',row.request_id);
    var amount=node('p',row.currency==='RUB'?money.format(row.amount_minor):row.amount_minor,'','umc-admin-money');
    parent.appendChild(amount);
    pair(parent,t('state'),stateLabel(row.state));
    pair(parent,c().requirements,row.requirements_id);
    pair(parent,c().asof,row.as_of);
    pair(parent,t('requested_at'),row.requested_at);
    pair(parent,t('deadline_at'),row.deadline_at);
    if(row.overdue===true)parent.appendChild(node('p',t('overdue')));
    if(row.masked_label)pair(parent,t('destination'),row.masked_label);
    if(row.block_reason)pair(parent,names()[3],safeMessage(row.block_reason));
  }
  function loadQueue(cursor) {
    return read('queue','/payouts/read/admin/queue',pageBody(cursor),function(data){
      checkPage(data);
      var r=region('admin-list');
      r.replaceChildren(node('h2',c().queue),node('p',c().asof+': '+data.as_of));
      data.entries.forEach(function(row){
        if(!ids.validId(row.request_id))return;
        var item=node('article');
        requestSummary(row,item);
        var b=button(c().queue,null,function(){
          selectRequest(row.request_id);
        });
        b.dataset.adminSelect='';
        item.appendChild(b);
        r.appendChild(item);
      });
      if(!data.entries.length)r.appendChild(node('p',c().empty));
      if(data.has_more)r.appendChild(button(c().next,'admin-queue-next',function(){
        loadQueue(data.next_cursor);
      }));
    });
  }
  function selectRequest(id) {
    if(!guard()||!ids.validId(id))return;
    clearForm();
    s.selection++;
    s.selected=id;
    s.detail=null;
    region('admin-detail').replaceChildren();
    region('admin-history').replaceChildren();
    region('admin-receipt').replaceChildren();
    loadDetail(id,s.selection);
  }
  function loadDetail(id,selection) {
    return read('detail','/payouts/read/'+id+'/detail',{
    },function(data){
      if(data.request_id!==id)throw new Error();
      s.detail=data;
      var r=region('admin-detail');
      r.replaceChildren(node('h2',c().queue));
      requestSummary(data,r);
      r.appendChild(node('p',t('version')+': '+(data.version==null?t('notRecorded'):data.version),'admin-detail-version'));
      if(data.current_execution){
        var scope=node('details');
        scope.appendChild(node('summary',t('currentExecution')));
        ['execution_id',
        'fence',
        'prepared_at',
        'bank_account',
        'expected_version',
        'version_provenance'].forEach(function(k){
          pair(scope,t(k==='bank_account'?'originAccount':k),k==='version_provenance'?t(data.current_execution[k]):data.current_execution[k]);
        });
        r.appendChild(scope);
      }
      renderDecisionButtons();
      renderObservationButtons();
      renderHistoryButtons();
    },selection,true);
  }
  function actionAllowed(action) {
    return guard()&&s.detail&&s.detail.request_id===s.selected&&s.detail.allowed_actions.indexOf(action)>=0;
  }
  function renderDecisionButtons() {
    var r=region('admin-detail');
    ['review',
    'reject',
    'start',
    'escalate',
    'reveal_requisites'].forEach(function(action){
      if(!actionAllowed(action))return;
      var b=button(t(action==='review'?'approve':action),'admin-action-'+action,function(){
        openDecision(action);
      });
      b.disabled=!!s.unresolved;
      r.appendChild(b);
    });
    Object.keys(s.detail.action_blockers).forEach(function(action){
      if(['ordinary','review','reject','start','escalate','reveal_requisites','record_observation'].indexOf(action)<0)return;
      var reasons=s.detail.action_blockers[action];
      if(Array.isArray(reasons))reasons.forEach(function(code){r.appendChild(node('p',(action==='ordinary'?t('review'):t(action==='review'?'approve':action))+': '+safeMessage(code)));});
    });
  }
  function openDecision(action) {
    if(!actionAllowed(action)||s.unresolved||s.operation)return;
    var id=s.selected,version=s.detail.version,isReveal=action==='reveal_requisites';
    if(!isReveal&&!integerVersion(version,false))return;
    var f=makeForm(t(action==='review'?'approve':action));
    if(action==='start')f.appendChild(node('p',t('prepareNotice')));
    if(isReveal)f.appendChild(node('p',t('revealNotice')));
    pair(f,'ID',id);
    if(!isReveal)pair(f,t('version'),version);
    var reason=field(f,'reason',t('reason'),'textarea','',true);
    reason.maxLength=4000;
    var evidence=isReveal?null:field(f,'evidence-reference',t('evidence_reference'),'text','',action==='review'||action==='start');
    if(evidence)evidence.maxLength=4000;
    bindReview(f,function(){
      if(!boundedText(reason.value,4000)||(evidence&&evidence.value.length>4000)||((action==='review'||action==='start')&&!boundedText(evidence.value,4000)))throw new Error();
      return isReveal?{
        reason:reason.value
      }
      :{
        request_id:id,expected_version:version,action:action,reason:reason.value,evidence_reference:evidence.value
      };
    },isReveal?'/payouts/admin/'+id+'/requisites':'/payouts/admin/command',isReveal?'reveal':'decision',t(action==='review'?'approve':action),function(){
      return actionAllowed(action)&&(isReveal||s.detail.version===version);
    });
  }
  function renderHistoryButtons() {
    var r=region('admin-history');
    if(r.hasChildNodes())return;
    ['events',
    'intents',
    'outcomes',
    'settlements'].forEach(function(kind){
      r.appendChild(button(t(kind),'admin-history-'+kind,function(){
        loadHistory(kind,null,s.selection);
      }));
      r.appendChild(node('section',null,'admin-history-'+kind+'-page'));
    });
  }
  var historyFields={
    events:['version',
    'action',
    'state',
    'actor_id',
    'reason',
    'recorded_at',
    'evidence_reference'],intents:['execution_id',
    'fence',
    'bank_account',
    'prepared_at',
    'amount_minor',
    'currency',
    'version',
    'version_provenance'],outcomes:['outcome_id',
    'execution_id',
    'status',
    'amount_minor',
    'currency',
    'settled_at',
    'bank_account',
    'bank_reference',
    'evidence_reference',
    'evidence_hash',
    'recorded_at',
    'applied',
    'review_reason'],settlements:['execution_id',
    'outcome_id',
    'amount_minor',
    'currency',
    'bank_account',
    'bank_reference',
    'settled_at']
  };
  function loadHistory(kind,cursor,selection) {
    var id=s.selected;
    if(!id)return Promise.resolve();
    return read('history:'+kind,'/payouts/read/admin/'+id+'/history/'+kind,pageBody(cursor),function(data){
      checkPage(data);
      var r=region('admin-history-'+kind+'-page');
      r.replaceChildren(node('p',c().asof+': '+data.as_of));
      data.entries.forEach(function(row){
        var record=node('details');
        record.appendChild(node('summary',String(row.execution_id||row.version||t(kind))));
        historyFields[kind].forEach(function(key){
          if(!Object.prototype.hasOwnProperty.call(row,key)||key==='amount_minor'||key==='currency')return;
          var value=row[key];
          if(key==='applied')value=t(value===true?'appliedYes':'notApplied');
          if(key==='review_reason'&&value)value=safeMessage(value);
          if(key==='state'||key==='status')value=stateLabel(value);
          if(key==='version_provenance')value=t(value);
          pair(record,t(kind==='intents'&&key==='bank_account'?'originAccount':key),value);
        });
        if(Object.prototype.hasOwnProperty.call(row,'amount_minor'))pair(record,t('amount_minor'),formatObservedAmount(row.amount_minor,row.currency));
        if(kind==='outcomes'&&row.applied===false)record.appendChild(node('p',t('reviewRequired')));
        if(kind==='events'&&row.resulting_state)pair(record,c().queue,stateLabel(row.resulting_state.state));
        if(kind==='intents'&&canObserve()){
          var scope=selectObservationScope(row,true);
          if(scope){
            var b=button(t('record_observation'),null,function(){
              openObservation(scope);
            });
            b.dataset.adminHistoryObserve='';
            b.disabled=!!s.unresolved;
            record.appendChild(b);
          }
        }
        r.appendChild(record);
      });
      if(!data.entries.length)r.appendChild(node('p',c().empty));
      if(data.has_more)r.appendChild(button(c().next,'admin-history-'+kind+'-next',function(){
        loadHistory(kind,data.next_cursor,selection);
      }));
    },selection);
  }
  function parseObservedMinor(text) {
    if(text==='')return {
      valid:true,value:null
    };
    if(typeof text!=='string'||!/^(0|-?[1-9][0-9]*)$/.test(text))return {
      valid:false,value:null
    };
    var magnitude=text.charAt(0)==='-'?text.slice(1):text,max='9223372036854775807';
    return {
      valid:magnitude.length<max.length||(magnitude.length===max.length&&magnitude<=max),value:text
    };
  }
  function formatObservedAmount(value,currency) {
    var amount=value==null?t('notRecorded'):parseObservedMinor(value).valid?value:c().error;
    return amount+' / '+t('amount_minor')+' / '+(typeof currency==='string'&&currency?currency:t('notRecorded'));
  }
  function canObserve() {
    return actionAllowed('record_observation')&&s.detail.observation.can_record===true;
  }
  function selectObservationScope(source,history) {
    if(!source||!ids.validId(source.execution_id)||!ids.validId(source.fence)||(source.request_id&&source.request_id!==s.selected)||['current_authority',
    'retained_event',
    'retained_version_required'].indexOf(source.version_provenance)<0)return null;
    var version=history?source.version:source.expected_version;
    if(version!=null&&!integerVersion(version,false))return null;
    return {
      request_id:s.selected,execution_id:source.execution_id,fence:source.fence,bank_account:source.bank_account,prepared_at:source.prepared_at,amount_minor:source.amount_minor,currency:source.currency,expected_version:version==null?null:version,version_provenance:source.version_provenance,selection:s.selection
    };
  }
  function renderObservationButtons() {
    if(!canObserve())return;
    var retained=s.detail.observation.retained_intents;
    if(!retained||!Array.isArray(retained.entries))return;
    var r=region('admin-detail');
    r.appendChild(node('h3',t('retained')));
    retained.entries.forEach(function(row){
      var scope=selectObservationScope(row,false);
      if(!scope)return;
      var b=button(t('record_observation')+' — '+scope.execution_id,null,function(){
        openObservation(scope);
      });
      b.dataset.adminObserve='';
      b.disabled=!!s.unresolved;
      r.appendChild(b);
    });
    if(retained.has_more&&typeof retained.next_cursor==='string')r.appendChild(button(c().next,'admin-retained-next',function(){
      loadHistory('intents',retained.next_cursor,s.selection);
    }));
  }
  function openObservation(scope) {
    if(!canObserve()||s.unresolved||s.operation||scope.selection!==s.selection||scope.request_id!==s.selected)return;
    var f=makeForm(t('record_observation'));
    f.appendChild(node('p',t('observationNotice')));
    var summary=node('section',null,'admin-observation-scope');
    summary.appendChild(node('h3',t('expectedScope')));
    ['request_id',
    'execution_id',
    'fence',
    'prepared_at',
    'bank_account',
    'expected_version'].forEach(function(k){
      pair(summary,t(k==='bank_account'?'originAccount':k),scope[k]);
    });
    pair(summary,t('version_provenance'),t(scope.version_provenance));
    pair(summary,t('amount_minor'),formatObservedAmount(scope.amount_minor,scope.currency));
    f.appendChild(summary);
    var operatorVersion=scope.expected_version==null?field(f,'expected-version',t('operatorVersion'),'text','',true):null;
    if(operatorVersion)operatorVersion.inputMode='numeric';
    var status=field(f,'observed-status',t('status'),'select',null,true);
    [['',
    ''],
    ['paid',
    names()[1]],
    ['failed',
    names()[4]],
    ['unknown',
    names()[5]]].forEach(function(entry){
      var option=node('option',entry[1]);
      option.value=entry[0];
      status.appendChild(option);
    });
    var reason=field(f,'reason',t('reason'),'textarea','',true),reference=field(f,'evidence-reference',t('evidence_reference'),'text','',true),hash=field(f,'evidence-hash',t('evidence_hash'),'text','',true);
    reason.maxLength=4000;
    reference.maxLength=4000;
    hash.maxLength=64;
    var amount=field(f,'observed-amount',t('amount_minor'),'text','');
    amount.inputMode='numeric';
    var currency=field(f,'observed-currency',t('currency'),'text','');
    currency.maxLength=20;
    var settled=field(f,'settled-at',t('settled_at'),'text',''),account=field(f,'bank-account',t('bank_account'),'text',''),bankref=field(f,'bank-reference',t('bank_reference'),'text','');
    account.maxLength=256;
    bankref.maxLength=256;
    var recipient=node('section',null,'admin-recipient-fields'),serial=0;
    f.appendChild(recipient);
    f.appendChild(button(t('addRecipient'),'admin-add-recipient',function(){
      if(s.operation)return;
      var row=node('div');
      var key=field(row,'recipient-key-'+(++serial),t('recipientKey'),'text','',true),value=field(row,'recipient-value-'+serial,t('recipientValue'),'text','',true);
      key.className='admin-recipient-key';
      value.className='admin-recipient-value';
      key.maxLength=64;
      value.maxLength=2000;
      row.appendChild(button(t('remove'),null,function(){
        row.querySelectorAll('input').forEach(function(n){
          n.value='';
        });
        row.remove();
        f.dispatchEvent(new Event('input'));
      }));
      recipient.appendChild(row);
      f.dispatchEvent(new Event('input'));
    }));
    bindReview(f,function(){
      var parsed=parseObservedMinor(amount.value),version=scope.expected_version;
      if(operatorVersion){
        if(!/^[1-9][0-9]*$/.test(operatorVersion.value))throw new Error();
        version=Number(operatorVersion.value);
      }
      if(!integerVersion(version,false)||!parsed.valid||['paid',
      'failed',
      'unknown'].indexOf(status.value)<0||!boundedText(reason.value,4000)||!boundedText(reference.value,4000)||!/^[0-9a-f]{64}$/.test(hash.value)||account.value.length>256||bankref.value.length>256||currency.value.length>20||(settled.value&&!aware(settled.value)))throw new Error();
      var details=Object.create(null);
      recipient.querySelectorAll('.admin-recipient-key').forEach(function(k){
        var v=k.parentElement.querySelector('.admin-recipient-value');
        if(!boundedText(k.value,64)||!boundedText(v.value,2000)||Object.prototype.hasOwnProperty.call(details,k.value))throw new Error();
        details[k.value]=v.value;
      });
      if(Object.keys(details).length>30||new TextEncoder().encode(JSON.stringify(details)).length>20000)throw new Error();
      return {
        request_id:scope.request_id,execution_id:scope.execution_id,fence:scope.fence,expected_version:version,status:status.value,reason:reason.value,evidence_reference:reference.value,evidence_hash:hash.value,bank_account:account.value,bank_reference:bankref.value,amount_minor:parsed.value,currency:currency.value||null,settled_at:settled.value||null,recipient_details:details
      };
    },'/payouts/admin/result','observation',t('record_observation'),function(){
      return canObserve()&&s.selected===scope.request_id&&s.selection===scope.selection;
    });
  }
  function publicationSummary(row,parent) {
    if(!row){
      parent.appendChild(node('p',c().empty));
      return;
    }
    pair(parent,c().requirements,row.version);
    pair(parent,t('effective_from'),row.effective_from);
    pair(parent,t('enabled'),(flagCopy[(window._me||{}).locale]||flagCopy.ru)[row.enabled===true?0:1]);
    ['reason',
    'legal_reference',
    'terms_reference',
    'evidence_reference'].forEach(function(k){
      if(row[k])pair(parent,t(k),row[k]);
    });
    if(row.document){
      pair(parent,t('source_locale'),row.document.source_locale);
      pair(parent,'SHA-256',row.document.sha256);
      parent.appendChild(node('div',row.document.content_text,null,'umc-admin-document'));
    }
  }
  function loadPublications(cursor) {
    return read('requirements','/payouts/read/admin/requirements',pageBody(cursor),function(data){
      checkPage(data);
      var r=region('admin-list');
      r.replaceChildren(node('h2',c().requirements),node('p',c().asof+': '+data.as_of));
      var create=button(t('newPublication'),'admin-publication-new',function(){
        openPublicationDraft(null);
      });
      create.disabled=!canPublish()||!!s.unresolved;
      r.appendChild(create);
      data.entries.forEach(function(row){
        var article=node('details');
        article.appendChild(node('summary',String(row.version)));
        publicationSummary(row,article);
        var draft=button(t('draft'),null,function(){
          openPublicationDraft(row);
        });
        draft.dataset.adminDraft='';
        draft.disabled=!canPublish()||!!s.unresolved;
        article.appendChild(draft);
        r.appendChild(article);
      });
      if(data.has_more)r.appendChild(button(c().next,'admin-publication-next',function(){
        loadPublications(data.next_cursor);
      }));
    });
  }
  function refresh() {
    return read('context','/payouts/read/context',pageBody(null),function(data){
      var caps=data&&data.capabilities;
      if(!data||!ids.validId(data.actor_id)||!data.admin||data.account_status!=='active'||!caps||caps[s.mode==='queue'?'read_admin_queue':'read_admin_requirements']!==true){
        invalidate(c().forbidden);
        return;
      }
      if(s.actor&&s.actor!==data.actor_id){
        invalidate(c().session);
        return;
      }
      s.actor=data.actor_id;
      s.context=data;
      var r=region('admin-context');
      r.replaceChildren(node('p',c().asof+': '+data.as_of));
      if(data.writes_paused)r.appendChild(node('p',c().paused));
      if(s.mode==='requirements'){
        var effective=node('details',null,'admin-effective');
        effective.open=true;
        effective.appendChild(node('summary',t('effective')));
        publicationSummary(data.requirements,effective);
        r.appendChild(effective);
        var latest=node('details',null,'admin-latest');
        latest.open=true;
        latest.appendChild(node('summary',t('latest')));
        publicationSummary(data.latest_publication,latest);
        r.appendChild(latest);
      }
      var reads=[s.mode==='queue'?loadQueue(null):loadPublications(null)];
      if(s.selected)reads.push(loadDetail(s.selected,s.selection));
      return Promise.all(reads);
    });
  }
  function canPublish() {
    return guard()&&s.context&&s.context.capabilities.publish_requirements===true;
  }
  function field(form,name,label,type,value,required) {
    var id='admin-'+name,l=node('label',label);
    l.htmlFor=id;
    form.appendChild(l);
    var n=node(type==='textarea'?'textarea':type==='select'?'select':'input',null,id);
    n.name=name;
    n.autocomplete='off';
    if(n.tagName==='INPUT')n.type=type||'text';
    if(value!=null)n.value=value;
    n.required=!!required;
    n.setAttribute('aria-describedby','admin-error');
    form.appendChild(n);
    return n;
  }
  function makeForm(title) {
    clearForm();
    var f=node('form',null,'admin-private-form');
    f.autocomplete='off';
    f.appendChild(node('h2',title));
    s.form=f;
    region('admin-form').replaceChildren(f);
    var heading=f.querySelector('h2');
    heading.tabIndex=-1;
    heading.focus();
    return f;
  }
  function aware(text) {
    return typeof text==='string'&&/^\d{4}-\d\d-\d\dT\d\d:\d\d(?::\d\d(?:\.\d+)?)?(?:Z|[+-]\d\d:\d\d)$/.test(text)&&!isNaN(Date.parse(text));
  }
  function boundedText(value,max) {
    return typeof value==='string'&&!!value.trim()&&value.length<=max;
  }
  function integerVersion(value,zero) {
    return typeof value==='number'&&Number.isSafeInteger(value)&&value>=(zero?0:1);
  }
  function bindReview(form,build,path,kind,label,permitted,preview) {
    var generation=s.formGeneration,life=s.life,bound=s.bound,selection=s.selection,reviewed=null,confirm=null;
    function owns(){
      return valid(life,bound,selection)&&s.form===form&&generation===s.formGeneration;
    }
    function edit(){
      if(reviewed)wipe(reviewed);
      reviewed=null;
      if(confirm)confirm.remove();
      confirm=null;
      sync();
    }
    formCleanups.set(form,edit);
    form.addEventListener('input',edit);
    form.addEventListener('change',edit);
    form.addEventListener('submit',function(e){
      e.preventDefault();
      review();
    });
    var reviewButton=button(t('review'),'admin-review',review);
    form.appendChild(reviewButton);
    function review(){
      if(!owns()||s.operation||s.unresolved)return;
      if(!permitted()){
        edit();
        message(t('changed'));
        return;
      }
      edit();
      try{
        if(!form.reportValidity())return;
        reviewed=build();
        confirm=node('section',null,'admin-confirmation');
        if(preview)preview(confirm,reviewed);
        else if(reviewed.document&&reviewed.document.content_text)confirm.appendChild(node('div',reviewed.document.content_text,null,'umc-admin-document'));
        ['expected_version',
        'effective_from',
        'request_id',
        'execution_id',
        'fence',
        'status',
        'amount_minor',
        'currency',
        'bank_account',
        'bank_reference',
        'settled_at',
        'reason',
        'evidence_reference',
        'evidence_hash'].forEach(function(k){
          if(reviewed[k]!=null)pair(confirm,t(k),reviewed[k]);
        });
        var send=button(typeof label==='function'?label(reviewed):label,'admin-submit',function(){
          if(!owns()||!reviewed||s.unresolved)return;
          if(!permitted()){
            edit();
            message(t('changed'));
            return;
          }
          var payload=reviewed;
          reviewed=null;
          submit(path,payload,kind,form,generation,selection);
        });
        send.dataset.umcPrimary='40';
        send.disabled=!ids.available();
        if(send.disabled)confirm.appendChild(node('p',secureKeyCopy[(window._me||{}).locale]||secureKeyCopy.ru));
        confirm.appendChild(send);
        form.appendChild(confirm);
        sync();
      }
      catch(_){
        edit();
        message(t('invalid'));
      }
    }
  }
  function reconcile() {
    return refresh().then(function(){
      if(guard()&&s.selected&&s.detail)return Promise.all(['events',
      'intents',
      'outcomes',
      'settlements'].map(function(kind){
        return loadHistory(kind,null,s.selection);
      }));
    }).then(function(){
      if(guard()){
        var old=region('admin-reconciled');
        if(old)old.remove();
        region('admin-receipt').appendChild(node('p',t('readAttempt'),'admin-reconciled'));
      }
    });
  }
  function showUncertain() {
    region('admin-receipt').replaceChildren(node('p',t('unknown'),'admin-uncertain'));
    screen.querySelectorAll('[id^="admin-action-"],[data-admin-observe],[data-admin-history-observe],#admin-publication-new,[data-admin-draft]').forEach(function(n){n.disabled=true;});
    sync();
  }
  function submit(path,payload,kind,form,generation,selection) {
    if(!guard()||s.operation||s.unresolved||s.form!==form||s.formGeneration!==generation)return;
    var key=ids.newKey();
    if(!key){
      message(c().error);
      return;
    }
    payload.operation_key=key;
    var op={
      life:s.life,bound:s.bound,selection:selection,generation:generation,form:form,payload:payload,key:key,kind:kind
    };
    s.operation=op;
    screen.setAttribute('aria-busy','true');
    form.querySelectorAll('button,input,select,textarea').forEach(function(n){
      n.disabled=true;
    });
    sync();
    function owns(){
      return valid(op.life,op.bound,op.selection)&&s.operation===op&&s.form===op.form&&s.formGeneration===op.generation;
    }
    op.bound.request(path,payload).then(function(result){
      if(!owns())return;
      s.operation=null;
      clearForm();
      if(kind==='reveal'){
        var reveal=region('admin-reveal');
        reveal.appendChild(node('p',t('revealNotice')));
        if(!result||typeof result!=='object'||Array.isArray(result))throw new Error();
        Object.keys(result).slice(0,30).forEach(function(k){
          if(typeof result[k]==='string')pair(reveal,k,result[k]);
        });
        reveal.appendChild(button(t('hide'),'admin-hide-reveal',function(){
          clearReveal();
        }));
        wipe(result);
        return;
      }
      var r=region('admin-receipt');
      r.replaceChildren(node('h2',t('receipt')));
      ['request_id',
      'version',
      'state',
      'requirements_id',
      'fence',
      'applied',
      'outcome_id'].forEach(function(k){
        if(result[k]!=null)pair(r,t(k),k==='state'?stateLabel(result[k]):k==='applied'?t(result[k]===true?'appliedYes':'notApplied'):result[k]);
      });
      return reconcile();
    }).catch(function(e){
      if(!valid(op.life,op.bound))return;
      if(authorityFailure(e)){
        failure(e);
        return;
      }
      if(!owns())return;
      s.operation=null;
      clearForm();
      if(e&&(e.status===409||e.status===422)){
        message(t('changed'));
        return reconcile();
      }
      s.unresolved={
        key:op.key,kind:op.kind,request_id:s.selected
      };
      showUncertain();
      return reconcile();
    }).finally(function(){
      form.querySelectorAll('input,textarea,select').forEach(function(n){
        n.value='';
      });
      wipe(payload);
      op.key=null;
      if(valid(op.life,op.bound)&&s.operation===op)s.operation=null;
      if(valid(op.life,op.bound)&&s.formGeneration===op.generation){
        screen.setAttribute('aria-busy','false');
        sync();
      }
    });
  }
  function openPublicationDraft(source) {
    if(!canPublish()||s.unresolved||s.operation)return;
    var latest=s.context.latest_publication,version=latest?latest.version:0;
    if(!integerVersion(version,true))return;
    var f=makeForm(t('newPublication')),enabled=field(f,'enabled',t('enabled'),'checkbox');
    enabled.checked=source?source.enabled===true:false;
    var effective=field(f,'effective-from',t('effective_from'),'text','',true);
    var reason=field(f,'reason',t('reason'),'textarea',source&&source.reason||'',true);
    var refs={
    };
    ['legal',
    'terms',
    'evidence'].forEach(function(k){
      refs[k]=field(f,k+'-reference',t(k+'_reference'),'text',source&&source[k+'_reference']||'',true);
      refs[k].maxLength=4000;
    });
    reason.maxLength=4000;
    var required=field(f,'required-fields',t('required_fields'),'textarea',(source&&source.required_fields||['recipient_name',
    'bank_account',
    'legal_status']).join('\n'),true);
    var mode=field(f,'document-mode',t('documentMode'),'select');
    [['new',
    t('newDocument')],
    ['reuse',
    t('reuse')],
    ['none',
    t('none')]].forEach(function(entry){
      var option=node('option',entry[1]);
      option.value=entry[0];
      if(entry[0]==='reuse'&&!(source&&source.document&&ids.validId(source.document.document_id)))option.disabled=true;
      mode.appendChild(option);
    });
    mode.value=source&&source.document?'reuse':'new';
    var text=field(f,'document-text',t('document'),'textarea','');
    var locale=field(f,'source-locale',t('source_locale'),'text',source&&source.document?source.document.source_locale:'');
    var defs=field(f,'field-definitions',t('definitions'),'textarea',source&&source.field_definitions?JSON.stringify(source.field_definitions,null,2):'');
    function visibility(){
      text.hidden=mode.value!=='new';
      text.previousElementSibling.hidden=text.hidden;
      locale.hidden=mode.value==='none';
      locale.previousElementSibling.hidden=locale.hidden;
      defs.hidden=mode.value==='none';
      defs.previousElementSibling.hidden=defs.hidden;
    }
    mode.addEventListener('change',visibility);
    visibility();
    bindReview(f,function(){
      var keys=required.value.split('\n'),payload={
        expected_version:version,effective_from:effective.value,reason:reason.value,legal_reference:refs.legal.value,terms_reference:refs.terms.value,evidence_reference:refs.evidence.value,required_fields:keys,enabled:enabled.checked
      };
      if(!aware(effective.value)||!boundedText(reason.value,4000)||Object.keys(refs).some(function(k){
        return !boundedText(refs[k].value,4000);
      })||keys.length>30||new Set(keys).size!==keys.length||keys.some(function(k){
        return !/^[a-z][a-z0-9_]{0,63}$/.test(k);
      })||['recipient_name',
      'bank_account',
      'legal_status'].some(function(k){
        return keys.indexOf(k)<0;
      }))throw new Error();
      if(mode.value==='none'){
        if(enabled.checked)throw new Error();
        return payload;
      }
      var documentLocale;
      if(mode.value==='reuse'){
        payload.document={
          document_id:source.document.document_id
        };
        documentLocale=source.document.source_locale;
      }
      else{
        if(!boundedText(text.value,1000000)||new TextEncoder().encode(text.value).length>1000000||!validLocale(locale.value))throw new Error();
        payload.document={
          content_text:text.value,source_locale:locale.value
        };
        documentLocale=locale.value;
      }
      var definitions=JSON.parse(defs.value);
      validateDefinitions(definitions,keys,documentLocale);
      payload.field_definitions=definitions;
      return payload;
    },'/payouts/admin/requirements/publish','publication',function(p){
      return t(p.enabled?'publish':'suspend');
    },canPublish,function(parent,payload){
      if(payload.document){
        var doc=payload.document.content_text!=null?payload.document:source.document;
        pair(parent,t('source_locale'),doc.source_locale);
        if(doc.sha256)pair(parent,'SHA-256',doc.sha256);
        parent.appendChild(node('div',doc.content_text,null,'umc-admin-document'));
      }
      if(payload.field_definitions){
        parent.appendChild(node('h3',t('definitions')));
        payload.field_definitions.forEach(function(definition){
          var item=node('section');
          pair(item,t('required_fields'),definition.key);
          ['labels',
          'help'].forEach(function(name){
            Object.keys(definition[name]||{
            }).forEach(function(locale){
              pair(item,locale,definition[name][locale]);
            });
          });
          if(definition.allowed_values)definition.allowed_values.forEach(function(value){
            item.appendChild(node('p',value));
          });
          parent.appendChild(item);
        });
      }
    });
  }
  function validLocale(value) {
    return typeof value==='string'&&/^[A-Za-z][A-Za-z0-9-]{1,34}$/.test(value);
  }
  function validateDefinitions(defs,keys,locale) {
    if(!Array.isArray(defs)||defs.length!==keys.length)throw new Error();
    var found=new Set();
    defs.forEach(function(d){
      if(!d||typeof d!=='object'||Object.keys(d).some(function(k){
        return ['key',
        'labels',
        'help',
        'allowed_values'].indexOf(k)<0;
      })||keys.indexOf(d.key)<0||found.has(d.key))throw new Error();
      found.add(d.key);
      [d.labels,
      d.help||{
      }
      ].forEach(function(map){
        if(!map||typeof map!=='object'||Array.isArray(map)||Object.keys(map).some(function(k){
          return !validLocale(k)||!boundedText(map[k],2000);
        }))throw new Error();
      });
      if(!d.labels||!boundedText(d.labels[locale],2000))throw new Error();
      if(d.allowed_values!=null&&(!Array.isArray(d.allowed_values)||!d.allowed_values.length||new Set(d.allowed_values).size!==d.allowed_values.length||d.allowed_values.some(function(v){
        return !boundedText(v,2000);
      })))throw new Error();
    });
  }
  function mount() {
    screen.replaceChildren();
    var heading=node('h1',c().title,'admin-title');
    heading.tabIndex=-1;
    screen.appendChild(heading);
    var error=node('p','','admin-error','error');
    error.tabIndex=-1;
    error.setAttribute('role','alert');
    screen.appendChild(error);
    var live=node('p','','admin-live','hint');
    live.setAttribute('role','status');
    live.setAttribute('aria-live','polite');
    screen.appendChild(live);
    ['admin-context',
    'admin-list',
    'admin-detail',
    'admin-history',
    'admin-form',
    'admin-reveal',
    'admin-receipt'].forEach(function(id){
      screen.appendChild(node('section',null,id,'umc-admin-region'));
    });
    screen.appendChild(button(c().refresh,'admin-refresh',refresh));
    var back=button(c().back,'admin-back',function(){
      if(s.form){
        var abandoned=!!s.operation;
        clearForm();
        if(abandoned&&guard()){
          showUncertain();
          reconcile();
        }
        return;
      }
      invalidate();
      if(window.UMCPayouts)window.UMCPayouts.resumeFromAdmin();
    });
    back.dataset.umcBack='';
    screen.appendChild(back);
    heading.focus();
    sync();
  }
  function open(mode) {
    if(mode!=='queue'&&mode!=='requirements')return;
    invalidate();
    s.mode=mode;
    s.bound=bridge.createRequestContext();
    bridge.showScreen(screen.id);
    mount();
    refresh();
  }
  document.addEventListener('umc:screen-change',function(e){
    if(e.detail&&e.detail.screen!==screen.id&&s.bound)invalidate();
  });
  window.addEventListener('pagehide',function(){
    invalidate();
  });
  window.addEventListener('focus',function(){
    if(s.bound&&!s.bound.isCurrent())invalidate(c().session);
  });
  document.addEventListener('visibilitychange',function(){
    if(document.hidden)clearForm();
    if(s.bound&&!s.bound.isCurrent())invalidate(c().session);
  });
  window.UMCPayoutAdmin=Object.freeze({
    open:open
  });
})();

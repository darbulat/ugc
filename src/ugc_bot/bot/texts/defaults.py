"""Default localized bot texts (key -> value per locale).

Used as fallback when bot_texts table has no row for (key, locale).
All bot messages and button labels must have keys here and in DB.
"""

# ru: Russian (current production)
# en: English (for global market)
DEFAULT_TEXTS: dict[str, dict[str, str]] = {
    "ru": {
        # Start & support
        "start_message": (
            "UMC — сервис для UGC.\n"
            "Бизнесу — подбор креаторов, креаторам — заказы."
        ),
        "support_response": (
            "Служба поддержки: @usemycontent\nОбращайтесь по любым вопросам!"
        ),
        "receipt_description": "Услуги платформы Use My Content",
        # Role selection buttons
        "btn_creator": "Я креатор",
        "btn_advertiser": "Мне нужны UGC‑креаторы",
        # Common buttons
        "btn_support": "💬 Поддержка",
        "btn_my_orders": "📂 Мои заказы",
        "btn_change_role": "Смена роли",
        "btn_create_profile": "Создать профиль",
        "btn_advertiser_start": "Начать",
        "btn_create_order": "➕ Создать заказ",
        "btn_confirm_instagram": "✅ Подтвердить Instagram",
        "btn_confirm_agreement": "✅ Подтвердить согласие",
        "btn_edit_profile": "Редактировать профиль",
        "btn_my_profile": "👤 Мой профиль",
        "btn_work_format_ads": "📢 Размещать рекламу у себя в аккаунте",
        "btn_work_format_ugc_only": "❌ Только UGC (без размещения)",
        "btn_phone_request": "📱 Поделиться номером телефона",
        "btn_city_picker": "Выбрать город",
        "btn_edit_profile_blogger": "Редактировать профиль блогера",
        "btn_edit_profile_advertiser": "Редактировать профиль рекламодателя",
        "btn_audience_f": "👩 В основном женщины",
        "btn_audience_m": "👨 В основном мужчины",
        "btn_audience_a": "👥 Примерно поровну",
        "btn_gender_m": "Мужской",
        "btn_gender_f": "Женский",
        "btn_age_0_17": "до 18",
        "btn_age_18_24": "18–24",
        "btn_age_25_34": "25–34",
        "btn_age_35_44": "35–44",
        "btn_age_45_99": "45+",
        "btn_barter_yes": "Да",
        "btn_barter_no": "Нет",
        "btn_payout": "Выплатить",
        "btn_back": "Назад",
        "btn_forward": "Вперёд",
        "btn_back_arrow": "⬅️ Назад",
        "btn_forward_arrow": "Вперед ➡️",
        "btn_pay_order": "💳 Оплатить №{creation_number}",
        "btn_open_profile": "🔗 Открыть профиль",
        "btn_write_telegram": "Написать в телеграм",
        "btn_ok_skipped": "Ок, пропущено.",
        # Order creation
        "order_type_ugc_only": "🎥 UGC-видео для бренда",
        "order_type_ugc_placement": "📢 UGC + размещение у креатора",
        "order_photo_add": "📷 Добавить фото",
        "order_photo_skip": "⏭ Пропустить",
        "coop_barter": "🎁 Бартер",
        "coop_payment": "💰 Оплата",
        "coop_both": "🔄 Бартер + оплата",
        "content_social": "📱 В соцсетях бренда",
        "content_ads": "📢 В рекламе (таргет, объявления)",
        "content_both": "🔄 В соцсетях и рекламе",
        "deadlines_3": "⏱ До 3 дней",
        "deadlines_7": "⏱ До 7 дней",
        "deadlines_14": "⏱ До 14 дней",
        # Messages: user/role
        "msg_user_not_found": "Пользователь не найден.",
        "msg_choose_role": "Выберите роль через /role.",
        "msg_fill_profile_orders": (
            "Заполните профиль (/advertiser или /creator), чтобы видеть заказы."
        ),
        "msg_confirm_agreement": (
            "Пожалуйста, подтвердите согласие с документами платформы."
        ),
        "msg_no_orders": "У вас пока нет заказов. /create_order",
        "msg_no_blogger_orders": (
            "Вы пока не откликались. Предложения приходят в бот."
        ),
        "msg_blogger_profile_empty": "Профиль блогера не заполнен.",
        "msg_advertiser_profile_empty": "Профиль рекламодателя не заполнен.",
        "msg_advertiser_profile_fill": (
            "Профиль рекламодателя не заполнен. Команда: /advertiser"
        ),
        "msg_creator_profile_fill": "Профиль не заполнен. Команда: /creator",
        "msg_confirm_instagram_first": "Подтвердите Instagram перед откликом.",
        "msg_confirm_agreement_first": "Сначала подтвердите согласие.",
        # Messages: payments
        "msg_invalid_order_amount": "Некорректная сумма заказа.",
        "msg_order_amount_too_large": (
            "Сумма заказа слишком большая для выставления счета в Telegram."
        ),
        "msg_invoice_failed": "Не удалось создать счет. Попробуйте позже.",
        "msg_pay_order_usage": "Использование: /pay_order <order_id>",
        "msg_invalid_order_id": "Неверный формат order_id.",
        "msg_invalid_order_format": "Неверный формат заказа.",
        "msg_order_not_found": "Заказ не найден.",
        "msg_order_not_yours": "Заказ не принадлежит рекламодателю.",
        "msg_order_not_new": "Заказ не в статусе NEW.",
        "msg_pricing_not_configured": (
            "Стоимость доступа не настроена. Свяжитесь с поддержкой."
        ),
        "msg_payment_provider_not_configured": (
            "Платежный провайдер не настроен."
        ),
        "msg_order_undetermined": "Не удалось определить заказ.",
        "msg_title_payment": "Оплата заказа",
        # Messages: referral
        "msg_referral_payout_today": "Вы уже подавали заявку на вывод сегодня.",
        "msg_referral_payout_unavailable": (
            "Выплата недоступна: нет баланса или уже есть заявка."
        ),
        "msg_referral_payout_sent": "Запрос на выплату отправлен в поддержку.",
        "msg_referral_payout_notify_failed": (
            "Заявка создана, но не удалось уведомить поддержку. "
            "Обратитесь в поддержку вручную."
        ),
        "msg_referral_no_users": "У вас пока нет приведённых пользователей.",
        "msg_referral_access_denied": "Доступ запрещён.",
        "msg_referral_list_title": (
            "Ваши рефералы (страница {page}/{total_pages}):"
        ),
        "msg_referral_list_empty": "Ваши рефералы: пока никого.",
        "msg_referral_pending_block": (
            "Не заполнили профиль креатора (напоминайте заполнить):"
        ),
        "msg_referral_no_pending": "Нет рефералов без профиля.",
        # Messages: orders list
        "msg_orders_title": "Ваши заказы (страница {page}/{total_pages}):",
        "msg_orders_blogger_title": (
            "Заказы, на которые вы откликнулись (страница {page}/{total_pages}):"
        ),
        "msg_order_status": "Статус: {status_label}",
        "msg_order_creators": "Креаторов: {bloggers_needed}",
        "msg_order_matched": "Подобрано: {matched_count} / {bloggers_needed}",
        "msg_order_date_created": "Дата создания: {date}",
        "msg_order_date_completed": "Дата завершения: {date}",
        "msg_order_link": "Ссылка на проект: {link}",
        "msg_order_type_ugc": "UGC-видео для бренда",
        "msg_order_type_placement": "UGC + размещение",
        "msg_order_price": "Стоимость 1 UGC: {price}",
        "msg_order_barter": "Бартер: {desc}",
        "msg_status_new": "Создан",
        "msg_status_pending_moderation": "На модерации",
        "msg_status_active": "Активен",
        "msg_status_closed": "Завершён",
        # Messages: blogger registration / profile
        "msg_choose_city": "Выберите город из списка.",
        "msg_choose_city_or_type": (
            "Укажите ближайший крупный город или нажмите «Выбрать город»"
        ),
        "msg_city_multiple_regions": (
            "Этот город есть в нескольких регионах. Выберите регион:"
        ),
        "msg_session_expired": "Сессия истекла. Начните заново.",
        "msg_session_expired_orders": "Сессия истекла. Начните заново с «Создать заказ».",
        "msg_session_expired_profile": "Сессия истекла. Откройте «Мой профиль» снова.",
        "msg_profile_not_found": "Профиль не найден.",
        "msg_profile_not_found_role": "Профиль не найден. Выберите роль через /role.",
        "msg_profile_incomplete": "Профиль не заполнен.",
        "msg_choose_profile_edit": "Выберите профиль для редактирования:",
        "msg_choose_section_edit": "Выберите раздел для редактирования:",
        "msg_profile_updated": "Профиль обновлён.",
        # Messages: advertiser registration
        "msg_whats_your_name": "Как вас зовут?",
        "msg_choose_action": "Выберите действие:",
        "msg_what_city": "Из какого вы города?\nПример: Казань / Москва / Санкт‑Петербург",
        "msg_brand_name": "Название вашего бренда / компании / бизнеса:",
        "msg_company_activity": "Чем занимается ваша компания?",
        "msg_brand_link": "Ссылка на сайт, продукт или соцсети бренда:",
        "msg_after_registration": (
            "Теперь вы можете разместить заказ и найти UGC-креаторов."
        ),
        "msg_advertiser_intro": (
            "Вы выбрали роль «Мне нужны UGC‑креаторы».\n"
            "Давайте создадим профиль, чтобы вы могли размещать заказы."
        ),
        "msg_creator_intro": (
            "Ты — UGC‑креатор. Заказчики уже ищут креаторов здесь — полный профиль "
            "помогает попасть в подбор и получать подходящие заказы.\n\n"
            "Заполним профиль за пару минут — и ты в подборе."
        ),
        # Creator registration: step prompts (with step N of 12)
        "msg_step_ask_name": "Как вас зовут?\n\nШаг 1 из 12",
        "msg_step_ask_instagram": "Пришлите ссылку в формате instagram.com/name\n\nШаг 2 из 12",
        "msg_step_ask_instagram_first": "Пришлите ссылку в формате instagram.com/name\n\nШаг 1 из 12",
        "msg_step_ask_city": (
            "Заказчики подбирают креаторов по городу: для доставки продукта и для "
            "офлайн взаимодействия. Из какого вы города?\n\nШаг 3 из 12"
        ),
        "msg_step_ask_birth_date": (
            "Укажите дату рождения в формате ДД.ММ.ГГГГ (например 15.05.1995):\n\nШаг 4 из 12"
        ),
        "msg_step_ask_gender": "Укажите ваш пол:\n\nШаг 5 из 12",
        "msg_step_ask_topics": (
            "О чём ваш контент?\n"
            "Напишите 1–5 тематики через запятую: бизнес, инвестиции, фитнес, "
            "питание, бьюти, уход за кожей, путешествия, еда, рестораны, мода, "
            "стиль, дети, семья, технологии, гаджеты, лайфстайл, мероприятия, другое\n\nШаг 6 из 12"
        ),
        "msg_step_ask_audience_gender": (
            "Кто в основном смотрит ваш контент? "
            "По наблюдениям или статистике\n\nШаг 7 из 12"
        ),
        "msg_step_ask_audience_age": "Основной возраст вашей аудитории?\n\nШаг 8 из 12",
        "msg_step_ask_audience_geo": (
            "В каких городах в основном аудитория? До 3 городов через запятую, "
            "например: Москва, Казань, Санкт‑Петербург\n\nШаг 9 из 12"
        ),
        "msg_step_ask_price": (
            "Заказчики отбирают креаторов по бюджету — указанная цена ускоряет сделку. "
            "Сколько стоит одно UGC‑видео? Цена в рублях, например: 500, 1000, 2000\n\nШаг 10 из 12"
        ),
        "msg_step_ask_barter": (
            "Много заказов с бартером — ответ «Да» увеличит число офферов. "
            "Готов иногда работать с брендами по бартеру?\n\nШаг 11 из 12"
        ),
        "msg_step_ask_work_format": (
            "Помимо UGC, как ещё готов работать с брендами? "
            "Последний шаг перед подбором.\n\nШаг 12 из 12"
        ),
        "msg_agreements_intro_creator": (
            "Почти готово. "
            "Пожалуйста, ознакомьтесь с документами и подтвердите согласие."
        ),
        "msg_profile_created": (
            "Профиль создан 👍\n\n"
            "Заказчики уже ищут креаторов — заполненный профиль повышает шансы "
            "получить оффер.\n\n"
            "Остался последний шаг — подтвердить Instagram‑аккаунт. Это нужно, чтобы:\n"
            "— защитить бренды от фейков\n"
            "— повысить доверие к твоему профилю\n"
            "— быстрее получать заказы"
        ),
        "msg_instagram_already_registered": (
            "Этот Instagram аккаунт уже зарегистрирован. "
            "Пожалуйста, используйте другой аккаунт или обратитесь в поддержку."
        ),
        "msg_work_format_choose": (
            "Выберите одну из кнопок: Размещать рекламу у себя в аккаунте "
            "или Только UGC (без размещения)."
        ),
        "msg_registration_aborted": (
            "Регистрация прервана. Чтобы завершить, откройте «Мой профиль» "
            "и подтвердите согласие."
        ),
        # Creator registration: validation errors
        "err_instagram_empty": (
            "Ссылка не может быть пустой. Пришли ссылку в формате instagram.com/name"
        ),
        "err_instagram_format": "Неверный формат. Нужна ссылка вида instagram.com/name",
        "err_instagram_example": (
            "Неверный формат ссылки Instagram. Пример: https://instagram.com/name"
        ),
        "err_gender_choose": "Выберите одну из кнопок: Мужской или Женский.",
        "err_audience_choose": (
            "Выберите: В основном женщины, мужчины или Примерно поровну."
        ),
        "err_age_choose": "Выберите одну из кнопок возраста.",
        "err_barter_choose": "Выберите Да или Нет.",
        "err_price_number": "Введите число, например 500, 1000, 2000.",
        "err_geo_max_cities": "Укажите не более 3 городов через запятую.",
        # Messages: order creation
        "msg_what_do_you_need": "Что вам нужно?",
        "msg_choose_from_keyboard": "Выберите один из вариантов на клавиатуре.",
        "msg_coop_format": "Какой формат сотрудничества вам подходит?",
        "msg_enter_number": "Введите число, например 1500.",
        "msg_how_many_creators": "Сколько креаторов вам нужно?",
        "msg_product_link": "Введите ссылку на продукт (для откликнувшихся креаторов):",
        "msg_choose_count": "Выберите одно из значений: {counts}.",
        "msg_where_use_ugc": "Где вы планируете использовать UGC-видео?",
        "msg_send_photo": "Отправьте фото продукта:",
        # Messages: Instagram
        "msg_profile_empty_creator": (
            "Профиль не заполнен. «Создать профиль» или /creator"
        ),
        "msg_instagram_already_confirmed": "Ваш Instagram‑аккаунт уже подтвержден",
        # Messages: complaints
        "msg_invalid_format": "Неверный формат.",
        "msg_invalid_id_format": "Неверный формат идентификатора.",
        "msg_order_not_found_short": "Заказ не найден.",
        "msg_no_bloggers_complain": "Нет блогеров для жалобы.",
        "msg_complain_on": "Пожаловаться на {blogger_name}",
        "msg_choose_blogger_complain": (
            "Выберите блогера, на которого хотите пожаловаться:"
        ),
        "msg_no_access_order": "У вас нет доступа к этому заказу.",
        "msg_choose_complaint_reason": "Выберите причину жалобы:",
        "msg_complaint_no_bloggers": "Нет блогеров для жалобы.",
        "msg_invalid_user_id": "Неверный идентификатор пользователя.",
        "msg_invalid_reason": "Неверная причина.",
        "msg_data_error": "Ошибка обработки данных.",
        "msg_describe_complaint": "Опишите причину жалобы:",
        "msg_error_try_later": "Произошла ошибка. Попробуйте позже.",
        "msg_enter_complaint_reason": "Пожалуйста, введите причину жалобы.",
        # Messages: offer responses
        "msg_order_closed": "Заказ уже закрыт.",
        "msg_order_closed_full": (
            "❗ Заказ уже закрыт\n\n"
            "Спасибо за отклик — все креаторы по этому заказу уже подобраны.\n\n"
            "Мы обязательно пришлём новые заказы, как только они появятся.\n\n"
            "Следите за уведомлениями в боте 🙌"
        ),
        "msg_blogger_after_response_what_next": (
            "⏳ Что дальше\n\n"
            "💬 Ожидайте сообщение от заказчика — он получил ссылку на Instagram "
            "и напишет первым\n"
            "📩 Проверьте запросы в Direct\n"
            "👀 Для демонстрации используйте превью с водяным знаком\n"
            "💸 Получите оплату после согласования превью\n"
            "🎥 Финальный UGC-ролик отправляйте только после оплаты\n"
            "❗ Если заказчик не меняет условия оффера, отказ после отклика\n"
            " может привести к ограничению аккаунта\n"
            "🤝 Платформа не участвует в переговорах и оплате."
        ),
        "msg_offer_accepted": "Отклик принят! Ожидайте связи от рекламодателя.",
        "msg_offer_order_filled": (
            "Заказ уже укомплектован. Мы сохранили ваш отклик — "
            "если кто-то откажется, с вами могут связаться."
        ),
        "msg_advertiser_after_payment_success": (
            "Оплата прошла успешно ✅\n\nПодбор креаторов по вашему заказу активирован."
        ),
        "msg_advertiser_after_payment_what_next": (
            "🔄 **Что дальше**\n\n"
            "📩 Креаторы получают ваш оффер\n"
            "🔗 Вы будете получать отклики со ссылками на их профили\n"
            "💬 Вы самостоятельно связываетесь с выбранными креаторами"
        ),
        "msg_advertiser_after_payment_important": (
            "⚠️ **Важно**\n\n"
            "🧷 Условия оффера не рекомендуется изменять после публикации\n"
            "🔄 Если условия меняются, креатор может отказаться от сотрудничества\n"
            "🤝 Платформа не является стороной сделки\n"
            "💸 Оплата креаторам производится вами напрямую\n"
            "👀 Оплачивайте после просмотра превью с водяным знаком\n"
            "🚫 Платформа не несёт ответственности за креаторов"
        ),
        "msg_phone_request": (
            "Укажите номер телефона для связи по заказу.\n"
            "Нажмите кнопку ниже или введите номер вручную "
            "(пример: 89001110777)."
        ),
        "msg_instagram_confirmed": (
            "Instagram подтверждён ✅. Бренды могут отправлять предложения."
        ),
        "msg_instagram_mismatch": (
            "Указанный в профиле Instagram не совпадает с аккаунтом, "
            "с которого вы отправили код. Откройте «Мой профиль», "
            "отредактируйте профиль блогера и укажите корректный Instagram."
        ),
        "msg_too_many_requests": "Слишком много запросов. Попробуйте позже.",
        "msg_invalid_order_id_short": "Неверный идентификатор заказа.",
        # Messages: admin / moderation
        "msg_order_activated": "Заказ активирован, уходит блогерам.",
        # Error middleware (user-facing)
        "err_user_not_found": "Пользователь не найден.",
        "err_blogger_registration": "Ошибка регистрации блогера.",
        "err_advertiser_registration": "Ошибка регистрации рекламодателя.",
        "err_order_not_found": "Заказ не найден.",
        "err_order_not_active": "Заказ не активен.",
        "err_order_creation": "Ошибка создания заказа.",
        "err_order_already_responded": "Вы уже откликались на заказ.",
        "err_order_response_limit": "Лимит откликов по заказу достигнут.",
        "err_order_not_new": "Заказ не в статусе NEW.",
        "err_order_not_yours": "Заказ не принадлежит рекламодателю.",
        "err_interaction_not_found": "Взаимодействие не найдено.",
        "err_interaction": "Ошибка взаимодействия.",
        "err_interaction_status": "Взаимодействие не в ISSUE.",
        "err_interaction_resolution": "Некорректный статус для ручного разрешения.",
        "err_complaint_exists": "Вы уже подали жалобу по этому заказу.",
        "err_complaint_not_found": "Жалоба не найдена.",
        "err_price_exceeds": "Сумма превышает максимум ({amount} {currency}).",
        "err_generic": "Произошла ошибка: {error}",
        # Feedback
        "msg_feedback_thanks": "Спасибо, ответ сохранен.",
        "msg_feedback_thanks_short": "Спасибо за обратную связь.",
        "msg_interaction_not_found": "Взаимодействие не найдено.",
        "msg_insufficient_rights": "Недостаточно прав.",
        "msg_feedback_thanks_ok": "Спасибо.",
        "msg_describe_problem": (
            "Опишите проблему и приложите скриншоты переписки или "
            "другие подтверждения. Это поможет разобраться.\n"
        ),
        "msg_postpone_max": (
            "Достигнут максимум переносов. "
            "Статус зафиксирован как 'Не договорились'."
        ),
        "msg_postpone_72": "Проверка перенесена на 72 ч. Переносов: {cnt}/{max}",
        "msg_session_expired_feedback": (
            "Сессия истекла. Ответьте на вопрос обратной связи снова."
        ),
        "msg_error_try_again": "Ошибка. Попробуйте снова.",
        "msg_add_description_or_photo": (
            "Добавьте описание или фото, затем нажмите «Отправить»."
        ),
        "msg_add_description_before_send": "Добавьте описание или фото перед отправкой.",
        "msg_complaint_error": (
            "Произошла ошибка при создании заявки. Попробуйте снова "
            "или обратитесь в поддержку через меню."
        ),
        "msg_complaint_received": (
            "Мы приняли вашу заявку. Поддержка разберётся в ситуации. "
            "При необходимости нажмите «Поддержка» в меню."
        ),
        "msg_enter_reason": "Напишите, пожалуйста, причину:",
        "msg_enter_reason_text": "Введите причину текстом.",
        "msg_nps_thanks": "Спасибо за оценку!",
        "msg_nps_question": "Оцените, насколько вы готовы рекомендовать нас? (1–5)",
        "msg_nps_thank": "Спасибо! Ваш отзыв очень важен для нас.",
        "msg_invalid_format_short": "Неверный формат.",
        "msg_invalid_id": "Неверный идентификатор.",
        "msg_score_1_to_5": "Оценка должна быть от 1 до 5.",
        "msg_invalid_status": "Неверный статус.",
        "msg_invalid_response": "Неверный формат ответа.",
        "msg_error_later": "Произошла ошибка. Попробуйте позже.",
        # Admin message to user
        "msg_cancelled": "Отменено.",
        "msg_invalid_uuid": "Неверный идентификатор пользователя.",
        "msg_user_not_telegram": "Пользователь не в Telegram.",
    },
    "en": {
        "start_message": (
            "UMC — UGC service.\n"
            "For business — creator matching; for creators — orders."
        ),
        "support_response": (
            "Support: @usemycontent\nContact us for any questions!"
        ),
        "receipt_description": "Use My Content platform services",
        "btn_creator": "I'm a creator",
        "btn_advertiser": "I need UGC creators",
        "btn_support": "💬 Support",
        "btn_my_orders": "📂 My orders",
        "btn_change_role": "Change role",
        "btn_create_profile": "Create profile",
        "btn_advertiser_start": "Start",
        "btn_create_order": "➕ Create order",
        "btn_confirm_instagram": "✅ Confirm Instagram",
        "btn_confirm_agreement": "✅ Confirm agreement",
        "btn_edit_profile": "Edit profile",
        "btn_my_profile": "👤 My profile",
        "btn_work_format_ads": "📢 Place ads in my account",
        "btn_work_format_ugc_only": "❌ UGC only (no placement)",
        "btn_phone_request": "📱 Share phone number",
        "btn_city_picker": "Choose city",
        "btn_edit_profile_blogger": "Edit blogger profile",
        "btn_edit_profile_advertiser": "Edit advertiser profile",
        "btn_audience_f": "👩 Mostly women",
        "btn_audience_m": "👨 Mostly men",
        "btn_audience_a": "👥 Mixed",
        "btn_gender_m": "Male",
        "btn_gender_f": "Female",
        "btn_age_0_17": "under 18",
        "btn_age_18_24": "18–24",
        "btn_age_25_34": "25–34",
        "btn_age_35_44": "35–44",
        "btn_age_45_99": "45+",
        "btn_barter_yes": "Yes",
        "btn_barter_no": "No",
        "btn_payout": "Payout",
        "btn_back": "Back",
        "btn_forward": "Forward",
        "btn_back_arrow": "⬅️ Back",
        "btn_forward_arrow": "Forward ➡️",
        "btn_pay_order": "💳 Pay #{creation_number}",
        "btn_open_profile": "🔗 Open profile",
        "btn_write_telegram": "Message in Telegram",
        "btn_ok_skipped": "OK, skipped.",
        "order_type_ugc_only": "🎥 UGC video for brand",
        "order_type_ugc_placement": "📢 UGC + placement",
        "order_photo_add": "📷 Add photo",
        "order_photo_skip": "⏭ Skip",
        "coop_barter": "🎁 Barter",
        "coop_payment": "💰 Payment",
        "coop_both": "🔄 Barter + payment",
        "content_social": "📱 Brand socials",
        "content_ads": "📢 Ads (targeting, banners)",
        "content_both": "🔄 Socials and ads",
        "deadlines_3": "⏱ Up to 3 days",
        "deadlines_7": "⏱ Up to 7 days",
        "deadlines_14": "⏱ Up to 14 days",
        "msg_user_not_found": "User not found.",
        "msg_choose_role": "Choose role via /role.",
        "msg_fill_profile_orders": (
            "Fill your profile (/advertiser or /creator) to see orders."
        ),
        "msg_confirm_agreement": "Please confirm agreement with platform documents.",
        "msg_no_orders": "You have no orders yet. /create_order",
        "msg_no_blogger_orders": "You haven't responded yet. Offers come to the bot.",
        "msg_blogger_profile_empty": "Blogger profile not filled.",
        "msg_advertiser_profile_empty": "Advertiser profile not filled.",
        "msg_advertiser_profile_fill": "Advertiser profile not filled. Command: /advertiser",
        "msg_creator_profile_fill": "Profile not filled. Command: /creator",
        "msg_confirm_instagram_first": "Confirm Instagram before responding.",
        "msg_confirm_agreement_first": "Confirm agreement first.",
        "msg_invalid_order_amount": "Invalid order amount.",
        "msg_order_amount_too_large": "Order amount too large for Telegram invoice.",
        "msg_invoice_failed": "Failed to create invoice. Try again later.",
        "msg_pay_order_usage": "Usage: /pay_order <order_id>",
        "msg_invalid_order_id": "Invalid order_id format.",
        "msg_invalid_order_format": "Invalid order format.",
        "msg_order_not_found": "Order not found.",
        "msg_order_not_yours": "Order does not belong to advertiser.",
        "msg_order_not_new": "Order is not in NEW status.",
        "msg_pricing_not_configured": "Pricing not configured. Contact support.",
        "msg_payment_provider_not_configured": "Payment provider not configured.",
        "msg_order_undetermined": "Could not determine order.",
        "msg_title_payment": "Order payment",
        "msg_referral_payout_today": "You already requested payout today.",
        "msg_referral_payout_unavailable": "Payout unavailable: no balance or request pending.",
        "msg_referral_payout_sent": "Payout request sent to support.",
        "msg_referral_payout_notify_failed": (
            "Request created but could not notify support. Contact support manually."
        ),
        "msg_referral_no_users": "You have no referred users yet.",
        "msg_referral_access_denied": "Access denied.",
        "msg_referral_list_title": "Your referrals (page {page}/{total_pages}):",
        "msg_referral_list_empty": "Your referrals: none yet.",
        "msg_referral_pending_block": "Haven't filled creator profile (remind them):",
        "msg_referral_no_pending": "No referrals without profile.",
        "msg_orders_title": "Your orders (page {page}/{total_pages}):",
        "msg_orders_blogger_title": "Orders you responded to (page {page}/{total_pages}):",
        "msg_order_status": "Status: {status_label}",
        "msg_order_creators": "Creators: {bloggers_needed}",
        "msg_order_matched": "Matched: {matched_count} / {bloggers_needed}",
        "msg_order_date_created": "Created: {date}",
        "msg_order_date_completed": "Completed: {date}",
        "msg_order_link": "Project link: {link}",
        "msg_order_type_ugc": "UGC video for brand",
        "msg_order_type_placement": "UGC + placement",
        "msg_order_price": "Price per UGC: {price}",
        "msg_order_barter": "Barter: {desc}",
        "msg_status_new": "Created",
        "msg_status_pending_moderation": "Pending moderation",
        "msg_status_active": "Active",
        "msg_status_closed": "Closed",
        "msg_choose_city": "Choose city from list.",
        "msg_choose_city_or_type": "Enter nearest city or tap «Choose city»",
        "msg_city_multiple_regions": "City in multiple regions. Choose region:",
        "msg_session_expired": "Session expired. Start over.",
        "msg_session_expired_orders": "Session expired. Start over with «Create order».",
        "msg_session_expired_profile": "Session expired. Open «My profile» again.",
        "msg_profile_not_found": "Profile not found.",
        "msg_profile_not_found_role": "Profile not found. Choose role via /role.",
        "msg_profile_incomplete": "Profile incomplete.",
        "msg_choose_profile_edit": "Choose profile to edit:",
        "msg_choose_section_edit": "Choose section to edit:",
        "msg_profile_updated": "Profile updated.",
        "msg_whats_your_name": "What's your name?",
        "msg_choose_action": "Choose action:",
        "msg_what_city": "What city are you from?\nE.g. London / New York",
        "msg_brand_name": "Your brand / company name:",
        "msg_company_activity": "What does your company do?",
        "msg_brand_link": "Link to site, product or brand socials:",
        "msg_after_registration": "You can now create an order and find UGC creators.",
        "msg_advertiser_intro": (
            "You chose the advertiser role.\n"
            "Let's create your profile so you can place orders."
        ),
        "msg_creator_intro": (
            "You're a UGC creator. Brands look for creators here — a complete "
            "profile helps you get matched and receive relevant orders.\n\n"
            "Fill in your profile in a few minutes and you're in."
        ),
        "msg_step_ask_name": "What's your name?\n\nStep 1 of 12",
        "msg_step_ask_instagram": "Send link in format instagram.com/name\n\nStep 2 of 12",
        "msg_step_ask_instagram_first": "Send link in format instagram.com/name\n\nStep 1 of 12",
        "msg_step_ask_city": (
            "Brands match creators by city for product delivery and offline work. "
            "What city are you from?\n\nStep 3 of 12"
        ),
        "msg_step_ask_birth_date": (
            "Enter birth date as DD.MM.YYYY (e.g. 15.05.1995):\n\nStep 4 of 12"
        ),
        "msg_step_ask_gender": "Your gender:\n\nStep 5 of 12",
        "msg_step_ask_topics": (
            "What's your content about?\n"
            "List 1–5 topics, comma-separated: business, fitness, beauty, "
            "travel, food, fashion, family, tech, lifestyle, etc.\n\nStep 6 of 12"
        ),
        "msg_step_ask_audience_gender": (
            "Who mainly watches your content? By observation or stats\n\nStep 7 of 12"
        ),
        "msg_step_ask_audience_age": "Main age of your audience?\n\nStep 8 of 12",
        "msg_step_ask_audience_geo": (
            "Which cities is your audience in? Up to 3 cities, comma-separated\n\nStep 9 of 12"
        ),
        "msg_step_ask_price": (
            "Brands filter by budget — your price speeds up deals. "
            "Price for one UGC video? E.g. 500, 1000, 2000\n\nStep 10 of 12"
        ),
        "msg_step_ask_barter": (
            "Many orders are barter — «Yes» increases offers. "
            "Ready to work with brands on barter sometimes?\n\nStep 11 of 12"
        ),
        "msg_step_ask_work_format": (
            "Besides UGC, how else can you work with brands? "
            "Last step before matching.\n\nStep 12 of 12"
        ),
        "msg_agreements_intro_creator": (
            "Almost done. Please read the documents and confirm agreement."
        ),
        "msg_profile_created": (
            "Profile created 👍\n\n"
            "Brands are looking for creators — a complete profile increases "
            "your chances to get offers.\n\n"
            "Last step: verify your Instagram. This helps:\n"
            "— protect brands from fakes\n"
            "— build trust in your profile\n"
            "— get orders faster"
        ),
        "msg_instagram_already_registered": (
            "This Instagram account is already registered. "
            "Use another account or contact support."
        ),
        "msg_work_format_choose": (
            "Choose one: Place ads in my account or UGC only (no placement)."
        ),
        "msg_registration_aborted": (
            "Registration aborted. To finish, open «My profile» and confirm agreement."
        ),
        "err_instagram_empty": "Link cannot be empty. Send link as instagram.com/name",
        "err_instagram_format": "Invalid format. Need a link like instagram.com/name",
        "err_instagram_example": "Invalid Instagram link. Example: https://instagram.com/name",
        "err_gender_choose": "Choose one: Male or Female.",
        "err_audience_choose": "Choose: Mostly women, men or Mixed.",
        "err_age_choose": "Choose one of the age options.",
        "err_barter_choose": "Choose Yes or No.",
        "err_price_number": "Enter a number, e.g. 500, 1000, 2000.",
        "err_geo_max_cities": "Enter no more than 3 cities, comma-separated.",
        "msg_what_do_you_need": "What do you need?",
        "msg_choose_from_keyboard": "Choose one of the options on the keyboard.",
        "msg_coop_format": "What cooperation format do you prefer?",
        "msg_enter_number": "Enter a number, e.g. 1500.",
        "msg_how_many_creators": "How many creators do you need?",
        "msg_product_link": "Enter product link (for responding creators):",
        "msg_choose_count": "Choose one of: {counts}.",
        "msg_where_use_ugc": "Where will you use the UGC video?",
        "msg_send_photo": "Send product photo:",
        "msg_profile_empty_creator": "Profile not filled. «Create profile» or /creator",
        "msg_instagram_already_confirmed": "Your Instagram is already verified",
        "msg_invalid_format": "Invalid format.",
        "msg_invalid_id_format": "Invalid identifier format.",
        "msg_order_not_found_short": "Order not found.",
        "msg_no_bloggers_complain": "No bloggers to complain about.",
        "msg_complain_on": "Complain about {blogger_name}",
        "msg_choose_blogger_complain": "Choose blogger to complain about:",
        "msg_no_access_order": "You don't have access to this order.",
        "msg_choose_complaint_reason": "Choose complaint reason:",
        "msg_complaint_no_bloggers": "No bloggers to complain about.",
        "msg_invalid_user_id": "Invalid user ID.",
        "msg_invalid_reason": "Invalid reason.",
        "msg_data_error": "Data processing error.",
        "msg_describe_complaint": "Describe the complaint:",
        "msg_error_try_later": "An error occurred. Try again later.",
        "msg_enter_complaint_reason": "Please enter the complaint reason.",
        "msg_order_closed": "Order already closed.",
        "msg_order_closed_full": (
            "❗ Order already closed\n\n"
            "Thanks for responding — all creators for this order have been matched.\n\n"
            "We'll send new orders as soon as they appear.\n\n"
            "Watch for notifications in the bot 🙌"
        ),
        "msg_blogger_after_response_what_next": (
            "⏳ What's next\n\n"
            "💬 Wait for the advertiser to message — they have your Instagram link "
            "and will reach out first\n"
            "📩 Check Direct requests\n"
            "👀 Use watermarked previews for demos\n"
            "💸 Get payment after approving the preview\n"
            "🎥 Send final UGC only after payment\n"
            "❗ Refusing after responding may lead to account limits\n"
            "🤝 The platform is not involved in negotiations or payment."
        ),
        "msg_offer_accepted": "Response accepted! Wait for the advertiser to contact you.",
        "msg_offer_order_filled": (
            "Order is already filled. We saved your response — "
            "if someone drops out, we may contact you."
        ),
        "msg_advertiser_after_payment_success": (
            "Payment successful ✅\n\nCreator matching for your order is now active."
        ),
        "msg_advertiser_after_payment_what_next": (
            "🔄 **What's next**\n\n"
            "📩 Creators receive your offer\n"
            "🔗 You'll get responses with links to their profiles\n"
            "💬 You contact selected creators yourself"
        ),
        "msg_advertiser_after_payment_important": (
            "⚠️ **Important**\n\n"
            "🧷 Don't change offer terms after publishing\n"
            "🔄 If terms change, the creator may decline\n"
            "🤝 The platform is not a party to the deal\n"
            "💸 You pay creators directly\n"
            "👀 Pay after viewing watermarked preview\n"
            "🚫 The platform is not responsible for creators"
        ),
        "msg_phone_request": (
            "Enter phone number for order contact.\n"
            "Tap the button below or enter the number manually (e.g. 89001110777)."
        ),
        "msg_instagram_confirmed": (
            "Instagram verified ✅. Brands can send you offers."
        ),
        "msg_instagram_mismatch": (
            "The Instagram in your profile doesn't match the account "
            "you sent the code from. Open «My profile», edit the blogger profile "
            "and set the correct Instagram."
        ),
        "msg_too_many_requests": "Too many requests. Try again later.",
        "msg_invalid_order_id_short": "Invalid order ID.",
        "msg_order_activated": "Order activated, sent to bloggers.",
        "err_user_not_found": "User not found.",
        "err_blogger_registration": "Blogger registration error.",
        "err_advertiser_registration": "Advertiser registration error.",
        "err_order_not_found": "Order not found.",
        "err_order_not_active": "Order not active.",
        "err_order_creation": "Order creation error.",
        "err_order_already_responded": "You already responded to this order.",
        "err_order_response_limit": "Order response limit reached.",
        "err_order_not_new": "Order not in NEW status.",
        "err_order_not_yours": "Order does not belong to advertiser.",
        "err_interaction_not_found": "Interaction not found.",
        "err_interaction": "Interaction error.",
        "err_interaction_status": "Interaction not in ISSUE.",
        "err_interaction_resolution": "Invalid status for manual resolution.",
        "err_complaint_exists": "You already filed a complaint for this order.",
        "err_complaint_not_found": "Complaint not found.",
        "err_price_exceeds": "Amount exceeds maximum ({amount} {currency}).",
        "err_generic": "An error occurred: {error}",
        "msg_feedback_thanks": "Thanks, response saved.",
        "msg_feedback_thanks_short": "Thanks for your feedback.",
        "msg_interaction_not_found": "Interaction not found.",
        "msg_insufficient_rights": "Insufficient rights.",
        "msg_feedback_thanks_ok": "Thanks.",
        "msg_describe_problem": (
            "Describe the issue and attach screenshots or other proof."
        ),
        "msg_postpone_max": "Max postponements reached. Status set to 'No deal'.",
        "msg_postpone_72": "Check postponed 72h. Postponements: {cnt}/{max}",
        "msg_session_expired_feedback": "Session expired. Answer the feedback question again.",
        "msg_error_try_again": "Error. Try again.",
        "msg_add_description_or_photo": "Add description or photo, then tap «Send».",
        "msg_add_description_before_send": "Add description or photo before sending.",
        "msg_complaint_error": "Error creating request. Try again or contact support.",
        "msg_complaint_received": "We received your request. Support will look into it.",
        "msg_enter_reason": "Please enter the reason:",
        "msg_enter_reason_text": "Enter reason as text.",
        "msg_nps_thanks": "Thanks for rating!",
        "msg_nps_question": "How likely are you to recommend us? (1–5)",
        "msg_nps_thank": "Thanks! Your feedback matters.",
        "msg_invalid_format_short": "Invalid format.",
        "msg_invalid_id": "Invalid identifier.",
        "msg_score_1_to_5": "Score must be 1 to 5.",
        "msg_invalid_status": "Invalid status.",
        "msg_invalid_response": "Invalid response format.",
        "msg_error_later": "An error occurred. Try again later.",
        "msg_cancelled": "Cancelled.",
        "msg_invalid_uuid": "Invalid user identifier.",
        "msg_user_not_telegram": "User not on Telegram.",
    },
}

"""Default localized bot texts (key -> value per locale).

Used as fallback when bot_texts table has no row for (key, locale).
All bot messages and button labels must have keys here and in DB.
"""

# ru: Russian (current production)
# en: English (for global market)
# kk: Kazakh (Қазақша)
# be: Belarusian (Беларуская)
# uz: Uzbek (O'zbek)
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
        "btn_location_request": "📍 Поделиться геопозицией",
        "btn_location_map": "🗺 Выбрать на карте",
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
        "msg_user_not_found_start": "Пользователь не найден. Начните с /start.",
        "msg_registration_blocked": "Заблокированные пользователи не могут регистрироваться.",
        "msg_registration_pause": "Пользователи на паузе не могут регистрироваться.",
        "msg_instagram_blocked": "Заблокированные не могут подтверждать аккаунт.",
        "msg_instagram_pause": "На паузе не могут подтверждать аккаунт.",
        "msg_complaint_blocked": "Заблокированные пользователи не могут подавать жалобы.",
        "msg_complaint_pause": "Пользователи на паузе не могут подавать жалобы.",
        "msg_order_creation_blocked": "Заблокированные не могут создавать заказы.",
        "msg_order_creation_pause": "На паузе не могут создавать заказы.",
        "msg_payment_blocked": "Заблокированные пользователи не могут оплачивать заказы.",
        "msg_payment_pause": "Пользователи на паузе не могут оплачивать заказы.",
        "msg_feedback_blocked": "Заблокированные пользователи не могут оставлять отзыв.",
        "msg_feedback_pause": "Пользователи на паузе не могут оставлять отзыв.",
        "msg_feedback_rate_blocked": "Заблокированные пользователи не могут оценивать.",
        "msg_feedback_rate_pause": "Пользователи на паузе не могут оценивать.",
        # Feedback flow messages
        "msg_fb_thanks_saved": "Спасибо, ответ сохранен.",
        "msg_fb_thanks_feedback": "Спасибо за обратную связь.",
        "msg_fb_interaction_not_found": "Взаимодействие не найдено.",
        "msg_fb_insufficient_rights": "Недостаточно прав.",
        "msg_fb_no_deal_question_blog": "Подскажите, по какой причине не удалось договориться?",
        "msg_fb_no_deal_question_adv": "По какой причине не удалось договориться?",
        "msg_fb_thanks_short": "Спасибо.",
        "msg_fb_issue_prompt": (
            "Опишите проблему и приложите скриншоты переписки или "
            "другие подтверждения. Это поможет разобраться.\n"
            "👉 Напишите текст, прикрепите фото и нажмите «Отправить»."
        ),
        "msg_fb_postpone_max": (
            "Достигнут максимум переносов. "
            "Статус зафиксирован как 'Не договорились'."
        ),
        "msg_fb_postpone_72": "Проверка перенесена на 72 ч. Переносов: {cnt}/{max_cnt}",
        "msg_fb_postpone_ok_blog": (
            "Хорошо, вернёмся к этому позже 👍 "
            "Если заказчик напишет — просто ответьте ему."
        ),
        "msg_fb_postpone_ok_adv": (
            "Поняли, вернёмся к этому позже 👍\n"
            "ℹ️ Креатор не видит контакты. "
            "Связь начинается с вашей стороны."
        ),
        "msg_fb_ok_blog": (
            "Спасибо за обратную связь 👍 "
            "Если понадобится помощь — мы на связи."
        ),
        "msg_fb_ok_adv": (
            "Спасибо за обратную связь 👍 Желаем удачной работы с креатором."
        ),
        "msg_fb_invalid_format": "Неверный формат.",
        "msg_fb_invalid_response": "Неверный формат ответа.",
        "msg_fb_invalid_status": "Неверный статус.",
        "msg_fb_invalid_id": "Неверный идентификатор.",
        "msg_fb_error_try_later": "Произошла ошибка. Попробуйте позже.",
        "msg_fb_no_deal_other_prompt": "Напишите, пожалуйста, причину:",
        "msg_fb_enter_reason_text": "Введите причину текстом.",
        "msg_fb_session_expired": "Сессия истекла. Ответьте на вопрос обратной связи снова.",
        "msg_fb_session_expired_nps": "Сессия истекла. Ответьте на вопрос оценки снова.",
        "msg_fb_error_try_again": "Ошибка. Попробуйте снова.",
        "msg_fb_add_description_photo": "Добавьте описание или фото, затем нажмите «Отправить».",
        "msg_fb_add_description_before_send": "Добавьте описание или фото перед отправкой.",
        "msg_fb_complaint_error": (
            "Произошла ошибка при создании заявки. Попробуйте снова "
            "или обратитесь в поддержку через меню."
        ),
        "msg_fb_complaint_accepted": (
            "Мы приняли вашу заявку. Поддержка разберётся в ситуации. "
            "При необходимости нажмите «Поддержка» в меню."
        ),
        "msg_fb_nps_done_btn": "Готово",
        "msg_fb_nps_thank": (
            "Благодарю! 🙌\n"
            "Ваш отзыв сохранён, он помогает нам делать платформу UMC лучше🙏"
        ),
        "msg_fb_nps_question": "Оцените, пожалуйста, работу с платформой UMC по шкале от 1 до 5 ⭐",
        "msg_fb_nps_prompt_5_adv": (
            "Спасибо за оценку 5 ⭐ — очень рады, что вам было удобно работать "
            "с платформой UMC! 🙌\n"
            "Если есть 1–2 идеи, как сделать сервис ещё удобнее (интерфейс, "
            "подбор креаторов, уведомления и т. д.) — напишите в ответ.\n"
            "Мы внимательно читаем каждое предложение для развития платформы."
        ),
        "msg_fb_nps_prompt_5_blog": (
            "Спасибо за оценку 5 ⭐ — очень рады, что вам комфортно работать "
            "с заказчиками через платформу UMC! 🙌\n"
            "Если есть 1–2 идеи, как улучшить сервис (личный кабинет, подбор "
            "заказов, условия, поддержка) — напишите в ответ.\n"
            "Мы внимательно читаем каждое предложение для развития платформы."
        ),
        "msg_fb_nps_prompt_34_adv": (
            "Спасибо за вашу оценку 🙏\n"
            "Нам важно понять, что именно можно улучшить в работе с UMC.\n"
            "Пожалуйста, в одном сообщении напишите:\n"
            "– что не устроило (подбор, скорость, интерфейс, коммуникация)."
        ),
        "msg_fb_nps_prompt_34_blog": (
            "Спасибо за вашу оценку 🙏\n"
            "Нам важно понимать, что можно улучшить в работе с заказами через UMC.\n"
            "Пожалуйста, в одном сообщении напишите:\n"
            "– что было сложно или неудобно (условия, общение с заказчиком, интерфейс, "
            "уведомления и т. д.)."
        ),
        "msg_fb_nps_prompt_1_adv": (
            "Спасибо, что честно поставили 1 ⭐ — нам правда важно это знать 🙏\n"
            "Нам очень жаль, что опыт работы с платформой UMC оказался негативным.\n"
            "Пожалуйста, опишите в одном сообщении, что именно пошло не так:\n"
            "– проблемы с креатором;\n"
            "– сложности с платформой;\n"
            "– ошибки, задержки, недопонимание и т. д.\n"
            "Мы внимательно разберём ситуацию."
        ),
        "msg_fb_nps_prompt_1_blog": (
            "Спасибо, что честно поставили 1 ⭐ — нам правда важно это знать 🙏\n"
            "Нам очень жаль, что опыт работы через UMC оказался негативным.\n"
            "Пожалуйста, опишите в одном сообщении, что именно произошло:\n"
            "– проблемы с заказчиком;\n"
            "– сложность условий;\n"
            "– технические проблемы платформы;\n"
            "– любые другие моменты.\n"
            "Мы внимательно разберём ситуацию."
        ),
        "msg_fb_issue_send_btn": "📤 Отправить",
        "msg_fb_feedback_ok": "✅ Всё прошло нормально",
        "msg_fb_feedback_no_deal": "❌ Не договорились",
        "msg_fb_feedback_postpone": "⏳ Ещё не связался",
        "msg_fb_feedback_issue": "⚠️ Проблема / подозрение на мошенничество",
        "msg_fb_no_deal_conditions": "💰 Не сошлись по условиям",
        "msg_fb_no_deal_timing": "⏱ Не подошли сроки",
        "msg_fb_no_deal_differed": "📝 Условия отличались от оффера",
        "msg_fb_no_deal_creator_change": "📝 Креатор хотел изменить условия",
        "msg_fb_no_deal_other": "🤝 Другое",
        "msg_fb_score_1_to_5": "Оценка должна быть от 1 до 5.",
        "msg_fb_thanks_for_rating": "Спасибо за оценку!",
        "msg_fb_no_description": "Без описания",
        # Feedback scheduler: request messages (placeholders: creator_link, order_link_part)
        "msg_feedback_request_adv": (
            "Хотим убедиться, что всё прошло корректно 🙌\n"
            "Удалось ли вам связаться с креатором{creator_link}?\n"
            "Выберите подходящий вариант:"
        ),
        "msg_feedback_request_blog": (
            "Мы хотим убедиться, что всё прошло корректно 🙌\n"
            "Удалось ли вам связаться с заказчиком {order_link_part}"
        ),
        "msg_choose_role": "Выберите роль через /role.",
        "msg_fill_profile_orders": (
            "Заполните профиль (/advertiser или /creator), чтобы видеть заказы."
        ),
        "msg_confirm_agreement": (
            "Пожалуйста, подтвердите согласие с документами платформы."
        ),
        "msg_agreements_intro_default": (
            "Профиль создан. Ознакомьтесь с документами и подтвердите."
        ),
        "msg_label_offer": "📄 Оферта",
        "msg_label_privacy": "🔒 Политика конфиденциальности",
        "msg_label_consent": "🧾 Согласие на обработку персональных данных",
        "msg_confirm_docs_fallback": (
            "Подтвердите согласие с документами платформы."
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
        "msg_referral_payout_blocked": "Не можете запрашивать выплату.",
        "msg_referral_payout_pause": "Пользователи на паузе не могут запрашивать выплату.",
        "msg_referral_no_users": "У вас пока нет приведённых пользователей.",
        "msg_referral_access_denied": "Доступ запрещён.",
        "msg_referral_blocked": "Заблокированные не могут использовать команду.",
        "msg_referral_pause": "Пользователи на паузе не могут использовать команду.",
        "msg_referral_list_blocked": "Заблокированные не могут просматривать список.",
        "msg_referral_list_pause": "Пользователи на паузе не могут просматривать список.",
        "msg_referral_list_title": (
            "Ваши рефералы (страница {page}/{total_pages}):"
        ),
        "msg_referral_list_empty": "Ваши рефералы: пока никого.",
        "msg_referral_pending_block": (
            "Не заполнили профиль креатора (напоминайте заполнить):"
        ),
        "msg_referral_no_pending": "Нет рефералов без профиля.",
        "msg_referral_link_intro": "Ваша реферальная ссылка:",
        "lbl_referral_stats": "📊 Реферальная статистика",
        "lbl_referral_creators": "Приведено креаторов",
        "lbl_referral_orders": "Выполнено заказов",
        "lbl_referral_income_month": "Доход за текущий месяц",
        "lbl_referral_income_total": "Накоплено (всего)",
        "lbl_referral_paid": "Выплачено",
        "lbl_referral_balance": "Текущий баланс",
        "lbl_referral_orders_done": "выполнено заказов",
        "msg_offer_new_response": (
            "Новый отклик по вашему заказу 🙌\n\n"
            "👤 Креатор: {creator}\n"
            "📍 Город: {city}\n"
            "🎬 Формат: {format}\n"
            "💼 Готов работать на условиях оффера\n"
            "🔗 Профиль креатора:\n{profile_url}"
        ),
        "lbl_creator_fallback": "Креатор",
        "lbl_phone_dash": "Телефон: —",
        "lbl_telegram_dash": "Telegram: —",
        "msg_offer_contacts_header": "📞 Контакты заказчика для связи:\n\n",
        "msg_advertiser_new_response_what_next": (
            "🔔 Что дальше\n\n"
            "💬 Напишите креатору и обсудите детали\n"
            "✅ Креатор ознакомился с оффером и готов работать на указанных условиях\n"
            "⏱ Рекомендуем связаться в течение 30 мин\n\n"
            "⚠️ Напоминание\n\n"
            "🧷 Условия оффера не рекомендуется менять\n"
            "🔄 При изменении условий креатор может отказаться от сотрудничества\n"
            "➡️ Связь всегда начинается с вашей стороны"
        ),
        "msg_offer_response_blocked": "Заблокированные пользователи не могут откликаться.",
        "msg_offer_response_pause": "Пользователи на паузе не могут откликаться.",
        "msg_advertiser_contacts_warning": (
            "⚠️ **Безопасный порядок работы с блогерами:**\n\n"
            "• Платформа не рекомендует предоплату\n"
            "• Оплачивайте после получения превью с водяным знаком\n"
            "• Убедитесь в качестве контента перед финальной оплатой\n"
            "• Переговоры и сделки — напрямую между вами и блогером"
        ),
        # Messages: orders list
        "msg_my_orders_blocked": "Заблокированные не могут просматривать заказы.",
        "msg_my_orders_pause": "На паузе не могут просматривать заказы.",
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
        "msg_order_format": "Формат: {order_type}",
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
        "msg_choose_section_keyboard": "Выберите один из разделов на клавиатуре.",
        "msg_profile_updated": "Профиль обновлён.",
        "msg_advertiser_profile_not_found": "Профиль рекламодателя не найден.",
        "msg_unknown_field": "Неизвестное поле.",
        "msg_profile_update_failed": "Не удалось обновить профиль.",
        "err_city_not_place_use_map": (
            "Не удалось обновить профиль. Укажите местоположение на карте "
            "или поделитесь геопозицией."
        ),
        "err_instagram_format_example": "Неверный формат ссылки. Пример: instagram.com/name",
        "err_instagram_invalid": "Неверный формат ссылки Instagram.",
        "err_instagram_taken": "Этот Instagram уже зарегистрирован. Используйте другой.",
        "msg_city_picker_edit": (
            "Укажите ближайший крупный город или нажмите «Выбрать город» и выберите из списка."
        ),
        "msg_choose_buttons": "Выберите одну из кнопок.",
        "msg_name_updated": "Имя обновлено.",
        # Profile display
        "lbl_profile_your": "👤 Ваш профиль",
        "lbl_profile_general": "📋 Общая информация",
        "lbl_profile_name": "Имя",
        "lbl_profile_roles": "Роли",
        "lbl_profile_status": "Статус",
        "lbl_profile_blogger": "📸 Профиль блогера",
        "lbl_profile_not_filled": "Не заполнен",
        "lbl_profile_advertiser": "🏢 Профиль рекламодателя",
        "lbl_status_new": "Новый",
        "lbl_status_active": "Активен",
        "lbl_status_pause": "На паузе",
        "lbl_status_blocked": "Заблокирован",
        "lbl_audience_male": "Мужчины",
        "lbl_audience_female": "Женщины",
        "lbl_audience_all": "Все",
        "lbl_blogger_gender_male": "Мужской",
        "lbl_blogger_gender_female": "Женский",
        "lbl_role_blogger": "Блогер",
        "lbl_role_advertiser": "Рекламодатель",
        "lbl_yes": "Да",
        "lbl_no": "Нет",
        "lbl_work_format_ads": "Размещать рекламу у себя в аккаунте",
        "lbl_work_format_ugc": "Только UGC",
        "lbl_instagram": "Instagram",
        "lbl_confirmed": "Подтверждён",
        "lbl_city": "Город",
        "lbl_country": "Страна",
        "lbl_region": "Регион",
        "lbl_gender": "Пол",
        "lbl_birth_date": "Дата рождения",
        "lbl_topics": "Тематики",
        "lbl_audience": "Целевая аудитория",
        "lbl_geo": "География",
        "lbl_price": "Цена",
        "lbl_barter": "Бартер",
        "lbl_work_format": "Формат работы",
        "lbl_phone": "Телефон",
        "lbl_brand": "Бренд",
        "lbl_activity": "Деятельность",
        "lbl_site": "Сайт",
        "lbl_years": "лет",
        # Profile edit prompts (field_key -> prompt)
        "prompt_edit_nickname": "Введите новое имя:",
        "prompt_edit_instagram_url": "Прикрепите ссылку instagram.com/name:",
        "prompt_edit_city": "Из какого вы города?",
        "prompt_edit_blogger_gender": "Укажите ваш пол:",
        "prompt_edit_birth_date": "Укажите дату рождения в формате ДД.ММ.ГГГГ (например 15.05.1995):",
        "prompt_edit_topics": "Напишите 1–3 тематики через запятую:",
        "prompt_edit_audience_gender": "Кто в основном смотрит ваш контент?",
        "prompt_edit_audience_age": "Основной возраст вашей аудитории?",
        "prompt_edit_audience_geo": "Укажите до 3 городов через запятую:",
        "prompt_edit_price": "Укажите цену за 1 UGC‑видео ({currency}):",
        "prompt_edit_barter": "Готовы работать по бартеру?",
        "prompt_edit_work_format": "Как готовы работать с брендами?",
        "prompt_edit_name": "Введите имя:",
        "prompt_edit_phone": "Укажите номер телефона для связи. Пример: 89001110777",
        "prompt_edit_brand": "Название вашего бренда / компании / бизнеса:",
        "prompt_edit_site_link": "Ссылка на сайт, продукт или соцсети бренда:",
        "prompt_edit_generic": "Введите новое значение:",
        "lbl_edit_nickname": "Имя",
        "lbl_edit_instagram": "Instagram",
        "lbl_edit_city": "Город",
        "lbl_edit_blogger_gender": "Пол",
        "lbl_edit_birth_date": "Дата рождения",
        "lbl_edit_topics": "Тематики",
        "lbl_edit_audience_gender": "Пол аудитории",
        "lbl_edit_audience_age": "Возраст аудитории",
        "lbl_edit_audience_geo": "География аудитории",
        "lbl_edit_price": "Цена",
        "lbl_edit_barter": "Бартер",
        "lbl_edit_work_format": "Формат работы",
        "lbl_edit_name": "Имя",
        "lbl_edit_phone": "Телефон",
        "lbl_edit_brand": "Бренд",
        "lbl_edit_company_activity": "Деятельность компании",
        "lbl_edit_site_link": "Ссылка на сайт",
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
            "Сколько стоит одно UGC‑видео? Цена ({currency}), например: 500, 1000, 2000\n\nШаг 10 из 12"
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
        # Validators (shared)
        "err_not_bot_command": (
            "Не используйте команды бота в качестве ответа. Введите текст заново."
        ),
        "err_offer_text_min": "Опишите задачу подробнее (минимум {min} символов).",
        "err_offer_text_max": "Текст слишком длинный (максимум {max} символов).",
        "err_barter_required": "Опишите бартерное предложение.",
        "err_barter_min": "Опишите бартер (мин. {min} символов).",
        "err_barter_max": "Текст длинный (макс. {max} символов).",
        "err_url_max": "Ссылка слишком длинная (максимум {max} символов).",
        "err_url_scheme": "Введите ссылку (http:// или https://).",
        "err_url_invalid": "Введите корректную ссылку.",
        "err_url_example": (
            "Введите корректную ссылку (например, сайт.рф или example.com)."
        ),
        "err_product_link_empty": "Ссылка не может быть пустой. Введите снова:",
        "err_geo_required": (
            "Укажите один вариант: город, регион или страна. "
            "Примеры: Казань, Москва, Татарстан, РФ"
        ),
        "err_geo_max": "Текст слишком длинный (максимум {max} символов).",
        "err_min_chars": "Введите минимум {min} символа.",
        "err_max_chars": "Максимум {max} символов.",
        "err_phone_empty": "Номер телефона не может быть пустым. Введите снова:",
        "err_phone_digits": (
            "Введите корректный номер (10–11 цифр). Пример: 89001110777"
        ),
        "err_phone_too_many": "Слишком много цифр. Пример: 89001110777",
        "err_phone_invalid": "Введите корректный номер. Пример: 89001110777",
        "err_birth_date_empty": (
            "Введите дату рождения в формате ДД.ММ.ГГГГ (например 15.05.1995)."
        ),
        "err_birth_date_format": (
            "Неверный формат. Используйте ДД.ММ.ГГГГ (например 15.05.1995)."
        ),
        "err_birth_date_digits": (
            "Введите дату цифрами в формате ДД.ММ.ГГГГ (например 15.05.1995)."
        ),
        "err_birth_date_invalid": "Некорректная дата. Проверьте день, месяц и год.",
        "err_birth_date_future": "Дата рождения не может быть в будущем.",
        "err_birth_date_min_age": "Возраст должен быть не менее {age} лет.",
        "err_birth_date_max_age": (
            "Укажите реальную дату рождения (возраст до {age} лет)."
        ),
        "err_city_required": "Укажите город. Введите снова:",
        "err_city_from_location": "Не удалось определить город по геопозиции. Введите город вручную или попробуйте ещё раз.",
        "err_city_not_found_use_map": (
            "Не удалось определить местоположение по названию. "
            "Введите точное название города или отправьте геолокацию."
        ),
        "err_company_activity_max": "Максимум {max} символов.",
        "err_nickname_no_url": "Введите имя, а не ссылку на Instagram.",
        "err_topics_empty": "Введите хотя бы одну тематику:",
        "err_topics_max": "Укажите не более {max} тематик.",
        "err_audience_geo_empty": "Укажите хотя бы один город. Введите снова:",
        "err_audience_geo_max": "Максимум {max} символов.",
        "err_price_positive": "Цена должна быть больше 0.",
        "err_price_max": (
            "Сумма превышает максимально допустимую ({max} {currency})."
        ),
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
        "msg_order_task_description": (
            "Кратко опишите задачу для креаторов.\n"
            "Что снять и в каком формате. Пример: Видео с распаковкой."
        ),
        "msg_order_budget": (
            "Бюджет за 1 UGC-видео? Укажите цену ({currency}): 500, 1000, 2000"
        ),
        "msg_order_barter_ask": (
            "Что вы предлагаете по бартеру?\n"
            "Продукт бренда (опишите коротко) + доставка"
        ),
        "msg_order_photo_intro": (
            "Прикрепите фото (по желанию).\n"
            "Фотография поможет креатору быстрее понять заказ и повысит отклик "
            "на ваше предложение"
        ),
        "msg_order_photo_choose": (
            "Выберите «Добавить фото» или «Пропустить» на клавиатуре, "
            "либо отправьте фото продукта."
        ),
        "msg_order_deadline": (
            "В какие сроки вам нужен контент? "
            "Укажите, через сколько дней после согласования "
            "вы ожидаете превью."
        ),
        "msg_order_geo": (
            "В каком городе, регионе или стране может находиться креатор? "
            "Укажите один вариант: например, Казань, Москва, Татарстан или РФ. "
            "Нужно для бартерных заказов и доставки продукта."
        ),
        # Messages: Instagram
        "msg_profile_empty_creator": (
            "Профиль не заполнен. «Создать профиль» или /creator"
        ),
        "msg_instagram_already_confirmed": "Ваш Instagram‑аккаунт уже подтвержден",
        "msg_instagram_verify_instruction": (
            "<b>Чтобы подтвердить Instagram‑аккаунт, сделайте 3 шага:</b>\n\n"
            "1. Скопируйте код ниже\n"
            "2. Отправьте его в личные сообщения Instagram‑аккаунту UMC\n"
            "3. Дождитесь автоматического подтверждения\n\n"
            '🔗 Instagram UMC: <a href="{url}">{url}</a>\n\n'
            "🔐 Ваш код (код действует 15 минут) 👇"
        ),
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
            "Текущая подборка блогеров уже закрыта. Мы добавим вас в лист ожидания — "
            "если потребуется замена блогера или заказчик решит расширить подборку, "
            "мы первыми отправим вам предложение."
        ),
        "msg_offer_order_filled_toast": "Записали в лист ожидания",
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
        "err_order_invalid_id": "Неверный идентификатор заказа.",
        "msg_offer_skipped": "Ок, пропущено.",
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
        # Language/country selection
        "language_prompt": "Выберите язык / Choose language:",
        "country_prompt": "Выберите вашу страну:",
        # Offer texts
        "offer_header": "Новый заказ",
        "offer_details_header": "📋 Детали заказа:",
        "offer_format": "🎥 Формат: {format_label}",
        "offer_task": "📝 Задача: {task}",
        "offer_budget": "💰 Бюджет: {price} {currency} за 1 UGC-видео",
        "offer_barter": "🎁 Бартер: {description}",
        "offer_content_usage": "📢 Использование: {usage}",
        "offer_deadlines": "⏱ Сроки: {deadlines}",
        "offer_geography": "📍 География: {geography}",
        "offer_bloggers_needed": "👥 Нужно креаторов: {count}",
        "offer_warning": (
            "⚠️ Важно\n"
            "🧷 Откликайтесь только если готовы работать на указанных условиях\n"
            "❗ Отказ после отклика без изменения условий со стороны заказчика"
            "   может привести к жалобе и ограничению аккаунта"
        ),
        "offer_how_it_works": (
            "⏳ Как это работает\n"
            "● Вы откликаетесь на оффер\n"
            "● Получаете ссылку на продукт\n"
            "● Заказчик получает ваш профиль и пишет вам первым\n"
            "● Платформа не участвует в переговорах и оплате"
        ),
        "offer_format_label_ugc_placement": "UGC + размещение",
        "offer_format_label_ugc_only": "UGC-видео для бренда",
        "btn_offer_accept": "Готов снять UGC",
        "btn_offer_skip": "Пропустить",
        # Complaint button
        "btn_complaint": "Пожаловаться на {name}",
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
        "btn_location_request": "📍 Share location",
        "btn_location_map": "🗺 Pick on map",
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
        "msg_user_not_found_start": "User not found. Start with /start.",
        "msg_registration_blocked": "Blocked users cannot register.",
        "msg_registration_pause": "Paused users cannot register.",
        "msg_instagram_blocked": "Blocked users cannot verify account.",
        "msg_instagram_pause": "Paused users cannot verify account.",
        "msg_complaint_blocked": "Blocked users cannot file complaints.",
        "msg_complaint_pause": "Paused users cannot file complaints.",
        "msg_order_creation_blocked": "Blocked users cannot create orders.",
        "msg_order_creation_pause": "Paused users cannot create orders.",
        "msg_payment_blocked": "Blocked users cannot pay for orders.",
        "msg_payment_pause": "Paused users cannot pay for orders.",
        "msg_feedback_blocked": "Blocked users cannot leave feedback.",
        "msg_feedback_pause": "Paused users cannot leave feedback.",
        "msg_feedback_rate_blocked": "Blocked users cannot rate.",
        "msg_feedback_rate_pause": "Paused users cannot rate.",
        # Feedback flow messages
        "msg_fb_thanks_saved": "Thanks, response saved.",
        "msg_fb_thanks_feedback": "Thanks for your feedback.",
        "msg_fb_interaction_not_found": "Interaction not found.",
        "msg_fb_insufficient_rights": "Insufficient rights.",
        "msg_fb_no_deal_question_blog": "What was the reason you couldn't reach an agreement?",
        "msg_fb_no_deal_question_adv": "What was the reason you couldn't reach an agreement?",
        "msg_fb_thanks_short": "Thanks.",
        "msg_fb_issue_prompt": (
            "Describe the issue and attach screenshots of the conversation or "
            "other evidence. This will help us look into it.\n"
            "👉 Write your message, attach photos and tap «Send»."
        ),
        "msg_fb_postpone_max": (
            "Maximum postponements reached. Status set to 'No deal'."
        ),
        "msg_fb_postpone_72": "Check postponed by 72 h. Postponements: {cnt}/{max_cnt}",
        "msg_fb_postpone_ok_blog": (
            "Okay, we'll get back to this later 👍 "
            "If the advertiser messages you — just reply."
        ),
        "msg_fb_postpone_ok_adv": (
            "Got it, we'll get back to this later 👍\n"
            "ℹ️ Creator doesn't see your contacts. "
            "You need to initiate contact."
        ),
        "msg_fb_ok_blog": (
            "Thanks for your feedback 👍 If you need help — we're here."
        ),
        "msg_fb_ok_adv": (
            "Thanks for your feedback 👍 "
            "Wishing you a smooth collaboration with the creator."
        ),
        "msg_fb_invalid_format": "Invalid format.",
        "msg_fb_invalid_response": "Invalid response format.",
        "msg_fb_invalid_status": "Invalid status.",
        "msg_fb_invalid_id": "Invalid identifier.",
        "msg_fb_error_try_later": "An error occurred. Please try later.",
        "msg_fb_no_deal_other_prompt": "Please write the reason:",
        "msg_fb_enter_reason_text": "Please enter the reason as text.",
        "msg_fb_session_expired": "Session expired. Please answer the feedback question again.",
        "msg_fb_session_expired_nps": "Session expired. Please answer the rating question again.",
        "msg_fb_error_try_again": "Error. Please try again.",
        "msg_fb_add_description_photo": "Add a description or photo, then tap «Send».",
        "msg_fb_add_description_before_send": "Add a description or photo before sending.",
        "msg_fb_complaint_error": (
            "An error occurred while creating the request. Please try again "
            "or contact support via the menu."
        ),
        "msg_fb_complaint_accepted": (
            "We have received your request. Support will look into it. "
            "If needed, tap «Support» in the menu."
        ),
        "msg_fb_nps_done_btn": "Done",
        "msg_fb_nps_thank": (
            "Thank you! 🙌\n"
            "Your feedback has been saved and helps us make UMC better 🙏"
        ),
        "msg_fb_nps_question": "Please rate your experience with UMC from 1 to 5 ⭐",
        "msg_fb_nps_prompt_5_adv": (
            "Thanks for the 5 ⭐ — we're glad the platform worked well for you! 🙌\n"
            "If you have 1–2 ideas to make the service even better (interface, "
            "creator matching, notifications, etc.) — reply with them.\n"
            "We read every suggestion to improve the platform."
        ),
        "msg_fb_nps_prompt_5_blog": (
            "Thanks for the 5 ⭐ — we're glad working with advertisers via UMC "
            "is comfortable for you! 🙌\n"
            "If you have 1–2 ideas to improve the service (dashboard, "
            "order matching, terms, support) — reply with them.\n"
            "We read every suggestion to improve the platform."
        ),
        "msg_fb_nps_prompt_34_adv": (
            "Thanks for your rating 🙏\n"
            "We want to understand what we can improve in your experience with UMC.\n"
            "Please write in one message:\n"
            "– what didn't work (matching, speed, interface, communication)."
        ),
        "msg_fb_nps_prompt_34_blog": (
            "Thanks for your rating 🙏\n"
            "We want to understand what we can improve in your experience with orders.\n"
            "Please write in one message:\n"
            "– what was difficult or inconvenient (terms, communication with advertiser, "
            "interface, notifications, etc.)."
        ),
        "msg_fb_nps_prompt_1_adv": (
            "Thanks for the honest 1 ⭐ — we really want to know 🙏\n"
            "We're sorry your experience with UMC was negative.\n"
            "Please describe in one message what went wrong:\n"
            "– issues with the creator;\n"
            "– platform difficulties;\n"
            "– errors, delays, misunderstandings, etc.\n"
            "We will look into the situation."
        ),
        "msg_fb_nps_prompt_1_blog": (
            "Thanks for the honest 1 ⭐ — we really want to know 🙏\n"
            "We're sorry your experience with UMC was negative.\n"
            "Please describe in one message what happened:\n"
            "– issues with the advertiser;\n"
            "– terms difficulties;\n"
            "– platform technical issues;\n"
            "– any other points.\n"
            "We will look into the situation."
        ),
        "msg_fb_issue_send_btn": "📤 Send",
        "msg_fb_feedback_ok": "✅ All went well",
        "msg_fb_feedback_no_deal": "❌ No deal",
        "msg_fb_feedback_postpone": "⏳ Haven't contacted yet",
        "msg_fb_feedback_issue": "⚠️ Problem / suspected fraud",
        "msg_fb_no_deal_conditions": "💰 Didn't agree on terms",
        "msg_fb_no_deal_timing": "⏱ Timing didn't work",
        "msg_fb_no_deal_differed": "📝 Terms differed from offer",
        "msg_fb_no_deal_creator_change": "📝 Creator wanted to change terms",
        "msg_fb_no_deal_other": "🤝 Other",
        "msg_fb_score_1_to_5": "Rating must be from 1 to 5.",
        "msg_fb_thanks_for_rating": "Thanks for your rating!",
        "msg_fb_no_description": "No description",
        # Feedback scheduler: request messages (placeholders: creator_link, order_link_part)
        "msg_feedback_request_adv": (
            "We want to make sure everything went well 🙌\n"
            "Were you able to get in touch with the creator{creator_link}?\n"
            "Choose the option that fits:"
        ),
        "msg_feedback_request_blog": (
            "We want to make sure everything went well 🙌\n"
            "Were you able to get in touch with the advertiser {order_link_part}"
        ),
        "msg_choose_role": "Choose role via /role.",
        "msg_fill_profile_orders": (
            "Fill your profile (/advertiser or /creator) to see orders."
        ),
        "msg_confirm_agreement": "Please confirm agreement with platform documents.",
        "msg_agreements_intro_default": (
            "Profile created. Please read the documents and confirm."
        ),
        "msg_label_offer": "📄 Offer",
        "msg_label_privacy": "🔒 Privacy Policy",
        "msg_label_consent": "🧾 Consent to personal data processing",
        "msg_confirm_docs_fallback": (
            "Please confirm your agreement with the platform documents."
        ),
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
        "msg_referral_payout_blocked": "You cannot request payout.",
        "msg_referral_payout_pause": "Paused users cannot request payout.",
        "msg_referral_no_users": "You have no referred users yet.",
        "msg_referral_access_denied": "Access denied.",
        "msg_referral_blocked": "Blocked users cannot use this command.",
        "msg_referral_pause": "Paused users cannot use this command.",
        "msg_referral_list_blocked": "Blocked users cannot view the list.",
        "msg_referral_list_pause": "Paused users cannot view the list.",
        "msg_referral_list_title": "Your referrals (page {page}/{total_pages}):",
        "msg_referral_list_empty": "Your referrals: none yet.",
        "msg_referral_pending_block": "Haven't filled creator profile (remind them):",
        "msg_referral_no_pending": "No referrals without profile.",
        "msg_referral_link_intro": "Your referral link:",
        "lbl_referral_stats": "📊 Referral stats",
        "lbl_referral_creators": "Creators referred",
        "lbl_referral_orders": "Orders completed",
        "lbl_referral_income_month": "Income this month",
        "lbl_referral_income_total": "Total earned",
        "lbl_referral_paid": "Paid out",
        "lbl_referral_balance": "Current balance",
        "lbl_referral_orders_done": "orders completed",
        "msg_offer_new_response": (
            "New response to your order 🙌\n\n"
            "👤 Creator: {creator}\n"
            "📍 City: {city}\n"
            "🎬 Format: {format}\n"
            "💼 Ready to work on offer terms\n"
            "🔗 Creator profile:\n{profile_url}"
        ),
        "lbl_creator_fallback": "Creator",
        "lbl_phone_dash": "Phone: —",
        "lbl_telegram_dash": "Telegram: —",
        "msg_offer_contacts_header": "📞 Advertiser contacts:\n\n",
        "msg_advertiser_new_response_what_next": (
            "🔔 What's next\n\n"
            "💬 Message the creator and discuss details\n"
            "✅ Creator has read the offer and is ready to work on these terms\n"
            "⏱ We recommend getting in touch within 30 min\n\n"
            "⚠️ Reminder\n\n"
            "🧷 Do not change offer terms\n"
            "🔄 If terms change, the creator may decline\n"
            "➡️ You always initiate contact"
        ),
        "msg_offer_response_blocked": "Blocked users cannot respond to offers.",
        "msg_offer_response_pause": "Paused users cannot respond to offers.",
        "msg_advertiser_contacts_warning": (
            "⚠️ **Safe workflow with creators:**\n\n"
            "• Platform does not recommend prepayment\n"
            "• Pay after receiving watermarked preview\n"
            "• Verify content quality before final payment\n"
            "• Negotiations and payments are between you and the creator"
        ),
        "msg_my_orders_blocked": "Blocked users cannot view orders.",
        "msg_my_orders_pause": "Paused users cannot view orders.",
        "msg_orders_title": "Your orders (page {page}/{total_pages}):",
        "msg_orders_blogger_title": "Orders you responded to (page {page}/{total_pages}):",
        "msg_order_status": "Status: {status_label}",
        "msg_order_creators": "Creators: {bloggers_needed}",
        "msg_order_matched": "Matched: {matched_count} / {bloggers_needed}",
        "msg_order_date_created": "Created: {date}",
        "msg_order_date_completed": "Completed: {date}",
        "msg_order_link": "Project link: {link}",
        "msg_order_format": "Format: {order_type}",
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
        "msg_choose_section_keyboard": "Choose one of the sections on the keyboard.",
        "msg_profile_updated": "Profile updated.",
        "msg_advertiser_profile_not_found": "Advertiser profile not found.",
        "msg_unknown_field": "Unknown field.",
        "msg_profile_update_failed": "Failed to update profile.",
        "err_city_not_place_use_map": (
            "Could not update profile. Please indicate your location on the "
            "map or share your geolocation."
        ),
        "err_instagram_format_example": "Invalid link format. Example: instagram.com/name",
        "err_instagram_invalid": "Invalid Instagram link format.",
        "err_instagram_taken": "This Instagram is already registered. Use another one.",
        "msg_city_picker_edit": (
            "Enter nearest city or tap «Choose city» and select from list."
        ),
        "msg_choose_buttons": "Choose one of the options.",
        "msg_name_updated": "Name updated.",
        # Profile display
        "lbl_profile_your": "👤 Your profile",
        "lbl_profile_general": "📋 General",
        "lbl_profile_name": "Name",
        "lbl_profile_roles": "Roles",
        "lbl_profile_status": "Status",
        "lbl_profile_blogger": "📸 Creator profile",
        "lbl_profile_not_filled": "Not filled",
        "lbl_profile_advertiser": "🏢 Advertiser profile",
        "lbl_status_new": "New",
        "lbl_status_active": "Active",
        "lbl_status_pause": "Paused",
        "lbl_status_blocked": "Blocked",
        "lbl_audience_male": "Male",
        "lbl_audience_female": "Female",
        "lbl_audience_all": "All",
        "lbl_blogger_gender_male": "Male",
        "lbl_blogger_gender_female": "Female",
        "lbl_role_blogger": "Creator",
        "lbl_role_advertiser": "Advertiser",
        "lbl_yes": "Yes",
        "lbl_no": "No",
        "lbl_work_format_ads": "Place ads in your account",
        "lbl_work_format_ugc": "UGC only",
        "lbl_instagram": "Instagram",
        "lbl_confirmed": "Verified",
        "lbl_city": "City",
        "lbl_country": "Country",
        "lbl_region": "Region",
        "lbl_gender": "Gender",
        "lbl_birth_date": "Birth date",
        "lbl_topics": "Topics",
        "lbl_audience": "Target audience",
        "lbl_geo": "Geography",
        "lbl_price": "Price",
        "lbl_barter": "Barter",
        "lbl_work_format": "Work format",
        "lbl_phone": "Phone",
        "lbl_brand": "Brand",
        "lbl_activity": "Activity",
        "lbl_site": "Site",
        "lbl_years": "years",
        "prompt_edit_nickname": "Enter new name:",
        "prompt_edit_instagram_url": "Attach link instagram.com/name:",
        "prompt_edit_city": "What city are you from?",
        "prompt_edit_blogger_gender": "Your gender:",
        "prompt_edit_birth_date": "Birth date as DD.MM.YYYY (e.g. 15.05.1995):",
        "prompt_edit_topics": "List 1–3 topics, comma-separated:",
        "prompt_edit_audience_gender": "Who mainly watches your content?",
        "prompt_edit_audience_age": "Main age of your audience?",
        "prompt_edit_audience_geo": "Up to 3 cities, comma-separated:",
        "prompt_edit_price": "Price for 1 UGC video ({currency}):",
        "prompt_edit_barter": "Ready to work on barter?",
        "prompt_edit_work_format": "How do you work with brands?",
        "prompt_edit_name": "Enter name:",
        "prompt_edit_phone": "Phone number for contact. Example: +1234567890",
        "prompt_edit_brand": "Your brand / company name:",
        "prompt_edit_site_link": "Link to site, product or brand socials:",
        "prompt_edit_generic": "Enter new value:",
        "lbl_edit_nickname": "Name",
        "lbl_edit_instagram": "Instagram",
        "lbl_edit_city": "City",
        "lbl_edit_blogger_gender": "Gender",
        "lbl_edit_birth_date": "Birth date",
        "lbl_edit_topics": "Topics",
        "lbl_edit_audience_gender": "Audience gender",
        "lbl_edit_audience_age": "Audience age",
        "lbl_edit_audience_geo": "Audience geography",
        "lbl_edit_price": "Price",
        "lbl_edit_barter": "Barter",
        "lbl_edit_work_format": "Work format",
        "lbl_edit_name": "Name",
        "lbl_edit_phone": "Phone",
        "lbl_edit_brand": "Brand",
        "lbl_edit_company_activity": "Company activity",
        "lbl_edit_site_link": "Site link",
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
            "Price for one UGC video ({currency})? E.g. 500, 1000, 2000\n\nStep 10 of 12"
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
        # Validators (shared)
        "err_not_bot_command": (
            "Do not use bot commands as your answer. Enter text again."
        ),
        "err_offer_text_min": "Describe the task in more detail (min {min} characters).",
        "err_offer_text_max": "Text too long (max {max} characters).",
        "err_barter_required": "Describe the barter offer.",
        "err_barter_min": "Describe the barter (min {min} characters).",
        "err_barter_max": "Text too long (max {max} characters).",
        "err_url_max": "Link too long (max {max} characters).",
        "err_url_scheme": "Enter a link (http:// or https://).",
        "err_url_invalid": "Enter a valid link.",
        "err_url_example": (
            "Enter a valid link (e.g. example.com or site.com)."
        ),
        "err_product_link_empty": "Link cannot be empty. Enter again:",
        "err_geo_required": (
            "Specify one option: city, region or country. "
            "Examples: London, UK, Worldwide"
        ),
        "err_geo_max": "Text too long (max {max} characters).",
        "err_min_chars": "Enter at least {min} characters.",
        "err_max_chars": "Max {max} characters.",
        "err_phone_empty": "Phone number cannot be empty. Enter again:",
        "err_phone_digits": "Enter a valid number (10–11 digits). Example: 89001110777",
        "err_phone_too_many": "Too many digits. Example: 89001110777",
        "err_phone_invalid": "Enter a valid number. Example: 89001110777",
        "err_birth_date_empty": (
            "Enter date of birth as DD.MM.YYYY (e.g. 15.05.1995)."
        ),
        "err_birth_date_format": (
            "Invalid format. Use DD.MM.YYYY (e.g. 15.05.1995)."
        ),
        "err_birth_date_digits": (
            "Enter date in digits as DD.MM.YYYY (e.g. 15.05.1995)."
        ),
        "err_birth_date_invalid": "Invalid date. Check day, month and year.",
        "err_birth_date_future": "Date of birth cannot be in the future.",
        "err_birth_date_min_age": "Age must be at least {age} years.",
        "err_birth_date_max_age": (
            "Enter a real date of birth (age up to {age} years)."
        ),
        "err_city_required": "Specify city. Enter again:",
        "err_city_from_location": "Could not determine city from location. Enter city manually or try again.",
        "err_city_not_found_use_map": (
            "Could not determine location from the name. "
            "Enter the exact city name or share your location."
        ),
        "err_company_activity_max": "Max {max} characters.",
        "err_nickname_no_url": "Enter name, not an Instagram link.",
        "err_topics_empty": "Enter at least one topic:",
        "err_topics_max": "Enter no more than {max} topics.",
        "err_audience_geo_empty": "Specify at least one city. Enter again:",
        "err_audience_geo_max": "Max {max} characters.",
        "err_price_positive": "Price must be greater than 0.",
        "err_price_max": ("Amount exceeds maximum allowed ({max} {currency})."),
        "msg_what_do_you_need": "What do you need?",
        "msg_choose_from_keyboard": "Choose one of the options on the keyboard.",
        "msg_coop_format": "What cooperation format do you prefer?",
        "msg_enter_number": "Enter a number, e.g. 1500.",
        "msg_how_many_creators": "How many creators do you need?",
        "msg_product_link": "Enter product link (for responding creators):",
        "msg_choose_count": "Choose one of: {counts}.",
        "msg_where_use_ugc": "Where will you use the UGC video?",
        "msg_send_photo": "Send product photo:",
        "msg_order_task_description": (
            "Briefly describe the task for creators.\n"
            "What to shoot and in what format. Example: Unboxing video."
        ),
        "msg_order_budget": (
            "Budget per 1 UGC video? Enter price ({currency}): 500, 1000, 2000"
        ),
        "msg_order_barter_ask": (
            "What do you offer as barter?\n"
            "Brand product (short description) + delivery"
        ),
        "msg_order_photo_intro": (
            "Attach a photo (optional).\n"
            "A photo helps the creator understand the order faster and boosts response."
        ),
        "msg_order_photo_choose": (
            "Choose «Add photo» or «Skip» on the keyboard, or send a product photo."
        ),
        "msg_order_deadline": (
            "When do you need the content? "
            "Specify how many days after agreement you expect the preview."
        ),
        "msg_order_geo": (
            "In which city, region or country can the creator be located? "
            "Specify one option, e.g. London, UK or Worldwide. "
            "Used for barter orders and product delivery."
        ),
        "msg_profile_empty_creator": "Profile not filled. «Create profile» or /creator",
        "msg_instagram_already_confirmed": "Your Instagram is already verified",
        "msg_instagram_verify_instruction": (
            "<b>To verify your Instagram account, follow 3 steps:</b>\n\n"
            "1. Copy the code below\n"
            "2. Send it in a direct message to the UMC Instagram account\n"
            "3. Wait for automatic verification\n\n"
            '🔗 Instagram UMC: <a href="{url}">{url}</a>\n\n'
            "🔐 Your code (valid for 15 minutes) 👇"
        ),
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
            "The current creator shortlist is closed. We've added you to the waitlist — "
            "if we need a replacement or the advertiser expands the shortlist, "
            "we'll send you an offer first."
        ),
        "msg_offer_order_filled_toast": "Added to waitlist",
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
        "err_order_invalid_id": "Invalid order identifier.",
        "msg_offer_skipped": "OK, skipped.",
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
        # Language/country selection
        "language_prompt": "Choose language:",
        "country_prompt": "Select your country:",
        # Offer texts
        "offer_header": "New order",
        "offer_details_header": "📋 Order details:",
        "offer_format": "🎥 Format: {format_label}",
        "offer_task": "📝 Task: {task}",
        "offer_budget": "💰 Budget: {price} {currency} per UGC video",
        "offer_barter": "🎁 Barter: {description}",
        "offer_content_usage": "📢 Usage: {usage}",
        "offer_deadlines": "⏱ Deadlines: {deadlines}",
        "offer_geography": "📍 Geography: {geography}",
        "offer_bloggers_needed": "👥 Creators needed: {count}",
        "offer_warning": (
            "⚠️ Important\n"
            "🧷 Respond only if you are ready to work under the stated conditions\n"
            "❗ Refusing after responding without changed conditions from the advertiser"
            "   may lead to a complaint and account restriction"
        ),
        "offer_how_it_works": (
            "⏳ How it works\n"
            "● You respond to the offer\n"
            "● You receive a product link\n"
            "● The advertiser gets your profile and contacts you first\n"
            "● The platform is not involved in negotiations or payment"
        ),
        "offer_format_label_ugc_placement": "UGC + placement",
        "offer_format_label_ugc_only": "UGC video for brand",
        "btn_offer_accept": "Ready to shoot UGC",
        "btn_offer_skip": "Skip",
        # Complaint button
        "btn_complaint": "Report {name}",
    },
    "kk": {
        "start_message": (
            "UMC — UGC сервисі.\n"
            "Бизнес үшін — креаторларды таңдау, креаторларға — тапсырыстар."
        ),
        "support_response": (
            "Қолдау қызметі: @usemycontent\nКез келген сұрақтар бойынша хабарласыңыз!"
        ),
        "receipt_description": "Use My Content платформа қызметтері",
        "btn_creator": "Мен креатормын",
        "btn_advertiser": "Маған UGC-креаторлар керек",
        "btn_support": "💬 Қолдау",
        "btn_my_orders": "📂 Менің тапсырыстарым",
        "btn_change_role": "Рөлді өзгерту",
        "btn_create_profile": "Профиль жасау",
        "btn_advertiser_start": "Бастау",
        "btn_create_order": "➕ Тапсырыс жасау",
        "btn_confirm_instagram": "✅ Instagram растау",
        "btn_confirm_agreement": "✅ Келісімді растау",
        "btn_edit_profile": "Профильді өзгерту",
        "btn_my_profile": "👤 Менің профилім",
        "btn_work_format_ads": "📢 Жарнаманы өз аккаунтымда орналастыру",
        "btn_work_format_ugc_only": "❌ Тек UGC (орналастырусыз)",
        "btn_phone_request": "📱 Телефон нөмірін бөлісу",
        "btn_location_request": "📍 Геолокацияны бөлісу",
        "btn_location_map": "🗺 Картадан таңдау",
        "btn_city_picker": "Қаланы таңдау",
        "btn_edit_profile_blogger": "Блогер профилін өзгерту",
        "btn_edit_profile_advertiser": "Жарнама беруші профилін өзгерту",
        "btn_audience_f": "👩 Негізінен әйелдер",
        "btn_audience_m": "👨 Негізінен ерлер",
        "btn_audience_a": "👥 Аралас",
        "btn_gender_m": "Ер",
        "btn_gender_f": "Әйел",
        "btn_age_0_17": "18-ден кіші",
        "btn_age_18_24": "18–24",
        "btn_age_25_34": "25–34",
        "btn_age_35_44": "35–44",
        "btn_age_45_99": "45+",
        "btn_barter_yes": "Иә",
        "btn_barter_no": "Жоқ",
        "btn_payout": "Төлем",
        "btn_back": "Артқа",
        "btn_forward": "Алға",
        "btn_back_arrow": "⬅️ Артқа",
        "btn_forward_arrow": "Алға ➡️",
        "btn_pay_order": "💳 №{creation_number} төлеу",
        "btn_open_profile": "🔗 Профильді ашу",
        "btn_write_telegram": "Телеграмда жазу",
        "btn_ok_skipped": "Жарайды, өткізіп жібердім.",
        "order_type_ugc_only": "🎥 Бренд үшін UGC-бейне",
        "order_type_ugc_placement": "📢 UGC + креаторда орналастыру",
        "order_photo_add": "📷 Фото қосу",
        "order_photo_skip": "⏭ Өткізіп жіберу",
        "coop_barter": "🎁 Бартер",
        "coop_payment": "💰 Төлем",
        "coop_both": "🔄 Бартер + төлем",
        "content_social": "📱 Бренд әлеуметтік желілерінде",
        "content_ads": "📢 Жарнамада (таргет, жарнамалар)",
        "content_both": "🔄 Әлеуметтік желілерде және жарнамада",
        "deadlines_3": "⏱ 3 күнге дейін",
        "deadlines_7": "⏱ 7 күнге дейін",
        "deadlines_14": "⏱ 14 күнге дейін",
        "msg_user_not_found": "Пайдаланушы табылмады.",
        "msg_user_not_found_start": "Пайдаланушы табылмады. /start бастаңыз.",
        "msg_registration_blocked": "Блокталған пайдаланушылар тіркеле алмайды.",
        "msg_registration_pause": "Паузадағы пайдаланушылар тіркеле алмайды.",
        "msg_instagram_blocked": "Блокталғандар аккаунтты растай алмайды.",
        "msg_instagram_pause": "Паузадағылар растай алмайды.",
        "msg_complaint_blocked": "Блокталған пайдаланушылар шағымдана алмайды.",
        "msg_complaint_pause": "Паузадағы пайдаланушылар шағымдана алмайды.",
        "msg_order_creation_blocked": "Блокталғандар тапсырыс жасай алмайды.",
        "msg_order_creation_pause": "Паузадағылар тапсырыс жасай алмайды.",
        "msg_payment_blocked": "Блокталған пайдаланушылар тапсырыс төлей алмайды.",
        "msg_payment_pause": "Паузадағы пайдаланушылар төлей алмайды.",
        "msg_feedback_blocked": "Блокталған пайдаланушылар пікір қалдыра алмайды.",
        "msg_feedback_pause": "Паузадағы пайдаланушылар пікір қалдыра алмайды.",
        "msg_feedback_rate_blocked": "Блокталған пайдаланушылар бағалай алмайды.",
        "msg_feedback_rate_pause": "Паузадағы пайдаланушылар бағалай алмайды.",
        "msg_fb_thanks_saved": "Рақмет, жауап сақталды.",
        "msg_fb_thanks_feedback": "Кері байланыс үшін рақмет.",
        "msg_fb_interaction_not_found": "Әрекеттесу табылмады.",
        "msg_fb_insufficient_rights": "Жеткілікті құқық жоқ.",
        "msg_fb_no_deal_question_blog": "Келісімге неге жете алмадыңыз?",
        "msg_fb_no_deal_question_adv": "Келісімге неге жете алмадыңыз?",
        "msg_fb_thanks_short": "Рақмет.",
        "msg_fb_issue_prompt": (
            "Мәселені сипаттаңыз және сөйлесу скриншоттарын немесе "
            "басқа дәлелдерді қосыңыз. Бұл анықтауға көмектеседі.\n"
            "👉 Мәтінді жазыңыз, фото қосыңыз және «Жіберу» батырмасын басыңыз."
        ),
        "msg_fb_postpone_max": (
            "Максималды кейінге қалдыруға жетті. "
            "Күйі «Келісім жоқ» деп белгіленді."
        ),
        "msg_fb_postpone_72": "Тексеру 72 сағатқа кейінге қалдырылды. Кейінге қалдыру: {cnt}/{max_cnt}",
        "msg_fb_postpone_ok_blog": (
            "Жарайды, кейінірек ораламыз 👍 "
            "Егер жарнама беруші хабарласа — жауап беріңіз."
        ),
        "msg_fb_postpone_ok_adv": (
            "Түсінікті, кейінірек ораламыз 👍\n"
            "ℹ️ Креатор контактілерді көрмейді. "
            "Байланыс сізден басталады."
        ),
        "msg_fb_ok_blog": (
            "Кері байланыс үшін рақмет 👍 "
            "Көмек керек болса — біз қолдау көрсетеміз."
        ),
        "msg_fb_ok_adv": (
            "Кері байланыс үшін рақмет 👍 Креатормен сәтті жұмыс тілейміз."
        ),
        "msg_fb_invalid_format": "Қате формат.",
        "msg_fb_invalid_response": "Қате жауап форматы.",
        "msg_fb_invalid_status": "Қате күй.",
        "msg_fb_invalid_id": "Қате идентификатор.",
        "msg_fb_error_try_later": "Қате орын алды. Кейінірек қайталаңыз.",
        "msg_fb_no_deal_other_prompt": "Себепті жазыңыз:",
        "msg_fb_enter_reason_text": "Себепті мәтінмен енгізіңіз.",
        "msg_fb_session_expired": "Сессия аяқталды. Кері байланыс сұрағына қайта жауап беріңіз.",
        "msg_fb_session_expired_nps": "Сессия аяқталды. Бағалау сұрағына қайта жауап беріңіз.",
        "msg_fb_error_try_again": "Қате. Қайталаңыз.",
        "msg_fb_add_description_photo": "Сипаттама немесе фото қосыңыз, содан кейін «Жіберу» басыңыз.",
        "msg_fb_add_description_before_send": "Жіберу алдында сипаттама немесе фото қосыңыз.",
        "msg_fb_complaint_error": (
            "Өтінім жасау кезінде қате орын алды. Қайталаңыз "
            "немесе меню арқылы қолдауға хабарласыңыз."
        ),
        "msg_fb_complaint_accepted": (
            "Өтініміңізді қабылдадық. Қолдау жағдайды анықтайды. "
            "Қажет болса менюде «Қолдау» батырмасын басыңыз."
        ),
        "msg_fb_nps_done_btn": "Дайын",
        "msg_fb_nps_thank": (
            "Рақмет! 🙌\n"
            "Пікіріңіз сақталды, ол UMC платформасын жақсартуға көмектеседі 🙏"
        ),
        "msg_fb_nps_question": "UMC платформасымен жұмысты 1-ден 5-ке бағалаңыз ⭐",
        "msg_fb_nps_prompt_5_adv": (
            "5 ⭐ бағасы үшін рақмет — платформамен жұмыс ыңғайлы болғанына қуаныштымыз! 🙌\n"
            "Сервисті одан ыңғайлы ету идеяларыңыз (интерфейс, креатор таңдау, "
            "хабарландырулар т.б.) болса — жауапта жазыңыз.\n"
            "Платформаны дамыту бойынша әр ұсынысты оқып шығамыз."
        ),
        "msg_fb_nps_prompt_5_blog": (
            "5 ⭐ бағасы үшін рақмет — UMC арқылы жарнама берушілермен жұмыс ыңғайлы болғанына қуаныштымыз! 🙌\n"
            "Сервисті жақсарту идеяларыңыз (жеке кабинет, тапсырыс таңдау, "
            "шарттар, қолдау) болса — жауапта жазыңыз.\n"
            "Платформаны дамыту бойынша әр ұсынысты оқып шығамыз."
        ),
        "msg_fb_nps_prompt_34_adv": (
            "Бағаңыз үшін рақмет 🙏\n"
            "UMC-мен жұмыста не жақсартуға болатынын білу маңызды.\n"
            "Бір хабарламада жазыңыз:\n"
            "– не ұнамады (таңдау, жылдамдық, интерфейс, коммуникация)."
        ),
        "msg_fb_nps_prompt_34_blog": (
            "Бағаңыз үшін рақмет 🙏\n"
            "UMC арқылы тапсырыстармен жұмыста не жақсартуға болатынын білу маңызды.\n"
            "Бір хабарламада жазыңыз:\n"
            "– не қиын немесе ыңғайсыз болды (шарттар, жарнама берушімен сөйлесу, "
            "интерфейс, хабарландырулар т.б.)."
        ),
        "msg_fb_nps_prompt_1_adv": (
            "Шынайы 1 ⭐ үшін рақмет — бізге білу маңызды 🙏\n"
            "UMC платформасымен тәжірибе жағымсыз болғанына өкінеміз.\n"
            "Бір хабарламада не болмағанын сипаттаңыз:\n"
            "– креатормен мәселелер;\n"
            "– платформа қиындықтары;\n"
            "– қателер, кідірістер, түсінбеушілік т.б.\n"
            "Жағдайды мұқият қарастырамыз."
        ),
        "msg_fb_nps_prompt_1_blog": (
            "Шынайы 1 ⭐ үшін рақмет — бізге білу маңызды 🙏\n"
            "UMC арқылы тәжірибе жағымсыз болғанына өкінеміз.\n"
            "Бір хабарламада не болғанын сипаттаңыз:\n"
            "– жарнама берушімен мәселелер;\n"
            "– шарттар қиындығы;\n"
            "– платформа техникалық мәселелері;\n"
            "– басқа сәттер.\n"
            "Жағдайды мұқият қарастырамыз."
        ),
        "msg_fb_issue_send_btn": "📤 Жіберу",
        "msg_fb_feedback_ok": "✅ Барлығы қалыпты өтті",
        "msg_fb_feedback_no_deal": "❌ Келісім жоқ",
        "msg_fb_feedback_postpone": "⏳ Әлі хабарласқан жоқ",
        "msg_fb_feedback_issue": "⚠️ Мәселе / алаяқтық күдігі",
        "msg_fb_no_deal_conditions": "💰 Шарттар бойынша келісе алмадық",
        "msg_fb_no_deal_timing": "⏱ Мерзімдер сәйкес келмеді",
        "msg_fb_no_deal_differed": "📝 Шарттар офферден өзгеше болды",
        "msg_fb_no_deal_creator_change": "📝 Креатор шарттарды өзгертуді қалады",
        "msg_fb_no_deal_other": "🤝 Басқа",
        "msg_fb_score_1_to_5": "Баға 1-ден 5-ке дейін болуы керек.",
        "msg_fb_thanks_for_rating": "Бағаңыз үшін рақмет!",
        "msg_fb_no_description": "Сипаттамасыз",
        "msg_feedback_request_adv": (
            "Барлығы қалыпты өткенін тексергіміз келеді 🙌\n"
            "Креатормен байланысқа түсе алдыңыз ба{creator_link}?\n"
            "Сәйкес нұсқаны таңдаңыз:"
        ),
        "msg_feedback_request_blog": (
            "Барлығы қалыпты өткенін тексергіміз келеді 🙌\n"
            "Жарнама берушімен байланысқа түсе алдыңыз ба {order_link_part}"
        ),
        "msg_choose_role": "Рөлді /role арқылы таңдаңыз.",
        "msg_fill_profile_orders": (
            "Тапсырыстарды көру үшін профильді толтырыңыз (/advertiser немесе /creator)."
        ),
        "msg_confirm_agreement": ("Платформа құжаттарымен келісімді растаңыз."),
        "msg_agreements_intro_default": (
            "Профиль жасалды. Құжаттармен танысып, растаңыз."
        ),
        "msg_label_offer": "📄 Оферта",
        "msg_label_privacy": "🔒 Құпиялылық саясаты",
        "msg_label_consent": "🧾 Жеке деректерді өңдеуге келісім",
        "msg_confirm_docs_fallback": (
            "Платформа құжаттарымен келісімді растаңыз."
        ),
        "msg_no_orders": "Тапсырыстарыңыз әлі жоқ. /create_order",
        "msg_no_blogger_orders": (
            "Сіз әлі жауап бермедіңіз. Ұсыныстар ботқа келеді."
        ),
        "msg_blogger_profile_empty": "Блогер профилі толтырылмаған.",
        "msg_advertiser_profile_empty": "Жарнама беруші профилі толтырылмаған.",
        "msg_advertiser_profile_fill": (
            "Жарнама беруші профилі толтырылмаған. Команда: /advertiser"
        ),
        "msg_creator_profile_fill": "Профиль толтырылмаған. Команда: /creator",
        "msg_confirm_instagram_first": "Жауап беру алдында Instagram растаңыз.",
        "msg_confirm_agreement_first": "Алдымен келісімді растаңыз.",
        "msg_invalid_order_amount": "Тапсырыс сомасы қате.",
        "msg_order_amount_too_large": (
            "Telegram шот-фактурасы үшін тапсырыс сомасы тым үлкен."
        ),
        "msg_invoice_failed": "Шот-фактура жасау мүмкін болмады. Кейінірек қайталаңыз.",
        "msg_pay_order_usage": "Пайдалану: /pay_order <order_id>",
        "msg_invalid_order_id": "order_id форматы қате.",
        "msg_invalid_order_format": "Тапсырыс форматы қате.",
        "msg_order_not_found": "Тапсырыс табылмады.",
        "msg_order_not_yours": "Тапсырыс жарнама берушіге тиесілі емес.",
        "msg_order_not_new": "Тапсырыс NEW күйінде емес.",
        "msg_pricing_not_configured": (
            "Қол жетімділік құны бапталмаған. Қолдауға хабарласыңыз."
        ),
        "msg_payment_provider_not_configured": (
            "Төлем провайдері бапталмаған."
        ),
        "msg_order_undetermined": "Тапсырысты анықтау мүмкін болмады.",
        "msg_title_payment": "Тапсырыс төлемі",
        "msg_referral_payout_today": "Сіз бүгін төлем сұрағыңызды жібердіңіз.",
        "msg_referral_payout_unavailable": (
            "Төлем қол жетімсіз: баланс жоқ немесе сұрау бар."
        ),
        "msg_referral_payout_sent": "Төлем сұрағы қолдауға жіберілді.",
        "msg_referral_payout_notify_failed": (
            "Сұрау жасалды, бірақ қолдауды хабарлау мүмкін болмады. "
            "Қолдауға қолмен хабарласыңыз."
        ),
        "msg_referral_payout_blocked": "Төлем сұрай алмайсыз.",
        "msg_referral_payout_pause": "Паузадағы пайдаланушылар төлем сұрай алмайды.",
        "msg_referral_no_users": "Әлі алынған пайдаланушылар жоқ.",
        "msg_referral_access_denied": "Қол жетімсіз.",
        "msg_referral_blocked": "Блокталғандар бұл команданы пайдалана алмайды.",
        "msg_referral_pause": "Паузадағы пайдаланушылар команданы пайдалана алмайды.",
        "msg_referral_list_blocked": "Блокталғандар тізімді көре алмайды.",
        "msg_referral_list_pause": "Паузадағы пайдаланушылар тізімді көре алмайды.",
        "msg_referral_list_title": (
            "Сіздің рефералдарыңыз (бет {page}/{total_pages}):"
        ),
        "msg_referral_list_empty": "Рефералдарыңыз: әлі ешкім жоқ.",
        "msg_referral_pending_block": (
            "Креатор профилін толтырмаған (толтыруды еске салыңыз):"
        ),
        "msg_referral_no_pending": "Профилісіз рефералдар жоқ.",
        "msg_referral_link_intro": "Сіздің реферал сілтемеңіз:",
        "lbl_referral_stats": "📊 Реферал статистикасы",
        "lbl_referral_creators": "Алынған креаторлар",
        "lbl_referral_orders": "Орындалған тапсырыстар",
        "lbl_referral_income_month": "Ағымдағы айдың табысы",
        "lbl_referral_income_total": "Жиналған (барлығы)",
        "lbl_referral_paid": "Төленген",
        "lbl_referral_balance": "Ағымдағы баланс",
        "lbl_referral_orders_done": "тапсырыс орындалды",
        "msg_offer_new_response": (
            "Тапсырысыңызға жаңа жауап 🙌\n\n"
            "👤 Креатор: {creator}\n"
            "📍 Қала: {city}\n"
            "🎬 Формат: {format}\n"
            "💼 Оффер шарттарында жұмыс жасауға дайын\n"
            "🔗 Креатор профилі:\n{profile_url}"
        ),
        "lbl_creator_fallback": "Креатор",
        "lbl_phone_dash": "Телефон: —",
        "lbl_telegram_dash": "Telegram: —",
        "msg_offer_contacts_header": "📞 Байланыс үшін жарнама беруші контактілері:\n\n",
        "msg_advertiser_new_response_what_next": (
            "🔔 Келесі қадам\n\n"
            "💬 Креаторға жазыңыз және детальдарды талқылаңыз\n"
            "✅ Креатор оффермен танысып, көрсетілген шарттарда жұмыс жасауға дайын\n"
            "⏱ 30 мин ішінде байланысқа түсуді ұсынамыз\n\n"
            "⚠️ Еске алу\n\n"
            "🧷 Оффер шарттарын өзгерту ұсынылмайды\n"
            "🔄 Шарттар өзгерсе креатор ынтымақтастан бас тарта алады\n"
            "➡️ Байланыс әрқашан сізден басталады"
        ),
        "msg_offer_response_blocked": "Блокталған пайдаланушылар офферге жауап бере алмайды.",
        "msg_offer_response_pause": "Паузадағы пайдаланушылар офферге жауап бере алмайды.",
        "msg_advertiser_contacts_warning": (
            "⚠️ **Креаторлармен қауіпсіз жұмыс тәртібі:**\n\n"
            "• Платформа алдын ала төлемді ұсынбайды\n"
            "• Су таңбасы бар превью алғаннан кейін төлеңіз\n"
            "• Соңғы төлем алдында контент сапасын тексеріңіз\n"
            "• Келіссөздер мен келісімдер — сіз бен креатор арасында"
        ),
        "msg_my_orders_blocked": "Блокталғандар тапсырыстарды көре алмайды.",
        "msg_my_orders_pause": "Паузадағылар тапсырыстарды көре алмайды.",
        "msg_orders_title": "Тапсырыстарыңыз (бет {page}/{total_pages}):",
        "msg_orders_blogger_title": (
            "Жауап берген тапсырыстарыңыз (бет {page}/{total_pages}):"
        ),
        "msg_order_status": "Күйі: {status_label}",
        "msg_order_creators": "Креаторлар: {bloggers_needed}",
        "msg_order_matched": "Таңдалды: {matched_count} / {bloggers_needed}",
        "msg_order_date_created": "Жасалған күні: {date}",
        "msg_order_date_completed": "Аяқталған күні: {date}",
        "msg_order_link": "Жоба сілтемесі: {link}",
        "msg_order_format": "Формат: {order_type}",
        "msg_order_type_ugc": "Бренд үшін UGC-бейне",
        "msg_order_type_placement": "UGC + орналастыру",
        "msg_order_price": "1 UGC бағасы: {price}",
        "msg_order_barter": "Бартер: {desc}",
        "msg_status_new": "Жасалды",
        "msg_status_pending_moderation": "Модерацияда",
        "msg_status_active": "Белсенді",
        "msg_status_closed": "Аяқталды",
        "msg_choose_city": "Қаланы тізімнен таңдаңыз.",
        "msg_choose_city_or_type": (
            "Ең жақын қаланы көрсетіңіз немесе «Қаланы таңдау» басыңыз"
        ),
        "msg_city_multiple_regions": (
            "Бұл қала бірнеше аймақта бар. Аймақты таңдаңыз:"
        ),
        "msg_session_expired": "Сессия аяқталды. Қайта бастаңыз.",
        "msg_session_expired_orders": (
            "Сессия аяқталды. «Тапсырыс жасау» арқылы қайта бастаңыз."
        ),
        "msg_session_expired_profile": (
            "Сессия аяқталды. «Менің профилім» қайта ашыңыз."
        ),
        "msg_profile_not_found": "Профиль табылмады.",
        "msg_profile_not_found_role": "Профиль табылмады. Рөлді /role арқылы таңдаңыз.",
        "msg_profile_incomplete": "Профиль толтырылмаған.",
        "msg_choose_profile_edit": "Өзгерту үшін профильді таңдаңыз:",
        "msg_choose_section_edit": "Өзгерту үшін бөлімді таңдаңыз:",
        "msg_choose_section_keyboard": "Клавиатурадағы бөлімдердің бірін таңдаңыз.",
        "msg_profile_updated": "Профиль жаңартылды.",
        "msg_advertiser_profile_not_found": "Жарнама беруші профилі табылмады.",
        "msg_unknown_field": "Белгісіз өріс.",
        "msg_profile_update_failed": "Профильді жаңарту мүмкін болмады.",
        "err_city_not_place_use_map": (
            "Профильді жаңарту мүмкін болмады. Картада орналасуыңызды көрсетіңіз "
            "немесе геолокацияны бөлісіңіз."
        ),
        "err_instagram_format_example": "Қате сілтеме форматы. Мысал: instagram.com/name",
        "err_instagram_invalid": "Instagram сілтеме форматы қате.",
        "err_instagram_taken": "Бұл Instagram әлі тіркелген. Басқасын пайдаланыңыз.",
        "msg_city_picker_edit": (
            "Ең жақын қаланы енгізіңіз немесе «Қаланы таңдау» басып тізімнен таңдаңыз."
        ),
        "msg_choose_buttons": "Батырмалардың бірін таңдаңыз.",
        "msg_name_updated": "Аты жаңартылды.",
        "lbl_profile_your": "👤 Сіздің профиліңіз",
        "lbl_profile_general": "📋 Жалпы ақпарат",
        "lbl_profile_name": "Аты",
        "lbl_profile_roles": "Рөлдер",
        "lbl_profile_status": "Күйі",
        "lbl_profile_blogger": "📸 Блогер профилі",
        "lbl_profile_not_filled": "Толтырылмаған",
        "lbl_profile_advertiser": "🏢 Жарнама беруші профилі",
        "lbl_status_new": "Жаңа",
        "lbl_status_active": "Белсенді",
        "lbl_status_pause": "Паузада",
        "lbl_status_blocked": "Блокталған",
        "lbl_audience_male": "Ерлер",
        "lbl_audience_female": "Әйелдер",
        "lbl_audience_all": "Барлығы",
        "lbl_blogger_gender_male": "Ер",
        "lbl_blogger_gender_female": "Әйел",
        "lbl_role_blogger": "Креатор",
        "lbl_role_advertiser": "Жарнама беруші",
        "lbl_yes": "Иә",
        "lbl_no": "Жоқ",
        "lbl_work_format_ads": "Жарнаманы өз аккаунтымда орналастыру",
        "lbl_work_format_ugc": "Тек UGC",
        "lbl_instagram": "Instagram",
        "lbl_confirmed": "Расталған",
        "lbl_city": "Қала",
        "lbl_country": "Ел",
        "lbl_region": "Аймақ",
        "lbl_gender": "Жыныс",
        "lbl_birth_date": "Туған күні",
        "lbl_topics": "Тақырыптар",
        "lbl_audience": "Мақсатты аудитория",
        "lbl_geo": "География",
        "lbl_price": "Баға",
        "lbl_barter": "Бартер",
        "lbl_work_format": "Жұмыс форматы",
        "lbl_phone": "Телефон",
        "lbl_brand": "Бренд",
        "lbl_activity": "Қызмет",
        "lbl_site": "Сайт",
        "lbl_years": "жас",
        "prompt_edit_nickname": "Жаңа атыңызды енгізіңіз:",
        "prompt_edit_instagram_url": "instagram.com/name сілтемесін қосыңыз:",
        "prompt_edit_city": "Қай қаладансыз?",
        "prompt_edit_blogger_gender": "Жынысыңызды көрсетіңіз:",
        "prompt_edit_birth_date": "Туған күнін КК.АА.ЖЖЖЖ форматында (мысалы 15.05.1995):",
        "prompt_edit_topics": "1–3 тақырыпты үтірмен жазыңыз:",
        "prompt_edit_audience_gender": "Контентіңізді негізінен кім көреді?",
        "prompt_edit_audience_age": "Аудиторияңыздың негізгі жасы?",
        "prompt_edit_audience_geo": "Үтірмен 3 қалаға дейін көрсетіңіз:",
        "prompt_edit_price": "1 UGC-бейне бағасы ({currency}):",
        "prompt_edit_barter": "Бартер бойынша жұмыс жасауға дайынсыз ба?",
        "prompt_edit_work_format": "Брендтермен қалай жұмыс жасайсыз?",
        "prompt_edit_name": "Атыңызды енгізіңіз:",
        "prompt_edit_phone": "Байланыс үшін телефон нөмірін көрсетіңіз. Мысал: 89001110777",
        "prompt_edit_brand": "Бренд / компания / бизнес атауыңыз:",
        "prompt_edit_site_link": "Сайт, өнім немесе бренд әлеуметтік желілеріне сілтеме:",
        "prompt_edit_generic": "Жаңа мәнді енгізіңіз:",
        "lbl_edit_nickname": "Аты",
        "lbl_edit_instagram": "Instagram",
        "lbl_edit_city": "Қала",
        "lbl_edit_blogger_gender": "Жыныс",
        "lbl_edit_birth_date": "Туған күні",
        "lbl_edit_topics": "Тақырыптар",
        "lbl_edit_audience_gender": "Аудитория жынысы",
        "lbl_edit_audience_age": "Аудитория жасы",
        "lbl_edit_audience_geo": "Аудитория географиясы",
        "lbl_edit_price": "Баға",
        "lbl_edit_barter": "Бартер",
        "lbl_edit_work_format": "Жұмыс форматы",
        "lbl_edit_name": "Аты",
        "lbl_edit_phone": "Телефон",
        "lbl_edit_brand": "Бренд",
        "lbl_edit_company_activity": "Компания қызметі",
        "lbl_edit_site_link": "Сайт сілтемесі",
        "msg_whats_your_name": "Сіздің атыңыз кім?",
        "msg_choose_action": "Әрекетті таңдаңыз:",
        "msg_what_city": "Қай қаладансыз?\nМысал: Астана / Алматы / Шымкент",
        "msg_brand_name": "Бренд / компания / бизнес атауыңыз:",
        "msg_company_activity": "Компанияңыз қандай қызмет атқарады?",
        "msg_brand_link": "Сайт, өнім немесе бренд әлеуметтік желілеріне сілтеме:",
        "msg_after_registration": (
            "Енді тапсырыс орналастырып UGC-креаторларды таба аласыз."
        ),
        "msg_advertiser_intro": (
            "«Маған UGC‑креаторлар керек» рөлін таңдадыңыз.\n"
            "Тапсырыс орналастыру үшін профиль жасайық."
        ),
        "msg_creator_intro": (
            "Сіз UGC‑креаторсыз. Заказчитер креаторларды осында іздейді — толық профиль "
            "таңдауға кіруге және сәйкес тапсырыс алуға көмектеседі.\n\n"
            "Бірнеше минутта профильді толтырыңыз — және таңдауда боласыз."
        ),
        "msg_step_ask_name": "Сіздің атыңыз кім?\n\n12-нің 1-қадамы",
        "msg_step_ask_instagram": "instagram.com/name форматында сілтеме жіберіңіз\n\n12-нің 2-қадамы",
        "msg_step_ask_instagram_first": "instagram.com/name форматында сілтеме жіберіңіз\n\n12-нің 1-қадамы",
        "msg_step_ask_city": (
            "Заказчитер креаторларды қала бойынша таңдайды: өнім жеткізу және офлайн әрекеттесу үшін. "
            "Қай қаладансыз?\n\n12-нің 3-қадамы"
        ),
        "msg_step_ask_birth_date": (
            "Туған күнін КК.АА.ЖЖЖЖ форматында көрсетіңіз (мысалы 15.05.1995):\n\n12-нің 4-қадамы"
        ),
        "msg_step_ask_gender": "Жынысыңызды көрсетіңіз:\n\n12-нің 5-қадамы",
        "msg_step_ask_topics": (
            "Контентіңіз не туралы?\n"
            "1–5 тақырыпты үтірмен жазыңыз: бизнес, инвестиция, фитнес, "
            "тамақтану, сұлулық, тері күтімі, саяхат, тағам, ресторандар, сән, "
            "стиль, балалар, отбасы, технологиялар, гаджеттер, лайфстайл, іс-шаралар, т.б.\n\n12-нің 6-қадамы"
        ),
        "msg_step_ask_audience_gender": (
            "Контентіңізді негізінен кім көреді? Бақылау бойынша немесе статистика\n\n12-нің 7-қадамы"
        ),
        "msg_step_ask_audience_age": "Аудиторияңыздың негізгі жасы?\n\n12-нің 8-қадамы",
        "msg_step_ask_audience_geo": (
            "Аудитория негізінен қай қалаларда? Үтірмен 3 қалаға дейін, "
            "мысалы: Астана, Алматы, Шымкент\n\n12-нің 9-қадамы"
        ),
        "msg_step_ask_price": (
            "Заказчитер бюджет бойынша таңдайды — көрсетілген баға келісімді жеделдетеді. "
            "Бір UGC‑бейне қанша тұрады? Баға ({currency}), мысалы: 500, 1000, 2000\n\n12-нің 10-қадамы"
        ),
        "msg_step_ask_barter": (
            "Көп тапсырыс бартермен — «Иә» жауабы офферлер санын арттырады. "
            "Кейде брендтермен бартер бойынша жұмыс жасауға дайынсыз ба?\n\n12-нің 11-қадамы"
        ),
        "msg_step_ask_work_format": (
            "UGC-дан басқа брендтермен қалай жұмыс жасайсыз? "
            "Таңдау алдындағы соңғы қадам.\n\n12-нің 12-қадамы"
        ),
        "msg_agreements_intro_creator": (
            "Іс жүзінде дайын. Құжаттармен танысып, келісімді растаңыз."
        ),
        "msg_profile_created": (
            "Профиль жасалды 👍\n\n"
            "Заказчитер креаторларды іздейді — толтырылған профиль оффер алу мүмкіндігін "
            "арттырады.\n\n"
            "Соңғы қадам — Instagram‑аккаунтты растау. Бұл керек:\n"
            "— брендтерді фейктерден қорғау үшін\n"
            "— профильге сенімді арттыру үшін\n"
            "— тапсырыстарды тезірек алу үшін"
        ),
        "msg_instagram_already_registered": (
            "Бұл Instagram аккаунты әлі тіркелген. "
            "Басқа аккаунт пайдаланыңыз немесе қолдауға хабарласыңыз."
        ),
        "msg_work_format_choose": (
            "Батырмалардың бірін таңдаңыз: Жарнаманы өз аккаунтымда орналастыру "
            "немесе Тек UGC (орналастырусыз)."
        ),
        "msg_registration_aborted": (
            "Тіркеу үзілді. Аяқтау үшін «Менің профилім» ашып келісімді растаңыз."
        ),
        "err_instagram_empty": (
            "Сілтеме бос болмайды. instagram.com/name форматында сілтеме жіберіңіз"
        ),
        "err_instagram_format": "Қате формат. instagram.com/name тәрізді сілтеме керек",
        "err_instagram_example": (
            "Instagram сілтеме форматы қате. Мысал: https://instagram.com/name"
        ),
        "err_gender_choose": "Батырмалардың бірін таңдаңыз: Ер немесе Әйел.",
        "err_audience_choose": (
            "Таңдаңыз: Негізінен әйелдер, ерлер немесе Аралас."
        ),
        "err_age_choose": "Жас батырмаларының бірін таңдаңыз.",
        "err_barter_choose": "Иә немесе Жоқ таңдаңыз.",
        "err_price_number": "Санды енгізіңіз, мысалы 500, 1000, 2000.",
        "err_geo_max_cities": "Үтірмен 3 қаладан аспай көрсетіңіз.",
        "err_not_bot_command": (
            "Бот командаларын жауап ретінде пайдаланбаңыз. Мәтінді қайта енгізіңіз."
        ),
        "err_offer_text_min": "Тапсырманы толығырақ сипаттаңыз (мин {min} таңба).",
        "err_offer_text_max": "Мәтін тым ұзын (макс {max} таңба).",
        "err_barter_required": "Бартер ұсынысын сипаттаңыз.",
        "err_barter_min": "Бартерді сипаттаңыз (мин {min} таңба).",
        "err_barter_max": "Мәтін ұзын (макс {max} таңба).",
        "err_url_max": "Сілтеме тым ұзын (макс {max} таңба).",
        "err_url_scheme": "Сілтемені енгізіңіз (http:// немесе https://).",
        "err_url_invalid": "Дұрыс сілтемені енгізіңіз.",
        "err_url_example": (
            "Дұрыс сілтемені енгізіңіз (мысалы, site.kz немесе example.com)."
        ),
        "err_product_link_empty": "Сілтеме бос болмайды. Қайта енгізіңіз:",
        "err_geo_required": (
            "Бір нұсқаны көрсетіңіз: қала, аймақ немесе ел. "
            "Мысалдар: Астана, Алматы, Қазақстан"
        ),
        "err_geo_max": "Мәтін тым ұзын (макс {max} таңба).",
        "err_min_chars": "Кем дегенде {min} таңба енгізіңіз.",
        "err_max_chars": "Макс {max} таңба.",
        "err_phone_empty": "Телефон нөмірі бос болмайды. Қайта енгізіңіз:",
        "err_phone_digits": (
            "Дұрыс нөмірді енгізіңіз (10–11 сан). Мысал: 89001110777"
        ),
        "err_phone_too_many": "Тым көп сан. Мысал: 89001110777",
        "err_phone_invalid": "Дұрыс нөмірді енгізіңіз. Мысал: 89001110777",
        "err_birth_date_empty": (
            "Туған күнін КК.АА.ЖЖЖЖ форматында енгізіңіз (мысалы 15.05.1995)."
        ),
        "err_birth_date_format": (
            "Қате формат. КК.АА.ЖЖЖЖ пайдаланыңыз (мысалы 15.05.1995)."
        ),
        "err_birth_date_digits": (
            "КК.АА.ЖЖЖЖ форматында сандармен күнді енгізіңіз (мысалы 15.05.1995)."
        ),
        "err_birth_date_invalid": "Қате күн. Күн, ай және жылды тексеріңіз.",
        "err_birth_date_future": "Туған күні болашақта болмайды.",
        "err_birth_date_min_age": "Жас кем дегенде {age} жас болуы керек.",
        "err_birth_date_max_age": (
            "Нақты туған күнін көрсетіңіз ({age} жасқа дейін)."
        ),
        "err_city_required": "Қаланы көрсетіңіз. Қайта енгізіңіз:",
        "err_city_from_location": "Геопозиция бойынша қаланы анықтау мүмкін болмады. Қолмен қаланы енгізіңіз немесе қайталаңыз.",
        "err_city_not_found_use_map": (
            "Атау бойынша орналасуды анықтау мүмкін болмады. "
            "Нақты қала атауын енгізіңіз немесе геолокацияны жіберіңіз."
        ),
        "err_company_activity_max": "Макс {max} таңба.",
        "err_nickname_no_url": "Атыңызды енгізіңіз, Instagram сілтемесін емес.",
        "err_topics_empty": "Кем дегенде бір тақырыпты енгізіңіз:",
        "err_topics_max": "{max} тақырыптан аспай көрсетіңіз.",
        "err_audience_geo_empty": "Кем дегенде бір қаланы көрсетіңіз. Қайта енгізіңіз:",
        "err_audience_geo_max": "Макс {max} таңба.",
        "err_price_positive": "Баға 0-ден үлкен болуы керек.",
        "err_price_max": (
            "Сома рұқсат етілген максимумнан асады ({max} {currency})."
        ),
        "msg_what_do_you_need": "Сізге не керек?",
        "msg_choose_from_keyboard": "Клавиатурадағы нұсқалардың бірін таңдаңыз.",
        "msg_coop_format": "Қандай ынтымақтастық форматы сізге сәйкес?",
        "msg_enter_number": "Санды енгізіңіз, мысалы 1500.",
        "msg_how_many_creators": "Сізге қанша креатор керек?",
        "msg_product_link": "Өнім сілтемесін енгізіңіз (жауап берген креаторлар үшін):",
        "msg_choose_count": "Мәндердің бірін таңдаңыз: {counts}.",
        "msg_where_use_ugc": "UGC-бейнені қайда пайдалануды жоспарлайсыз?",
        "msg_send_photo": "Өнім фотосын жіберіңіз:",
        "msg_order_task_description": (
            "Креаторлар үшін тапсырманы қысқаша сипаттаңыз.\n"
            "Не түсіру керек және қандай форматта. Мысал: Ашудың бейнесі."
        ),
        "msg_order_budget": (
            "1 UGC-бейнеге бюджет? Бағаны көрсетіңіз ({currency}): 500, 1000, 2000"
        ),
        "msg_order_barter_ask": (
            "Бартер бойынша не ұсынасыз?\n"
            "Бренд өнімі (қысқа сипаттама) + жеткізу"
        ),
        "msg_order_photo_intro": (
            "Фото қосыңыз (қаласаңыз).\n"
            "Фото креаторға тапсырысты тезірек түсінуге және жауапты "
            "арттыруға көмектеседі."
        ),
        "msg_order_photo_choose": (
            "Клавиатурада «Фото қосу» немесе «Өткізіп жіберу» таңдаңыз, "
            "немесе өнім фотосын жіберіңіз."
        ),
        "msg_order_deadline": (
            "Контент қай мерзімде керек? "
            "Келісімнен кейін қанша күннен кейін превью күтетініңізді көрсетіңіз."
        ),
        "msg_order_geo": (
            "Креатор қай қалада, аймақта немесе елде болуы мүмкін? "
            "Бір нұсқаны көрсетіңіз: мысалы Астана, Алматы, Қазақстан. "
            "Бартер тапсырыстары және өнім жеткізу үшін қажет."
        ),
        "msg_profile_empty_creator": (
            "Профиль толтырылмаған. «Профиль жасау» немесе /creator"
        ),
        "msg_instagram_already_confirmed": "Instagram‑аккаунтыңыз әлі расталған",
        "msg_instagram_verify_instruction": (
            "<b>Instagram‑аккаунтыңызды растау үшін 3 қадамды орындаңыз:</b>\n\n"
            "1. Төмендегі коды көшіріңіз\n"
            "2. Оны UMC Instagram тіркелгісіне жеке хабарламада жіберіңіз\n"
            "3. Автоматты растауды күтіңіз\n\n"
            '🔗 Instagram UMC: <a href="{url}">{url}</a>\n\n'
            "🔐 Сіздің кодыңыз (15 минутқа жарамды) 👇"
        ),
        "msg_invalid_format": "Қате формат.",
        "msg_invalid_id_format": "Идентификатор форматы қате.",
        "msg_order_not_found_short": "Тапсырыс табылмады.",
        "msg_no_bloggers_complain": "Шағымдануға блогерлер жоқ.",
        "msg_complain_on": "{blogger_name} туралы шағымдану",
        "msg_choose_blogger_complain": ("Шағымдануға блогерді таңдаңыз:"),
        "msg_no_access_order": "Бұл тапсырысқа қол жетімсіз.",
        "msg_choose_complaint_reason": "Шағым себебін таңдаңыз:",
        "msg_complaint_no_bloggers": "Шағымдануға блогерлер жоқ.",
        "msg_invalid_user_id": "Қате пайдаланушы идентификаторы.",
        "msg_invalid_reason": "Қате себеп.",
        "msg_data_error": "Деректерді өңдеу қатесі.",
        "msg_describe_complaint": "Шағым себебін сипаттаңыз:",
        "msg_error_try_later": "Қате орын алды. Кейінірек қайталаңыз.",
        "msg_enter_complaint_reason": "Шағым себебін енгізіңіз.",
        "msg_order_closed": "Тапсырыс әлі жабық.",
        "msg_order_closed_full": (
            "❗ Тапсырыс жабық\n\n"
            "Жауап бергеніңіз үшін рақмет — бұл тапсырыс бойынша барлық креаторлар таңдалды.\n\n"
            "Жаңа тапсырыстар пайда болғанда жібереміз.\n\n"
            "Боттағы хабарландыруларды қадағалаңыз 🙌"
        ),
        "msg_blogger_after_response_what_next": (
            "⏳ Келесі қадам\n\n"
            "💬 Жарнама берушінің хабарламасын күтіңіз — оған Instagram сілтемесі бар "
            "және ол алдымен жазады\n"
            "📩 Direct сұрауларын тексеріңіз\n"
            "👀 Демо үшін су таңбасы бар превью пайдаланыңыз\n"
            "💸 Превью келісілгеннен кейін төлем алыңыз\n"
            "🎥 Соңғы UGC-роликті тек төлемнен кейін жіберіңіз\n"
            "❗ Жарнама беруші оффер шарттарын өзгертпесе, жауап бергеннен кейін бас тарту "
            "аккаунт шектеуіне әкелуі мүмкін\n"
            "🤝 Платформа келіссөздер мен төлемге қатыспайды."
        ),
        "msg_offer_accepted": "Жауап қабылданды! Жарнама берушінің байланысын күтіңіз.",
        "msg_offer_order_filled": (
            "Ағымдағы креатор таңдауы жабық. Сізді күту тізіміне қостұқ — "
            "егер креаторды ауыстыру қажет болса немесе жарнама беруші таңдауды кеңейтсе, "
            "алдымен сізге ұсыныс жібереміз."
        ),
        "msg_offer_order_filled_toast": "Күту тізіміне қосылды",
        "msg_advertiser_after_payment_success": (
            "Төлем сәтті өтті ✅\n\nТапсырысыңыз бойынша креатор таңдау белсенді."
        ),
        "msg_advertiser_after_payment_what_next": (
            "🔄 **Келесі қадам**\n\n"
            "📩 Креаторлар офферіңізді алады\n"
            "🔗 Олардың профиль сілтемелерімен жауаптар аласыз\n"
            "💬 Таңдалған креаторлармен өзіңіз байланысасыз"
        ),
        "msg_advertiser_after_payment_important": (
            "⚠️ **Маңызды**\n\n"
            "🧷 Оффер шарттарын жариялағаннан кейін өзгерту ұсынылмайды\n"
            "🔄 Шарттар өзгерсе креатор ынтымақтастан бас тарта алады\n"
            "🤝 Платформа келісім тарапы емес\n"
            "💸 Креаторларға төлемді өзіңіз тікелей жасайсыз\n"
            "👀 Су таңбасы бар превью көргеннен кейін төлеңіз\n"
            "🚫 Платформа креаторлар үшін жауапкершілік алмайды"
        ),
        "msg_phone_request": (
            "Тапсырыс бойынша байланыс үшін телефон нөмірін көрсетіңіз.\n"
            "Төмендегі батырманы басыңыз немесе нөмірді қолмен енгізіңіз "
            "(мысалы: 89001110777)."
        ),
        "msg_instagram_confirmed": (
            "Instagram расталды ✅. Брендтер ұсыныс жібере алады."
        ),
        "msg_instagram_mismatch": (
            "Профильде көрсетілген Instagram код жіберген аккаунтпен сәйкес келмейді. "
            "«Менің профилім» ашып, блогер профилін өзгертіп, дұрыс Instagram көрсетіңіз."
        ),
        "msg_too_many_requests": "Тым көп сұрау. Кейінірек қайталаңыз.",
        "msg_invalid_order_id_short": "Қате тапсырыс идентификаторы.",
        "msg_order_activated": "Тапсырыс белсенді, блогерлерге жіберіледі.",
        "err_user_not_found": "Пайдаланушы табылмады.",
        "err_blogger_registration": "Блогер тіркеу қатесі.",
        "err_advertiser_registration": "Жарнама беруші тіркеу қатесі.",
        "err_order_not_found": "Тапсырыс табылмады.",
        "err_order_not_active": "Тапсырыс белсенді емес.",
        "err_order_creation": "Тапсырыс жасау қатесі.",
        "err_order_already_responded": "Бұл тапсырысқа әлі жауап бердіңіз.",
        "err_order_response_limit": "Тапсырыс бойынша жауап лимитіне жеттіңіз.",
        "err_order_not_new": "Тапсырыс NEW күйінде емес.",
        "err_order_not_yours": "Тапсырыс жарнама берушіге тиесілі емес.",
        "err_order_invalid_id": "Қате тапсырыс идентификаторы.",
        "msg_offer_skipped": "Жарайды, өткізіп жібердім.",
        "err_interaction_not_found": "Әрекеттесу табылмады.",
        "err_interaction": "Әрекеттесу қатесі.",
        "err_interaction_status": "Әрекеттесу ISSUE күйінде емес.",
        "err_interaction_resolution": "Қолмен шешім үшін қате күй.",
        "err_complaint_exists": "Бұл тапсырыс бойынша шағым әлі жібердіңіз.",
        "err_complaint_not_found": "Шағым табылмады.",
        "err_price_exceeds": "Сома максимумнан асады ({amount} {currency}).",
        "err_generic": "Қате орын алды: {error}",
        "msg_feedback_thanks": "Рақмет, жауап сақталды.",
        "msg_feedback_thanks_short": "Кері байланыс үшін рақмет.",
        "msg_interaction_not_found": "Әрекеттесу табылмады.",
        "msg_insufficient_rights": "Жеткілікті құқық жоқ.",
        "msg_feedback_thanks_ok": "Рақмет.",
        "msg_describe_problem": (
            "Мәселені сипаттаңыз және сөйлесу скриншоттарын немесе "
            "басқа дәлелдерді қосыңыз. Бұл анықтауға көмектеседі.\n"
        ),
        "msg_postpone_max": "Максималды кейінге қалдыруға жетті. Күйі «Келісім жоқ» деп белгіленді.",
        "msg_postpone_72": "Тексеру 72 сағатқа кейінге қалдырылды. Кейінге қалдыру: {cnt}/{max}",
        "msg_session_expired_feedback": "Сессия аяқталды. Кері байланыс сұрағына қайта жауап беріңіз.",
        "msg_error_try_again": "Қате. Қайталаңыз.",
        "msg_add_description_or_photo": "Сипаттама немесе фото қосыңыз, содан кейін «Жіберу» басыңыз.",
        "msg_add_description_before_send": "Жіберу алдында сипаттама немесе фото қосыңыз.",
        "msg_complaint_error": "Өтінім жасау қатесі. Қайталаңыз немесе меню арқылы қолдауға хабарласыңыз.",
        "msg_complaint_received": "Өтініміңізді қабылдадық. Қолдау жағдайды анықтайды.",
        "msg_enter_reason": "Себепті жазыңыз:",
        "msg_enter_reason_text": "Себепті мәтінмен енгізіңіз.",
        "msg_nps_thanks": "Бағаңыз үшін рақмет!",
        "msg_nps_question": "Бізді 1–5 масштабында ұсынуға дайынсыз ба?",
        "msg_nps_thank": "Рақмет! Пікіріңіз біз үшін маңызды.",
        "msg_invalid_format_short": "Қате формат.",
        "msg_invalid_id": "Қате идентификатор.",
        "msg_score_1_to_5": "Баға 1-ден 5-ке дейін болуы керек.",
        "msg_invalid_status": "Қате күй.",
        "msg_invalid_response": "Қате жауап форматы.",
        "msg_error_later": "Қате орын алды. Кейінірек қайталаңыз.",
        "msg_cancelled": "Бас тартылды.",
        "msg_invalid_uuid": "Қате пайдаланушы идентификаторы.",
        "msg_user_not_telegram": "Пайдаланушы Telegram-да емес.",
        "language_prompt": "Тілді таңдаңыз:",
        "country_prompt": "Еліңізді таңдаңыз:",
        "offer_header": "Жаңа тапсырыс",
        "offer_details_header": "📋 Тапсырыс детальдары:",
        "offer_format": "🎥 Формат: {format_label}",
        "offer_task": "📝 Тапсырма: {task}",
        "offer_budget": "💰 Бюджет: {price} {currency} 1 UGC-бейнеге",
        "offer_barter": "🎁 Бартер: {description}",
        "offer_content_usage": "📢 Пайдалану: {usage}",
        "offer_deadlines": "⏱ Мерзімдер: {deadlines}",
        "offer_geography": "📍 География: {geography}",
        "offer_bloggers_needed": "👥 Креаторлар қажет: {count}",
        "offer_warning": (
            "⚠️ Маңызды\n"
            "🧷 Көрсетілген шарттарда жұмыс жасауға дайын болсаңыз ғана жауап беріңіз\n"
            "❗ Жарнама беруші шарттарды өзгертпеген жағдайда жауап бергеннен кейін бас тарту "
            "шағым мен аккаунт шектеуіне әкелуі мүмкін"
        ),
        "offer_how_it_works": (
            "⏳ Қалай жұмыс істейді\n"
            "● Офферге жауап бересіз\n"
            "● Өнім сілтемесін аласыз\n"
            "● Жарнама беруші профиліңізді алып сізге алдымен жазады\n"
            "● Платформа келіссөздер мен төлемге қатыспайды"
        ),
        "offer_format_label_ugc_placement": "UGC + орналастыру",
        "offer_format_label_ugc_only": "Бренд үшін UGC-бейне",
        "btn_offer_accept": "UGC түсіруге дайын",
        "btn_offer_skip": "Өткізіп жіберу",
        "btn_complaint": "{name} туралы шағымдану",
    },
    "be": {
        # Start & support
        "start_message": (
            "UMC — сэрвіс для UGC.\n"
            "Бізнесу — падбор крэатараў, крэатарам — заказы."
        ),
        "support_response": (
            "Служба падтрымкі: @usemycontent\nЗварочайцеся па любых пытаннях!"
        ),
        "receipt_description": "Паслугі платформы Use My Content",
        # Role selection buttons
        "btn_creator": "Я крэатар",
        "btn_advertiser": "Мне патрэбны UGC‑крэаторы",
        # Common buttons
        "btn_support": "💬 Падтрымка",
        "btn_my_orders": "📂 Мае заказы",
        "btn_change_role": "Змена ролі",
        "btn_create_profile": "Стварыць профіль",
        "btn_advertiser_start": "Пачаць",
        "btn_create_order": "➕ Стварыць заказ",
        "btn_confirm_instagram": "✅ Пацвердзіць Instagram",
        "btn_confirm_agreement": "✅ Пацвердзіць згоду",
        "btn_edit_profile": "Рэдагаваць профіль",
        "btn_my_profile": "👤 Мой профіль",
        "btn_work_format_ads": "📢 Размяшчаць рэкламу ў сябе ў акаўнце",
        "btn_work_format_ugc_only": "❌ Толькі UGC (без размяшчэння)",
        "btn_phone_request": "📱 Падзяліцца нумарам тэлефона",
        "btn_location_request": "📍 Падзяліцца геапазіцыяй",
        "btn_location_map": "🗺 Выбраць на карце",
        "btn_city_picker": "Выбраць горад",
        "btn_edit_profile_blogger": "Рэдагаваць профіль блогера",
        "btn_edit_profile_advertiser": "Рэдагаваць профіль рэкламадаўцы",
        "btn_audience_f": "👩 У асноўным жанчыны",
        "btn_audience_m": "👨 У асноўным мужчыны",
        "btn_audience_a": "👥 Прыблізна пароўну",
        "btn_gender_m": "Мужчынскі",
        "btn_gender_f": "Жаночы",
        "btn_age_0_17": "да 18",
        "btn_age_18_24": "18–24",
        "btn_age_25_34": "25–34",
        "btn_age_35_44": "35–44",
        "btn_age_45_99": "45+",
        "btn_barter_yes": "Так",
        "btn_barter_no": "Не",
        "btn_payout": "Выплаціць",
        "btn_back": "Назад",
        "btn_forward": "Наперад",
        "btn_back_arrow": "⬅️ Назад",
        "btn_forward_arrow": "Наперад ➡️",
        "btn_pay_order": "💳 Аплаціць №{creation_number}",
        "btn_open_profile": "🔗 Адкрыць профіль",
        "btn_write_telegram": "Напісаць у тэлеграм",
        "btn_ok_skipped": "Ок, прапушчана.",
        # Order creation
        "order_type_ugc_only": "🎥 UGC-відэа для брэнда",
        "order_type_ugc_placement": "📢 UGC + размяшчэнне ў крэатара",
        "order_photo_add": "📷 Дадаць фота",
        "order_photo_skip": "⏭ Прапусціць",
        "coop_barter": "🎁 Бартэр",
        "coop_payment": "💰 Аплата",
        "coop_both": "🔄 Бартэр + аплата",
        "content_social": "📱 У сацсетках брэнда",
        "content_ads": "📢 У рэкламе (таргет, аб'явы)",
        "content_both": "🔄 У сацсетках і рэкламе",
        "deadlines_3": "⏱ Да 3 дзён",
        "deadlines_7": "⏱ Да 7 дзён",
        "deadlines_14": "⏱ Да 14 дзён",
        # Messages: user/role
        "msg_user_not_found": "Карыстальнік не знойдзены.",
        "msg_user_not_found_start": "Карыстальнік не знойдзены. Пачніце з /start.",
        "msg_registration_blocked": "Заблакаваныя карыстальнікі не могуць рэгістравацца.",
        "msg_registration_pause": "Карыстальнікі на паузе не могуць рэгістравацца.",
        "msg_instagram_blocked": "Заблакаваныя не могуць пацвярджаць акаўнт.",
        "msg_instagram_pause": "На паузе не могуць пацвярджаць акаўнт.",
        "msg_complaint_blocked": "Заблакаваныя карыстальнікі не могуць падаваць скаргі.",
        "msg_complaint_pause": "Карыстальнікі на паузе не могуць падаваць скаргі.",
        "msg_order_creation_blocked": "Заблакаваныя не могуць ствараць заказы.",
        "msg_order_creation_pause": "На паузе не могуць ствараць заказы.",
        "msg_payment_blocked": "Заблакаваныя карыстальнікі не могуць аплочваць заказы.",
        "msg_payment_pause": "Карыстальнікі на паузе не могуць аплочваць заказы.",
        "msg_feedback_blocked": "Заблакаваныя карыстальнікі не могуць пакідаць водгук.",
        "msg_feedback_pause": "Карыстальнікі на паузе не могуць пакідаць водгук.",
        "msg_feedback_rate_blocked": "Заблакаваныя карыстальнікі не могуць ацэньваць.",
        "msg_feedback_rate_pause": "Карыстальнікі на паузе не могуць ацэньваць.",
        # Feedback flow messages
        "msg_fb_thanks_saved": "Дзякуй, адказ захаваны.",
        "msg_fb_thanks_feedback": "Дзякуй за зваротную сувязь.",
        "msg_fb_interaction_not_found": "Узаемадзеянне не знойдзена.",
        "msg_fb_insufficient_rights": "Недастаткова правоў.",
        "msg_fb_no_deal_question_blog": "Падкажыце, па якой прычыне не ўдалося дамовіцца?",
        "msg_fb_no_deal_question_adv": "Па якой прычыне не ўдалося дамовіцца?",
        "msg_fb_thanks_short": "Дзякуй.",
        "msg_fb_issue_prompt": (
            "Апішыце праблему і прыкладзіце скрыншоты перапіскі або "
            "іншыя пацверджанні. Гэта дапаможа разабрацца.\n"
            "👉 Напішыце тэкст, прымацуйце фота і націсніце «Адправіць»."
        ),
        "msg_fb_postpone_max": (
            "Дасягнута максімальная колькасць пераносаў. "
            "Статус зафіксаваны як 'Не дамовіліся'."
        ),
        "msg_fb_postpone_72": "Праверка перанесена на 72 г. Пераносаў: {cnt}/{max_cnt}",
        "msg_fb_postpone_ok_blog": (
            "Добра, вернемся да гэтага пазней 👍 "
            "Калі заказчык напіша — проста адкажыце яму."
        ),
        "msg_fb_postpone_ok_adv": (
            "Зразумелі, вернемся да гэтага пазней 👍\n"
            "ℹ️ Крэатар не бачыць кантакты. "
            "Сувязь пачынаецца з вашага боку."
        ),
        "msg_fb_ok_blog": (
            "Дзякуй за зваротную сувязь 👍 "
            "Калі спатрэбіцца дапамога — мы на сувязі."
        ),
        "msg_fb_ok_adv": (
            "Дзякуй за зваротную сувязь 👍 Жадаем удалай працы з крэатарам."
        ),
        "msg_fb_invalid_format": "Няверны фармат.",
        "msg_fb_invalid_response": "Няверны фармат адказу.",
        "msg_fb_invalid_status": "Няверны статус.",
        "msg_fb_invalid_id": "Няверны ідэнтыфікатар.",
        "msg_fb_error_try_later": "Адбылася памылка. Паспрабуйце пазней.",
        "msg_fb_no_deal_other_prompt": "Напішыце, калі ласка, прычыну:",
        "msg_fb_enter_reason_text": "Увядзіце прычыну тэкстам.",
        "msg_fb_session_expired": "Сесія скончылася. Адкажыце на пытанне зваротнай сувязі зноў.",
        "msg_fb_session_expired_nps": "Сесія скончылася. Адкажыце на пытанне ацэнкі зноў.",
        "msg_fb_error_try_again": "Памылка. Паспрабуйце зноў.",
        "msg_fb_add_description_photo": "Дадайце апісанне або фота, затым націсніце «Адправіць».",
        "msg_fb_add_description_before_send": "Дадайце апісанне або фота перад адпраўкай.",
        "msg_fb_complaint_error": (
            "Адбылася памылка пры стварэнні заяўкі. Паспрабуйце зноў "
            "або звярніцеся ў падтрымку праз меню."
        ),
        "msg_fb_complaint_accepted": (
            "Мы прынялі вашу заяўку. Падтрымка разбярэцца ў сітуацыі. "
            "Пры неабходнасці націсніце «Падтрымка» ў меню."
        ),
        "msg_fb_nps_done_btn": "Гатова",
        "msg_fb_nps_thank": (
            "Дзякую! 🙌\n"
            "Ваш водгук захаваны, ён дапамагае нам рабіць платформу UMC лепш 🙏"
        ),
        "msg_fb_nps_question": "Ацаніце, калі ласка, працу з платформай UMC па шкале ад 1 да 5 ⭐",
        "msg_fb_nps_prompt_5_adv": (
            "Дзякуй за ацэнку 5 ⭐ — вельмі рады, што вам было зручна працаваць "
            "з платформай UMC! 🙌\n"
            "Калі ёсць 1–2 ідэі, як зрабіць сэрвіс яшчэ зручней (інтэрфейс, "
            "падбор крэатараў, апавяшчэнні і г.д.) — напішыце ў адказ.\n"
            "Мы ўважліва чытаем кожную прапанову для развіцця платформы."
        ),
        "msg_fb_nps_prompt_5_blog": (
            "Дзякуй за ацэнку 5 ⭐ — вельмі рады, што вам камфортна працаваць "
            "з заказчыкамі праз платформу UMC! 🙌\n"
            "Калі ёсць 1–2 ідэі, як паляпшыць сэрвіс (асабісты кабінет, падбор "
            "заказаў, умовы, падтрымка) — напішыце ў адказ.\n"
            "Мы ўважліва чытаем кожную прапанову для развіцця платформы."
        ),
        "msg_fb_nps_prompt_34_adv": (
            "Дзякуй за вашу ацэнку 🙏\n"
            "Нам важна зразумець, што менавіта можна паляпшыць у рабоце з UMC.\n"
            "Калі ласка, у адным паведамленні напішыце:\n"
            "– што не задаволіла (падбор, хуткасць, інтэрфейс, камунікацыя)."
        ),
        "msg_fb_nps_prompt_34_blog": (
            "Дзякуй за вашу ацэнку 🙏\n"
            "Нам важна разумець, што можна паляпшыць у рабоце з заказамі праз UMC.\n"
            "Калі ласка, у адным паведамленні напішыце:\n"
            "– што было складана або нязручна (умовы, зносіны з заказчыкам, інтэрфейс, "
            "апавяшчэнні і г.д.)."
        ),
        "msg_fb_nps_prompt_1_adv": (
            "Дзякуй, што шчыра паставілі 1 ⭐ — нам сапраўды важна гэта ведаць 🙏\n"
            "Нам вельмі шкада, што вопыт працы з платформай UMC аказаўся негатыўным.\n"
            "Калі ласка, апішыце ў адным паведамленні, што менавіта пайшло не так:\n"
            "– праблемы з крэатарам;\n"
            "– складанасці з платформай;\n"
            "– памылкі, затрымкі, непаразуменні і г.д.\n"
            "Мы ўважліва разбяром сітуацыю."
        ),
        "msg_fb_nps_prompt_1_blog": (
            "Дзякуй, што шчыра паставілі 1 ⭐ — нам сапраўды важна гэта ведаць 🙏\n"
            "Нам вельмі шкада, што вопыт працы праз UMC аказаўся негатыўным.\n"
            "Калі ласка, апішыце ў адным паведамленні, што менавіта адбылося:\n"
            "– праблемы з заказчыкам;\n"
            "– складанасць умоў;\n"
            "– тэхнічныя праблемы платформы;\n"
            "– любыя іншыя моманты.\n"
            "Мы ўважліва разбяром сітуацыю."
        ),
        "msg_fb_issue_send_btn": "📤 Адправіць",
        "msg_fb_feedback_ok": "✅ Усё прайшло нармальна",
        "msg_fb_feedback_no_deal": "❌ Не дамовіліся",
        "msg_fb_feedback_postpone": "⏳ Яшчэ не звязаўся",
        "msg_fb_feedback_issue": "⚠️ Праблема / падазрэнне на махлярства",
        "msg_fb_no_deal_conditions": "💰 Не сышліся па ўмовах",
        "msg_fb_no_deal_timing": "⏱ Не падышлі тэрміны",
        "msg_fb_no_deal_differed": "📝 Умовы адрозніваліся ад оферу",
        "msg_fb_no_deal_creator_change": "📝 Крэатар хацеў змяніць умовы",
        "msg_fb_no_deal_other": "🤝 Іншае",
        "msg_fb_score_1_to_5": "Ацэнка павінна быць ад 1 да 5.",
        "msg_fb_thanks_for_rating": "Дзякуй за ацэнку!",
        "msg_fb_no_description": "Без апісання",
        # Feedback scheduler
        "msg_feedback_request_adv": (
            "Хочам упэўніцца, што ўсё прайшло карэктна 🙌\n"
            "Удалося вам звязацца з крэатарам{creator_link}?\n"
            "Выберыце адпаведны варыянт:"
        ),
        "msg_feedback_request_blog": (
            "Мы хочам упэўніцца, што ўсё прайшло карэктна 🙌\n"
            "Удалося вам звязацца з заказчыкам {order_link_part}"
        ),
        "msg_choose_role": "Выберыце ролю праз /role.",
        "msg_fill_profile_orders": (
            "Запоўніце профіль (/advertiser або /creator), каб бачыць заказы."
        ),
        "msg_confirm_agreement": (
            "Калі ласка, пацвердзіце згоду з дакументамі платформы."
        ),
        "msg_agreements_intro_default": (
            "Профіль створаны. Азнаёмцеся з дакументамі і пацвердзіце."
        ),
        "msg_label_offer": "📄 Афerta",
        "msg_label_privacy": "🔒 Палітыка канфідэнцыяльнасці",
        "msg_label_consent": "🧾 Згода на апрацоўку персанальных даных",
        "msg_confirm_docs_fallback": (
            "Пацвердзіце згоду з дакументамі платформы."
        ),
        "msg_no_orders": "У вас пакуль няма заказаў. /create_order",
        "msg_no_blogger_orders": (
            "Вы пакуль не адгукваліся. Прапановы прыходзяць у бот."
        ),
        "msg_blogger_profile_empty": "Профіль блогера не запоўнены.",
        "msg_advertiser_profile_empty": "Профіль рэкламадаўцы не запоўнены.",
        "msg_advertiser_profile_fill": (
            "Профіль рэкламадаўцы не запоўнены. Каманда: /advertiser"
        ),
        "msg_creator_profile_fill": "Профіль не запоўнены. Каманда: /creator",
        "msg_confirm_instagram_first": "Пацвердзіце Instagram перад адгукам.",
        "msg_confirm_agreement_first": "Спачатку пацвердзіце згоду.",
        # Messages: payments
        "msg_invalid_order_amount": "Некарэктная сума заказу.",
        "msg_order_amount_too_large": (
            "Сума заказу занадта вялікая для выстаўлення рахунку ў Telegram."
        ),
        "msg_invoice_failed": "Не ўдалося стварыць рахунак. Паспрабуйце пазней.",
        "msg_pay_order_usage": "Выкарыстанне: /pay_order <order_id>",
        "msg_invalid_order_id": "Няверны фармат order_id.",
        "msg_invalid_order_format": "Няверны фармат заказу.",
        "msg_order_not_found": "Заказ не знойдзены.",
        "msg_order_not_yours": "Заказ не належыць рэкламадаўцу.",
        "msg_order_not_new": "Заказ не ў статусе NEW.",
        "msg_pricing_not_configured": (
            "Кошт доступу не настроены. Звяжыцеся з падтрымкай."
        ),
        "msg_payment_provider_not_configured": (
            "Плацёжны правайдар не настроены."
        ),
        "msg_order_undetermined": "Не ўдалося вызначыць заказ.",
        "msg_title_payment": "Аплата заказу",
        # Messages: referral
        "msg_referral_payout_today": "Вы ўжо падавалі заяўку на вывад сёння.",
        "msg_referral_payout_unavailable": (
            "Выплата недаступна: няма балансу або ўжо ёсць заяўка."
        ),
        "msg_referral_payout_sent": "Запыт на выплату адпраўлены ў падтрымку.",
        "msg_referral_payout_notify_failed": (
            "Заяўка створана, але не ўдалося апавясціць падтрымку. "
            "Звярніцеся ў падтрымку ўручную."
        ),
        "msg_referral_payout_blocked": "Не можаце запытваць выплату.",
        "msg_referral_payout_pause": "Карыстальнікі на паузе не могуць запытваць выплату.",
        "msg_referral_no_users": "У вас пакуль няма прыведзеных карыстальнікаў.",
        "msg_referral_access_denied": "Доступ забаронены.",
        "msg_referral_blocked": "Заблакаваныя не могуць выкарыстоўваць каманду.",
        "msg_referral_pause": "Карыстальнікі на паузе не могуць выкарыстоўваць каманду.",
        "msg_referral_list_blocked": "Заблакаваныя не могуць праглядаць спіс.",
        "msg_referral_list_pause": "Карыстальнікі на паузе не могуць праглядаць спіс.",
        "msg_referral_list_title": (
            "Вашы рэфералы (старонка {page}/{total_pages}):"
        ),
        "msg_referral_list_empty": "Вашы рэфералы: пакуль нікога.",
        "msg_referral_pending_block": (
            "Не запоўнілі профіль крэатара (нагадвайце запоўніць):"
        ),
        "msg_referral_no_pending": "Няма рэфералаў без профілю.",
        "msg_referral_link_intro": "Ваша рэферальная спасылка:",
        "lbl_referral_stats": "📊 Рэферальная статыстыка",
        "lbl_referral_creators": "Прыведзена крэатараў",
        "lbl_referral_orders": "Выканана заказаў",
        "lbl_referral_income_month": "Даход за бягучы месяц",
        "lbl_referral_income_total": "Назапашана (усяго)",
        "lbl_referral_paid": "Выплачана",
        "lbl_referral_balance": "Бягучы баланс",
        "lbl_referral_orders_done": "выканана заказаў",
        "msg_offer_new_response": (
            "Новы адгук па вашым заказе 🙌\n\n"
            "👤 Крэатар: {creator}\n"
            "📍 Горад: {city}\n"
            "🎬 Фармат: {format}\n"
            "💼 Гатовы працаваць на ўмовах оферу\n"
            "🔗 Профіль крэатара:\n{profile_url}"
        ),
        "lbl_creator_fallback": "Крэатар",
        "lbl_phone_dash": "Тэлефон: —",
        "lbl_telegram_dash": "Telegram: —",
        "msg_offer_contacts_header": "📞 Кантакты заказчыка для сувязі:\n\n",
        "msg_advertiser_new_response_what_next": (
            "🔔 Што далей\n\n"
            "💬 Напішыце крэатару і абмяркуйце дэталі\n"
            "✅ Крэатар азнаёміўся з офером і гатовы працаваць на паказаных умовах\n"
            "⏱ Рэкамендуем звязацца на працягу 30 хв\n\n"
            "⚠️ Напамін\n\n"
            "🧷 Умовы оферу не рэкамендуецца мяняць\n"
            "🔄 Пры змяненні ўмоў крэатар можа адмовіцца ад супрацоўніцтва\n"
            "➡️ Сувязь заўсёды пачынаецца з вашага боку"
        ),
        "msg_offer_response_blocked": "Заблакаваныя карыстальнікі не могуць адгукацца.",
        "msg_offer_response_pause": "Карыстальнікі на паузе не могуць адгукацца.",
        "msg_advertiser_contacts_warning": (
            "⚠️ **Бяспечны парадак працы з блогерамі:**\n\n"
            "• Платформа не рэкамендуе перадаплату\n"
            "• Аплочвайце пасля атрымання прэв'ю з вадзяным знакам\n"
            "• Упэўніцеся ў якасці кантэнту перад фінальнай аплатай\n"
            "• Перамовы і здзелкі — напрамую паміж вамі і блогерам"
        ),
        # Messages: orders list
        "msg_my_orders_blocked": "Заблакаваныя не могуць праглядаць заказы.",
        "msg_my_orders_pause": "На паузе не могуць праглядаць заказы.",
        "msg_orders_title": "Вашы заказы (старонка {page}/{total_pages}):",
        "msg_orders_blogger_title": (
            "Заказы, на якія вы адгукнуліся (старонка {page}/{total_pages}):"
        ),
        "msg_order_status": "Статус: {status_label}",
        "msg_order_creators": "Крэатараў: {bloggers_needed}",
        "msg_order_matched": "Падабрана: {matched_count} / {bloggers_needed}",
        "msg_order_date_created": "Дата стварэння: {date}",
        "msg_order_date_completed": "Дата завяршэння: {date}",
        "msg_order_link": "Спасылка на праект: {link}",
        "msg_order_format": "Фармат: {order_type}",
        "msg_order_type_ugc": "UGC-відэа для брэнда",
        "msg_order_type_placement": "UGC + размяшчэнне",
        "msg_order_price": "Кошт 1 UGC: {price}",
        "msg_order_barter": "Бартэр: {desc}",
        "msg_status_new": "Створаны",
        "msg_status_pending_moderation": "На мадэрацыі",
        "msg_status_active": "Актыўны",
        "msg_status_closed": "Завершаны",
        # Messages: blogger registration / profile
        "msg_choose_city": "Выберыце горад са спісу.",
        "msg_choose_city_or_type": (
            "Укажыце бліжэйшы буйны горад або націсніце «Выбраць горад»"
        ),
        "msg_city_multiple_regions": (
            "Гэты горад ёсць у некалькіх рэгіёнах. Выберыце рэгіён:"
        ),
        "msg_session_expired": "Сесія скончылася. Пачніце зноў.",
        "msg_session_expired_orders": "Сесія скончылася. Пачніце зноў з «Стварыць заказ».",
        "msg_session_expired_profile": "Сесія скончылася. Адкрыйце «Мой профіль» зноў.",
        "msg_profile_not_found": "Профіль не знойдзены.",
        "msg_profile_not_found_role": "Профіль не знойдзены. Выберыце ролю праз /role.",
        "msg_profile_incomplete": "Профіль не запоўнены.",
        "msg_choose_profile_edit": "Выберыце профіль для рэдагавання:",
        "msg_choose_section_edit": "Выберыце раздзел для рэдагавання:",
        "msg_choose_section_keyboard": "Выберыце адзін з раздзелаў на клавіятуры.",
        "msg_profile_updated": "Профіль абноўлены.",
        "msg_advertiser_profile_not_found": "Профіль рэкламадаўцы не знойдзены.",
        "msg_unknown_field": "Невядомае поле.",
        "msg_profile_update_failed": "Не ўдалося абнавіць профіль.",
        "err_city_not_place_use_map": (
            "Не ўдалося абнавіць профіль. Укажыце месцазнаходжанне на карце "
            "або падзяліцеся геапазіцыяй."
        ),
        "err_instagram_format_example": "Няверны фармат спасылкі. Прыклад: instagram.com/name",
        "err_instagram_invalid": "Няверны фармат спасылкі Instagram.",
        "err_instagram_taken": "Гэты Instagram ужо зарэгістраваны. Выкарыстайце іншы.",
        "msg_city_picker_edit": (
            "Укажыце бліжэйшы буйны горад або націсніце «Выбраць горад» і выберыце са спісу."
        ),
        "msg_choose_buttons": "Выберыце адну з кнопак.",
        "msg_name_updated": "Імя абноўлена.",
        # Profile display
        "lbl_profile_your": "👤 Ваш профіль",
        "lbl_profile_general": "📋 Агульная інфармацыя",
        "lbl_profile_name": "Імя",
        "lbl_profile_roles": "Ролі",
        "lbl_profile_status": "Статус",
        "lbl_profile_blogger": "📸 Профіль блогера",
        "lbl_profile_not_filled": "Не запоўнены",
        "lbl_profile_advertiser": "🏢 Профіль рэкламадаўцы",
        "lbl_status_new": "Новы",
        "lbl_status_active": "Актыўны",
        "lbl_status_pause": "На паузе",
        "lbl_status_blocked": "Заблакаваны",
        "lbl_audience_male": "Мужчыны",
        "lbl_audience_female": "Жанчыны",
        "lbl_audience_all": "Усе",
        "lbl_blogger_gender_male": "Мужчынскі",
        "lbl_blogger_gender_female": "Жаночы",
        "lbl_role_blogger": "Блогер",
        "lbl_role_advertiser": "Рэкламадавец",
        "lbl_yes": "Так",
        "lbl_no": "Не",
        "lbl_work_format_ads": "Размяшчаць рэкламу ў сябе ў акаўнце",
        "lbl_work_format_ugc": "Толькі UGC",
        "lbl_instagram": "Instagram",
        "lbl_confirmed": "Пацверджаны",
        "lbl_city": "Горад",
        "lbl_country": "Краіна",
        "lbl_region": "Рэгіён",
        "lbl_gender": "Пол",
        "lbl_birth_date": "Дата нараджэння",
        "lbl_topics": "Тэматыкі",
        "lbl_audience": "Мэтавая аўдыторыя",
        "lbl_geo": "Геаграфія",
        "lbl_price": "Цана",
        "lbl_barter": "Бартэр",
        "lbl_work_format": "Фармат працы",
        "lbl_phone": "Тэлефон",
        "lbl_brand": "Брэнд",
        "lbl_activity": "Дзейнасць",
        "lbl_site": "Сайт",
        "lbl_years": "гадоў",
        # Profile edit prompts
        "prompt_edit_nickname": "Увядзіце новае імя:",
        "prompt_edit_instagram_url": "Прымацуйце спасылку instagram.com/name:",
        "prompt_edit_city": "З якога вы горада?",
        "prompt_edit_blogger_gender": "Укажыце ваш пол:",
        "prompt_edit_birth_date": "Укажыце дату нараджэння ў фармаце ДД.ММ.ГГГГ (напрыклад 15.05.1995):",
        "prompt_edit_topics": "Напішыце 1–3 тэматыкі праз коску:",
        "prompt_edit_audience_gender": "Хто ў асноўным глядзіць ваш кантэнт?",
        "prompt_edit_audience_age": "Асноўны ўзрост вашай аўдыторыі?",
        "prompt_edit_audience_geo": "Укажыце да 3 гарадоў праз коску:",
        "prompt_edit_price": "Укажыце цану за 1 UGC‑відэа ({currency}):",
        "prompt_edit_barter": "Гатовы працаваць па бартэры?",
        "prompt_edit_work_format": "Як гатовы працаваць з брэндамі?",
        "prompt_edit_name": "Увядзіце імя:",
        "prompt_edit_phone": "Укажыце нумар тэлефона для сувязі. Прыклад: 89001110777",
        "prompt_edit_brand": "Назва вашага брэнда / кампаніі / бізнесу:",
        "prompt_edit_site_link": "Спасылка на сайт, прадукт або сацсеткі брэнда:",
        "prompt_edit_generic": "Увядзіце новае значэнне:",
        "lbl_edit_nickname": "Імя",
        "lbl_edit_instagram": "Instagram",
        "lbl_edit_city": "Горад",
        "lbl_edit_blogger_gender": "Пол",
        "lbl_edit_birth_date": "Дата нараджэння",
        "lbl_edit_topics": "Тэматыкі",
        "lbl_edit_audience_gender": "Пол аўдыторыі",
        "lbl_edit_audience_age": "Узрост аўдыторыі",
        "lbl_edit_audience_geo": "Геаграфія аўдыторыі",
        "lbl_edit_price": "Цана",
        "lbl_edit_barter": "Бартэр",
        "lbl_edit_work_format": "Фармат працы",
        "lbl_edit_name": "Імя",
        "lbl_edit_phone": "Тэлефон",
        "lbl_edit_brand": "Брэнд",
        "lbl_edit_company_activity": "Дзейнасць кампаніі",
        "lbl_edit_site_link": "Спасылка на сайт",
        # Messages: advertiser registration
        "msg_whats_your_name": "Як вас завуць?",
        "msg_choose_action": "Выберыце дзеянне:",
        "msg_what_city": "З якога вы горада?\nПрыклад: Мінск / Гомель / Брэст",
        "msg_brand_name": "Назва вашага брэнда / кампаніі / бізнесу:",
        "msg_company_activity": "Чым займаецца ваша кампанія?",
        "msg_brand_link": "Спасылка на сайт, прадукт або сацсеткі брэнда:",
        "msg_after_registration": (
            "Цяпер вы можаце размясціць заказ і знайсці UGC-крэатараў."
        ),
        "msg_advertiser_intro": (
            "Вы выбралі ролю «Мне патрэбны UGC‑крэаторы».\n"
            "Давайце створым профіль, каб вы маглі размяшчаць заказы."
        ),
        "msg_creator_intro": (
            "Ты — UGC‑крэатар. Заказчыкі ўжо шукаюць крэатараў тут — поўны профіль "
            "дапамагае трапіць у падбор і атрымліваць падыходзячыя заказы.\n\n"
            "Запоўнім профіль за пару хвілін — і ты ў падборы."
        ),
        # Creator registration: step prompts
        "msg_step_ask_name": "Як вас завуць?\n\nКрок 1 з 12",
        "msg_step_ask_instagram": "Прышліце спасылку ў фармаце instagram.com/name\n\nКрок 2 з 12",
        "msg_step_ask_instagram_first": "Прышліце спасылку ў фармаце instagram.com/name\n\nКрок 1 з 12",
        "msg_step_ask_city": (
            "Заказчыкі падбіраюць крэатараў па горадзе: для дастаўкі прадукту і "
            "для афлайн узаемадзеяння. З якога вы горада?\n\nКрок 3 з 12"
        ),
        "msg_step_ask_birth_date": (
            "Укажыце дату нараджэння ў фармаце ДД.ММ.ГГГГ (напрыклад 15.05.1995):\n\nКрок 4 з 12"
        ),
        "msg_step_ask_gender": "Укажыце ваш пол:\n\nКрок 5 з 12",
        "msg_step_ask_topics": (
            "Пра што ваш кантэнт?\n"
            "Напішыце 1–5 тэматык праз коску: бізнес, інвестыцыі, фітнес, "
            "харчаванне, б'юці, догляд за скурай, вандроўкі, ежа, рэстараны, мода, "
            "стыль, дзеці, сям'я, тэхналогіі, гаджэты, лайфстайл, мерапрыемствы, іншае\n\nКрок 6 з 12"
        ),
        "msg_step_ask_audience_gender": (
            "Хто ў асноўным глядзіць ваш кантэнт? "
            "Па назіраннях або статыстыцы\n\nКрок 7 з 12"
        ),
        "msg_step_ask_audience_age": "Асноўны ўзрост вашай аўдыторыі?\n\nКрок 8 з 12",
        "msg_step_ask_audience_geo": (
            "У якіх гарадах у асноўным аўдыторыя? Да 3 гарадоў праз коску, "
            "напрыклад: Мінск, Гомель, Брэст\n\nКрок 9 з 12"
        ),
        "msg_step_ask_price": (
            "Заказчыкі адбіраюць крэатараў па бюджэту — указаная цана паскарае здзелку. "
            "Колькі каштуе адно UGC‑відэа? Цана ({currency}), напрыклад: 500, 1000, 2000\n\nКрок 10 з 12"
        ),
        "msg_step_ask_barter": (
            "Шмат заказаў з бартэрам — адказ «Так» павялічыць колькасць офераў. "
            "Гатовы часам працаваць з брэндамі па бартэры?\n\nКрок 11 з 12"
        ),
        "msg_step_ask_work_format": (
            "Акрамя UGC, як яшчэ гатовы працаваць з брэндамі? "
            "Апошні крок перад падборам.\n\nКрок 12 з 12"
        ),
        "msg_agreements_intro_creator": (
            "Амаль гатова. "
            "Калі ласка, азнаёмцеся з дакументамі і пацвердзіце згоду."
        ),
        "msg_profile_created": (
            "Профіль створаны 👍\n\n"
            "Заказчыкі ўжо шукаюць крэатараў — запоўнены профіль павышае шансы "
            "атрымаць офер.\n\n"
            "Застаўся апошні крок — пацвердзіць Instagram‑акаўнт. Гэта патрэбна, каб:\n"
            "— абараніць брэнды ад фэйкаў\n"
            "— павысіць давер да твайго профілю\n"
            "— хутчэй атрымліваць заказы"
        ),
        "msg_instagram_already_registered": (
            "Гэты Instagram акаўнт ужо зарэгістраваны. "
            "Калі ласка, выкарыстайце іншы акаўнт або звярніцеся ў падтрымку."
        ),
        "msg_work_format_choose": (
            "Выберыце адну з кнопак: Размяшчаць рэкламу ў сябе ў акаўнце "
            "або Толькі UGC (без размяшчэння)."
        ),
        "msg_registration_aborted": (
            "Рэгістрацыя перарвана. Каб завяршыць, адкрыйце «Мой профіль» "
            "і пацвердзіце згоду."
        ),
        # Creator registration: validation errors
        "err_instagram_empty": (
            "Спасылка не можа быць пустой. Прышліце спасылку ў фармаце instagram.com/name"
        ),
        "err_instagram_format": "Няверны фармат. Патрэбна спасылка выгляду instagram.com/name",
        "err_instagram_example": (
            "Няверны фармат спасылкі Instagram. Прыклад: https://instagram.com/name"
        ),
        "err_gender_choose": "Выберыце адну з кнопак: Мужчынскі або Жаночы.",
        "err_audience_choose": (
            "Выберыце: У асноўным жанчыны, мужчыны або Прыблізна пароўну."
        ),
        "err_age_choose": "Выберыце адну з кнопак узросту.",
        "err_barter_choose": "Выберыце Так або Не.",
        "err_price_number": "Увядзіце лічбу, напрыклад 500, 1000, 2000.",
        "err_geo_max_cities": "Укажыце не больш за 3 гарады праз коску.",
        # Validators (shared)
        "err_not_bot_command": (
            "Не выкарыстоўвайце каманды бота ў якасці адказу. Увядзіце тэкст зноўку."
        ),
        "err_offer_text_min": "Апішыце задачу падрабязней (мінімум {min} сімвалаў).",
        "err_offer_text_max": "Тэкст занадта доўгі (максімум {max} сімвалаў).",
        "err_barter_required": "Апішыце бартэрную прапанову.",
        "err_barter_min": "Апішыце бартэр (мін. {min} сімвалаў).",
        "err_barter_max": "Тэкст доўгі (макс. {max} сімвалаў).",
        "err_url_max": "Спасылка занадта доўгая (максімум {max} сімвалаў).",
        "err_url_scheme": "Увядзіце спасылку (http:// або https://).",
        "err_url_invalid": "Увядзіце карэктную спасылку.",
        "err_url_example": (
            "Увядзіце карэктную спасылку (напрыклад, сайт.бел або example.com)."
        ),
        "err_product_link_empty": "Спасылка не можа быць пустой. Увядзіце зноўку:",
        "err_geo_required": (
            "Укажыце адзін варыянт: горад, рэгіён або краіна. "
            "Прыклады: Мінск, Гомель, Брэсцкая вобл., РБ"
        ),
        "err_geo_max": "Тэкст занадта доўгі (максімум {max} сімвалаў).",
        "err_min_chars": "Увядзіце мінімум {min} сімвалы.",
        "err_max_chars": "Максімум {max} сімвалаў.",
        "err_phone_empty": "Нумар тэлефона не можа быць пустым. Увядзіце зноўку:",
        "err_phone_digits": (
            "Увядзіце карэктны нумар (10–11 лічбаў). Прыклад: 89001110777"
        ),
        "err_phone_too_many": "Занадта шмат лічбаў. Прыклад: 89001110777",
        "err_phone_invalid": "Увядзіце карэктны нумар. Прыклад: 89001110777",
        "err_birth_date_empty": (
            "Увядзіце дату нараджэння ў фармаце ДД.ММ.ГГГГ (напрыклад 15.05.1995)."
        ),
        "err_birth_date_format": (
            "Няверны фармат. Выкарыстоўвайце ДД.ММ.ГГГГ (напрыклад 15.05.1995)."
        ),
        "err_birth_date_digits": (
            "Увядзіце дату лічбамі ў фармаце ДД.ММ.ГГГГ (напрыклад 15.05.1995)."
        ),
        "err_birth_date_invalid": "Некарэктная дата. Праверце дзень, месяц і год.",
        "err_birth_date_future": "Дата нараджэння не можа быць у будучыні.",
        "err_birth_date_min_age": "Узрост павінен быць не менш за {age} гадоў.",
        "err_birth_date_max_age": (
            "Укажыце рэальную дату нараджэння (узрост да {age} гадоў)."
        ),
        "err_city_required": "Укажыце горад. Увядзіце зноўку:",
        "err_city_from_location": "Не ўдалося вызначыць горад па геапазіцыі. Увядзіце горад уручную або паспрабуйце яшчэ раз.",
        "err_city_not_found_use_map": (
            "Не ўдалося вызначыць месцазнаходжанне па назве. "
            "Увядзіце дакладную назву горада або адпраўце геалакацыю."
        ),
        "err_company_activity_max": "Максімум {max} сімвалаў.",
        "err_nickname_no_url": "Увядзіце імя, а не спасылку на Instagram.",
        "err_topics_empty": "Увядзіце хаця б адну тэматыку:",
        "err_topics_max": "Укажыце не больш за {max} тэматыкі.",
        "err_audience_geo_empty": "Укажыце хаця б адзін горад. Увядзіце зноўку:",
        "err_audience_geo_max": "Максімум {max} сімвалаў.",
        "err_price_positive": "Цана павінна быць больш за 0.",
        "err_price_max": (
            "Сума перавышае максімальна дапушчальную ({max} {currency})."
        ),
        # Messages: order creation
        "msg_what_do_you_need": "Што вам патрэбна?",
        "msg_choose_from_keyboard": "Выберыце адзін з варыянтаў на клавіятуры.",
        "msg_coop_format": "Які фармат супрацоўніцтва вам падыходзіць?",
        "msg_enter_number": "Увядзіце лічбу, напрыклад 1500.",
        "msg_how_many_creators": "Колькі крэатараў вам патрэбна?",
        "msg_product_link": "Увядзіце спасылку на прадукт (для адгукнуўшыхся крэатараў):",
        "msg_choose_count": "Выберыце адно са значэнняў: {counts}.",
        "msg_where_use_ugc": "Дзе вы плануеце выкарыстоўваць UGC-відэа?",
        "msg_send_photo": "Адпраўце фота прадукту:",
        "msg_order_task_description": (
            "Коратка апішыце задачу для крэатараў.\n"
            "Што зняць і ў якім фармаце. Прыклад: Відэа з распакоўкай."
        ),
        "msg_order_budget": (
            "Бюджэт за 1 UGC-відэа? Укажыце цану ({currency}): 500, 1000, 2000"
        ),
        "msg_order_barter_ask": (
            "Што вы прапануеце па бартэры?\n"
            "Прадукт брэнда (апішыце коратка) + дастаўка"
        ),
        "msg_order_photo_intro": (
            "Прымацуйце фота (па жаданні).\n"
            "Фатаграфія дапаможа крэатару хутчэй зразумець заказ і павысіць адгук "
            "на вашу прапанову"
        ),
        "msg_order_photo_choose": (
            "Выберыце «Дадаць фота» або «Прапусціць» на клавіятуры, "
            "альбо адпраўце фота прадукту."
        ),
        "msg_order_deadline": (
            "У якія тэрміны вам патрэбен кантэнт? "
            "Укажыце, праз колькі дзён пасля ўзгаднення "
            "вы чакаеце прэв'ю."
        ),
        "msg_order_geo": (
            "У якім горадзе, рэгіёне або краіне можа знаходзіцца крэатар? "
            "Укажыце адзін варыянт: напрыклад, Мінск, Гомель, Брэсцкая вобл. або РБ. "
            "Патрэбна для бартэрных заказаў і дастаўкі прадукту."
        ),
        # Messages: Instagram
        "msg_profile_empty_creator": (
            "Профіль не запоўнены. «Стварыць профіль» або /creator"
        ),
        "msg_instagram_already_confirmed": "Ваш Instagram‑акаўнт ужо пацверджаны",
        "msg_instagram_verify_instruction": (
            "<b>Каб пацвердзіць Instagram‑акаўнт, зрабіце 3 крокі:</b>\n\n"
            "1. Скапіруйце код ніжэй\n"
            "2. Адпраўце яго ў асабістыя паведамленні Instagram‑акаўнту UMC\n"
            "3. Дачакайцеся аўтаматычнага пацверджання\n\n"
            '🔗 Instagram UMC: <a href="{url}">{url}</a>\n\n'
            "🔐 Ваш код (код дзейнічае 15 хвілін) 👇"
        ),
        # Messages: complaints
        "msg_invalid_format": "Няверны фармат.",
        "msg_invalid_id_format": "Няверны фармат ідэнтыфікатара.",
        "msg_order_not_found_short": "Заказ не знойдзены.",
        "msg_no_bloggers_complain": "Няма блогераў для скаргі.",
        "msg_complain_on": "Скардзіцца на {blogger_name}",
        "msg_choose_blogger_complain": (
            "Выберыце блогера, на якога хочаце скардзіцца:"
        ),
        "msg_no_access_order": "У вас няма доступу да гэтага заказу.",
        "msg_choose_complaint_reason": "Выберыце прычыну скаргі:",
        "msg_complaint_no_bloggers": "Няма блогераў для скаргі.",
        "msg_invalid_user_id": "Няверны ідэнтыфікатар карыстальніка.",
        "msg_invalid_reason": "Няверная прычына.",
        "msg_data_error": "Памылка апрацоўкі даных.",
        "msg_describe_complaint": "Апішыце прычыну скаргі:",
        "msg_error_try_later": "Адбылася памылка. Паспрабуйце пазней.",
        "msg_enter_complaint_reason": "Калі ласка, увядзіце прычыну скаргі.",
        # Messages: offer responses
        "msg_order_closed": "Заказ ужо зачынены.",
        "msg_order_closed_full": (
            "❗ Заказ ужо зачынены\n\n"
            "Дзякуй за адгук — усе крэатары па гэтым заказе ўжо падабраны.\n\n"
            "Мы абавязкова прышлём новыя заказы, як толькі яны з'явяцца.\n\n"
            "Сачыце за апавяшчэннямі ў боце 🙌"
        ),
        "msg_blogger_after_response_what_next": (
            "⏳ Што далей\n\n"
            "💬 Чакайце паведамленне ад заказчыка — ён атрымаў спасылку на Instagram "
            "і напіша першым\n"
            "📩 Праверце запыты ў Direct\n"
            "👀 Для дэманстрацыі выкарыстоўвайце прэв'ю з вадзяным знакам\n"
            "💸 Атрымайце аплату пасля ўзгаднення прэв'ю\n"
            "🎥 Фінальны UGC-ролік адпраўляйце толькі пасля аплаты\n"
            "❗ Калі заказчык не мяняе ўмовы оферу, адмова пасля адгуку\n"
            " можа прывесці да абмежавання акаўнта\n"
            "🤝 Платформа не ўдзельнічае ў перамовах і аплаце."
        ),
        "msg_offer_accepted": "Адгук прыняты! Чакайце сувязі ад рэкламадаўцы.",
        "msg_offer_order_filled": (
            "Бягучая падборка блогераў ужо зачынена. Мы дадамо вас у ліст чакання — "
            "калі спатрэбіцца замена блогера або заказчык вырашыць пашырыць падборку, "
            "мы першымі адправім вам прапанову."
        ),
        "msg_offer_order_filled_toast": "Запісалі ў ліст чакання",
        "msg_advertiser_after_payment_success": (
            "Аплата прайшла паспяхова ✅\n\nПадбор крэатараў па вашым заказе актываваны."
        ),
        "msg_advertiser_after_payment_what_next": (
            "🔄 **Што далей**\n\n"
            "📩 Крэатары атрымліваюць ваш офер\n"
            "🔗 Вы будзеце атрымліваць адгукі са спасылкамі на іх профілі\n"
            "💬 Вы самастойна звязваецеся з выбранымі крэатарамі"
        ),
        "msg_advertiser_after_payment_important": (
            "⚠️ **Важна**\n\n"
            "🧷 Умовы оферу не рэкамендуецца мяняць пасля публікацыі\n"
            "🔄 Калі ўмовы мяняюцца, крэатар можа адмовіцца ад супрацоўніцтва\n"
            "🤝 Платформа не з'яўляецца бокам здзелкі\n"
            "💸 Аплата крэатарам ажыццяўляецца вамі напрамую\n"
            "👀 Аплочвайце пасля прагляду прэв'ю з вадзяным знакам\n"
            "🚫 Платформа не нясе адказнасці за крэатараў"
        ),
        "msg_phone_request": (
            "Укажыце нумар тэлефона для сувязі па заказе.\n"
            "Націсніце кнопку ніжэй або ўвядзіце нумар уручную "
            "(прыклад: 89001110777)."
        ),
        "msg_instagram_confirmed": (
            "Instagram пацверджаны ✅. Брэнды могуць адпраўляць прапановы."
        ),
        "msg_instagram_mismatch": (
            "Паказаны ў профілі Instagram не супадае з акаўнтам, "
            "з якога вы адправілі код. Адкрыйце «Мой профіль», "
            "адрэдагуйце профіль блогера і ўкажыце карэктны Instagram."
        ),
        "msg_too_many_requests": "Занадта шмат запытаў. Паспрабуйце пазней.",
        "msg_invalid_order_id_short": "Няверны ідэнтыфікатар заказу.",
        # Messages: admin / moderation
        "msg_order_activated": "Заказ актываваны, ідзе блогерам.",
        # Error middleware (user-facing)
        "err_user_not_found": "Карыстальнік не знойдзены.",
        "err_blogger_registration": "Памылка рэгістрацыі блогера.",
        "err_advertiser_registration": "Памылка рэгістрацыі рэкламадаўцы.",
        "err_order_not_found": "Заказ не знойдзены.",
        "err_order_not_active": "Заказ не актыўны.",
        "err_order_creation": "Памылка стварэння заказу.",
        "err_order_already_responded": "Вы ўжо адгукаліся на заказ.",
        "err_order_response_limit": "Ліміт адгукаў па заказе дасягнуты.",
        "err_order_not_new": "Заказ не ў статусе NEW.",
        "err_order_not_yours": "Заказ не належыць рэкламадаўцу.",
        "err_order_invalid_id": "Няверны ідэнтыфікатар заказу.",
        "msg_offer_skipped": "Ок, прапушчана.",
        "err_interaction_not_found": "Узаемадзеянне не знойдзена.",
        "err_interaction": "Памылка ўзаемадзеяння.",
        "err_interaction_status": "Узаемадзеянне не ў ISSUE.",
        "err_interaction_resolution": "Некарэктны статус для ручнога вырашэння.",
        "err_complaint_exists": "Вы ўжо падалі скаргу па гэтым заказе.",
        "err_complaint_not_found": "Скарга не знойдзена.",
        "err_price_exceeds": "Сума перавышае максімум ({amount} {currency}).",
        "err_generic": "Адбылася памылка: {error}",
        # Feedback
        "msg_feedback_thanks": "Дзякуй, адказ захаваны.",
        "msg_feedback_thanks_short": "Дзякуй за зваротную сувязь.",
        "msg_interaction_not_found": "Узаемадзеянне не знойдзена.",
        "msg_insufficient_rights": "Недастаткова правоў.",
        "msg_feedback_thanks_ok": "Дзякуй.",
        "msg_describe_problem": (
            "Апішыце праблему і прыкладзіце скрыншоты перапіскі або "
            "іншыя пацверджанні. Гэта дапаможа разабрацца.\n"
        ),
        "msg_postpone_max": (
            "Дасягнута максімальная колькасць пераносаў. "
            "Статус зафіксаваны як 'Не дамовіліся'."
        ),
        "msg_postpone_72": "Праверка перанесена на 72 г. Пераносаў: {cnt}/{max}",
        "msg_session_expired_feedback": (
            "Сесія скончылася. Адкажыце на пытанне зваротнай сувязі зноў."
        ),
        "msg_error_try_again": "Памылка. Паспрабуйце зноў.",
        "msg_add_description_or_photo": (
            "Дадайце апісанне або фота, затым націсніце «Адправіць»."
        ),
        "msg_add_description_before_send": "Дадайце апісанне або фота перад адпраўкай.",
        "msg_complaint_error": (
            "Адбылася памылка пры стварэнні заяўкі. Паспрабуйце зноў "
            "або звярніцеся ў падтрымку праз меню."
        ),
        "msg_complaint_received": (
            "Мы прынялі вашу заяўку. Падтрымка разбярэцца ў сітуацыі. "
            "Пры неабходнасці націсніце «Падтрымка» ў меню."
        ),
        "msg_enter_reason": "Напішыце, калі ласка, прычыну:",
        "msg_enter_reason_text": "Увядзіце прычыну тэкстам.",
        "msg_nps_thanks": "Дзякуй за ацэнку!",
        "msg_nps_question": "Ацаніце, наколькі вы гатовы рэкамендаваць нас? (1–5)",
        "msg_nps_thank": "Дзякуй! Ваш водгук вельмі важны для нас.",
        "msg_invalid_format_short": "Няверны фармат.",
        "msg_invalid_id": "Няверны ідэнтыфікатар.",
        "msg_score_1_to_5": "Ацэнка павінна быць ад 1 да 5.",
        "msg_invalid_status": "Няверны статус.",
        "msg_invalid_response": "Няверны фармат адказу.",
        "msg_error_later": "Адбылася памылка. Паспрабуйце пазней.",
        # Admin message to user
        "msg_cancelled": "Адменена.",
        "msg_invalid_uuid": "Няверны ідэнтыфікатар карыстальніка.",
        "msg_user_not_telegram": "Карыстальнік не ў Telegram.",
        # Language/country selection
        "language_prompt": "Выберыце мову / Choose language:",
        "country_prompt": "Выберыце вашу краіну:",
        # Offer texts
        "offer_header": "Новы заказ",
        "offer_details_header": "📋 Дэталі заказу:",
        "offer_format": "🎥 Фармат: {format_label}",
        "offer_task": "📝 Задача: {task}",
        "offer_budget": "💰 Бюджэт: {price} {currency} за 1 UGC-відэа",
        "offer_barter": "🎁 Бартэр: {description}",
        "offer_content_usage": "📢 Выкарыстанне: {usage}",
        "offer_deadlines": "⏱ Тэрміны: {deadlines}",
        "offer_geography": "📍 Геаграфія: {geography}",
        "offer_bloggers_needed": "👥 Патрэбна крэатараў: {count}",
        "offer_warning": (
            "⚠️ Важна\n"
            "🧷 Адгукайцеся толькі калі гатовы працаваць на паказаных умовах\n"
            "❗ Адмова пасля адгуку без змянення ўмоў з боку заказчыка"
            "   можа прывесці да скаргі і абмежавання акаўнта"
        ),
        "offer_how_it_works": (
            "⏳ Як гэта працуе\n"
            "● Вы адгукаецеся на офер\n"
            "● Атрымліваеце спасылку на прадукт\n"
            "● Заказчык атрымлівае ваш профіль і піша вам першым\n"
            "● Платформа не ўдзельнічае ў перамовах і аплаце"
        ),
        "offer_format_label_ugc_placement": "UGC + размяшчэнне",
        "offer_format_label_ugc_only": "UGC-відэа для брэнда",
        "btn_offer_accept": "Гатовы зняць UGC",
        "btn_offer_skip": "Прапусціць",
        # Complaint button
        "btn_complaint": "Скардзіцца на {name}",
    },
    "uz": {
        "start_message": (
            "UMC — UGC xizmati.\n"
            "Biznes uchun — kreatorlarni tanlash, kreatorlar uchun — buyurtmalar."
        ),
        "support_response": (
            "Qo'llab-quvvatlash: @usemycontent\nHar qanday savollar uchun murojaat qiling!"
        ),
        "receipt_description": "Use My Content platforma xizmatlari",
        "btn_creator": "Men kreatorman",
        "btn_advertiser": "Menga UGC-kreatorlar kerak",
        "btn_support": "💬 Qo'llab-quvvatlash",
        "btn_my_orders": "📂 Mening buyurtmalarim",
        "btn_change_role": "Rolni o'zgartirish",
        "btn_create_profile": "Profil yaratish",
        "btn_advertiser_start": "Boshlash",
        "btn_create_order": "➕ Buyurtma yaratish",
        "btn_confirm_instagram": "✅ Instagram tasdiqlash",
        "btn_confirm_agreement": "✅ Rozilikni tasdiqlash",
        "btn_edit_profile": "Profilni tahrirlash",
        "btn_my_profile": "👤 Mening profilim",
        "btn_work_format_ads": "📢 Reklamani o'z akkauntimda joylashtirish",
        "btn_work_format_ugc_only": "❌ Faqat UGC (joylashtirishsiz)",
        "btn_phone_request": "📱 Telefon raqamini ulashish",
        "btn_location_request": "📍 Geolokatsiyani ulashish",
        "btn_location_map": "🗺 Xaritadan tanlash",
        "btn_city_picker": "Shaharni tanlash",
        "btn_edit_profile_blogger": "Bloger profilini tahrirlash",
        "btn_edit_profile_advertiser": "Reklamachi profilini tahrirlash",
        "btn_audience_f": "👩 Asosan ayollar",
        "btn_audience_m": "👨 Asosan erkaklar",
        "btn_audience_a": "👥 Aralash",
        "btn_gender_m": "Erkak",
        "btn_gender_f": "Ayol",
        "btn_age_0_17": "18 gacha",
        "btn_age_18_24": "18–24",
        "btn_age_25_34": "25–34",
        "btn_age_35_44": "35–44",
        "btn_age_45_99": "45+",
        "btn_barter_yes": "Ha",
        "btn_barter_no": "Yo'q",
        "btn_payout": "To'lov",
        "btn_back": "Orqaga",
        "btn_forward": "Oldinga",
        "btn_back_arrow": "⬅️ Orqaga",
        "btn_forward_arrow": "Oldinga ➡️",
        "btn_pay_order": "💳 №{creation_number} to'lash",
        "btn_open_profile": "🔗 Profilni ochish",
        "btn_write_telegram": "Telegramda yozish",
        "btn_ok_skipped": "Ok, o'tkazib yuborildi.",
        "order_type_ugc_only": "🎥 Brend uchun UGC-video",
        "order_type_ugc_placement": "📢 UGC + kreatorda joylashtirish",
        "order_photo_add": "📷 Foto qo'shish",
        "order_photo_skip": "⏭ O'tkazib yuborish",
        "coop_barter": "🎁 Barter",
        "coop_payment": "💰 To'lov",
        "coop_both": "🔄 Barter + to'lov",
        "content_social": "📱 Brend ijtimoiy tarmoqlarida",
        "content_ads": "📢 Reklamada (targhet, e'lonlar)",
        "content_both": "🔄 Ijtimoiy tarmoqlar va reklamada",
        "deadlines_3": "⏱ 3 kun ichida",
        "deadlines_7": "⏱ 7 kun ichida",
        "deadlines_14": "⏱ 14 kun ichida",
        # Messages: user/role
        "msg_user_not_found": "Foydalanuvchi topilmadi.",
        "msg_user_not_found_start": "Foydalanuvchi topilmadi. /start bilan boshlang.",
        "msg_registration_blocked": "Bloklangan foydalanuvchilar ro'yxatdan o'ta olmaydi.",
        "msg_registration_pause": "Pauza rejimidagi foydalanuvchilar ro'yxatdan o'ta olmaydi.",
        "msg_instagram_blocked": "Bloklangan foydalanuvchilar akkauntni tasdiqlay olmaydi.",
        "msg_instagram_pause": "Pauza rejimidagilar akkauntni tasdiqlay olmaydi.",
        "msg_complaint_blocked": "Bloklangan foydalanuvchilar shikoyat yubora olmaydi.",
        "msg_complaint_pause": "Pauza rejimidagi foydalanuvchilar shikoyat yubora olmaydi.",
        "msg_order_creation_blocked": "Bloklangan foydalanuvchilar buyurtma yarata olmaydi.",
        "msg_order_creation_pause": "Pauza rejimidagilar buyurtma yarata olmaydi.",
        "msg_payment_blocked": "Bloklangan foydalanuvchilar buyurtma to'lay olmaydi.",
        "msg_payment_pause": "Pauza rejimidagi foydalanuvchilar to'lay olmaydi.",
        "msg_feedback_blocked": "Bloklangan foydalanuvchilar izoh qoldira olmaydi.",
        "msg_feedback_pause": "Pauza rejimidagi foydalanuvchilar izoh qoldira olmaydi.",
        "msg_feedback_rate_blocked": "Bloklangan foydalanuvchilar baho bera olmaydi.",
        "msg_feedback_rate_pause": "Pauza rejimidagi foydalanuvchilar baho bera olmaydi.",
        # Feedback flow messages
        "msg_fb_thanks_saved": "Rahmat, javob saqlandi.",
        "msg_fb_thanks_feedback": "Fikr-mulohaza uchun rahmat.",
        "msg_fb_interaction_not_found": "Muloqot topilmadi.",
        "msg_fb_insufficient_rights": "Huquqlar yetarli emas.",
        "msg_fb_no_deal_question_blog": "Kelishuvga nega erisha olmadingiz?",
        "msg_fb_no_deal_question_adv": "Kelishuvga nega erisha olmadingiz?",
        "msg_fb_thanks_short": "Rahmat.",
        "msg_fb_issue_prompt": (
            "Muammoni tasvirlab bering va suhbat skrinshotlarini yoki "
            "boshqa dalillarni ilova qiling. Bu tushunishga yordam beradi.\n"
            "👉 Matn yozing, foto qo'shing va «Yuborish» tugmasini bosing."
        ),
        "msg_fb_postpone_max": (
            "Maksimal ko'chirish soni tugadi. "
            "Holat «Kelishilmadi» deb belgilandi."
        ),
        "msg_fb_postpone_72": "Tekshiruv 72 soatga ko'chirildi. Ko'chirishlar: {cnt}/{max_cnt}",
        "msg_fb_postpone_ok_blog": (
            "Yaxshi, keyinroq qaytamiz 👍 Buyurtmachi yozsa — javob bering."
        ),
        "msg_fb_postpone_ok_adv": (
            "Tushunarli, keyinroq qaytamiz 👍\n"
            "ℹ️ Kreator sizning kontaktlaringizni ko'rmaydi. "
            "Muloqotni siz boshlashingiz kerak."
        ),
        "msg_fb_ok_blog": (
            "Fikr-mulohaza uchun rahmat 👍 "
            "Yordam kerak bo'lsa — biz shu yerdamiz."
        ),
        "msg_fb_ok_adv": (
            "Fikr-mulohaza uchun rahmat 👍 Kreator bilan muvaffaqiyatli hamkorlik tilaymiz."
        ),
        "msg_fb_invalid_format": "Noto'g'ri format.",
        "msg_fb_invalid_response": "Noto'g'ri javob formati.",
        "msg_fb_invalid_status": "Noto'g'ri holat.",
        "msg_fb_invalid_id": "Noto'g'ri identifikator.",
        "msg_fb_error_try_later": "Xato yuz berdi. Keyinroq urinib ko'ring.",
        "msg_fb_no_deal_other_prompt": "Iltimos, sababni yozing:",
        "msg_fb_enter_reason_text": "Sababni matn ko'rinishida kiriting.",
        "msg_fb_session_expired": "Sessiya tugadi. Fikr-mulohaza savoliga qaytadan javob bering.",
        "msg_fb_session_expired_nps": "Sessiya tugadi. Baho savoliga qaytadan javob bering.",
        "msg_fb_error_try_again": "Xato. Qaytadan urinib ko'ring.",
        "msg_fb_add_description_photo": "Tavsif yoki foto qo'shing, so'ng «Yuborish» ni bosing.",
        "msg_fb_add_description_before_send": "Yuborishdan oldin tavsif yoki foto qo'shing.",
        "msg_fb_complaint_error": (
            "So'rov yaratishda xato yuz berdi. Qaytadan urinib ko'ring "
            "yoki menyu orqali qo'llab-quvvatlashga murojaat qiling."
        ),
        "msg_fb_complaint_accepted": (
            "Sizning so'rovingizni qabul qildik. Qo'llab-quvvatlash vaziyatni ko'rib chiqadi. "
            "Kerak bo'lsa, menyudagi «Qo'llab-quvvatlash» ni bosing."
        ),
        "msg_fb_nps_done_btn": "Tayyor",
        "msg_fb_nps_thank": (
            "Rahmat! 🙌\n"
            "Sizning fikringiz saqlandi va UMC platformasini yaxshilashga yordam beradi 🙏"
        ),
        "msg_fb_nps_question": "Iltimos, UMC platforma bilan ishlashni 1 dan 5 gacha baholang ⭐",
        "msg_fb_nps_prompt_5_adv": (
            "5 ⭐ bahosi uchun rahmat — UMC platforma sizga qulay bo'lgani uchun juda xursandmiz! 🙌\n"
            "Agar xizmatni yanada qulay qilish bo'yicha 1–2 fikringiz bo'lsa (interfeys, "
            "kreatorlarni tanlash, bildirishnomalar va h.k.) — javob yozing.\n"
            "Platformani rivojlantirish uchun har bir taklifni diqqat bilan o'qiymiz."
        ),
        "msg_fb_nps_prompt_5_blog": (
            "5 ⭐ bahosi uchun rahmat — UMC orqali buyurtmachilar bilan ishlash sizga qulay bo'lgani uchun xursandmiz! 🙌\n"
            "Agar xizmatni yaxshilash bo'yicha 1–2 fikringiz bo'lsa (shaxsiy kabinet, "
            "buyurtmalarni tanlash, shartlar, qo'llab-quvvatlash) — javob yozing.\n"
            "Platformani rivojlantirish uchun har bir taklifni diqqat bilan o'qiymiz."
        ),
        "msg_fb_nps_prompt_34_adv": (
            "Bahoyingiz uchun rahmat 🙏\n"
            "UMC bilan ishlashda nimani yaxshilash mumkinligini tushunish muhim.\n"
            "Iltimos, bitta xabarda yozing:\n"
            "– nima qoniqtirmadi (tanlash, tezlik, interfeys, muloqot)."
        ),
        "msg_fb_nps_prompt_34_blog": (
            "Bahoyingiz uchun rahmat 🙏\n"
            "UMC orqali buyurtmalar bilan ishlashda nimani yaxshilash mumkinligini tushunish muhim.\n"
            "Iltimos, bitta xabarda yozing:\n"
            "– nima qiyin yoki noqulay bo'ldi (shartlar, buyurtmachi bilan muloqot, interfeys, "
            "bildirishnomalar va h.k.)."
        ),
        "msg_fb_nps_prompt_1_adv": (
            "1 ⭐ qo'yganingiz uchun rahmat — bu bizga juda muhim 🙏\n"
            "UMC platforma bilan ishlash tajribangiz salbiy bo'lgani uchun juda afsusdamiz.\n"
            "Iltimos, bitta xabarda nima noto'g'ri bo'lganini tasvirlab bering:\n"
            "– kreator bilan muammolar;\n"
            "– platforma bilan qiyinchiliklar;\n"
            "– xatolar, kechikishlar, tushunmovchiliklar va h.k.\n"
            "Vaziyatni diqqat bilan ko'rib chiqamiz."
        ),
        "msg_fb_nps_prompt_1_blog": (
            "1 ⭐ qo'yganingiz uchun rahmat — bu bizga juda muhim 🙏\n"
            "UMC orqali ishlash tajribangiz salbiy bo'lgani uchun juda afsusdamiz.\n"
            "Iltimos, bitta xabarda nima bo'lganini tasvirlab bering:\n"
            "– buyurtmachi bilan muammolar;\n"
            "– shartlarning qiyinligi;\n"
            "– platforma texnik muammolari;\n"
            "– boshqa har qanday holat.\n"
            "Vaziyatni diqqat bilan ko'rib chiqamiz."
        ),
        "msg_fb_issue_send_btn": "📤 Yuborish",
        "msg_fb_feedback_ok": "✅ Hammasi yaxshi o'tdi",
        "msg_fb_feedback_no_deal": "❌ Kelishilmadi",
        "msg_fb_feedback_postpone": "⏳ Hali bog'lanmadi",
        "msg_fb_feedback_issue": "⚠️ Muammo / firibgarlik shubhasi",
        "msg_fb_no_deal_conditions": "💰 Shartlar bo'yicha kelisha olmadi",
        "msg_fb_no_deal_timing": "⏱ Muddatlar to'g'ri kelmadi",
        "msg_fb_no_deal_differed": "📝 Shartlar offerdan farq qildi",
        "msg_fb_no_deal_creator_change": "📝 Kreator shartlarni o'zgartirmoqchi bo'ldi",
        "msg_fb_no_deal_other": "🤝 Boshqa",
        "msg_fb_score_1_to_5": "Baho 1 dan 5 gacha bo'lishi kerak.",
        "msg_fb_thanks_for_rating": "Baho uchun rahmat!",
        "msg_fb_no_description": "Tavsif yo'q",
        # Feedback scheduler
        "msg_feedback_request_adv": (
            "Hammasi to'g'ri o'tganiga ishonch hosil qilmoqchimiz 🙌\n"
            "Kreator{creator_link} bilan bog'lana oldingizmi?\n"
            "Mos variantni tanlang:"
        ),
        "msg_feedback_request_blog": (
            "Hammasi to'g'ri o'tganiga ishonch hosil qilmoqchimiz 🙌\n"
            "Buyurtmachi {order_link_part} bilan bog'lana oldingizmi?"
        ),
        "msg_choose_role": "Rol tanlang: /role.",
        "msg_fill_profile_orders": (
            "Buyurtmalarni ko'rish uchun profilni to'ldiring (/advertiser yoki /creator)."
        ),
        "msg_confirm_agreement": (
            "Iltimos, platforma hujjatlariga roziligingizni tasdiqlang."
        ),
        "msg_agreements_intro_default": (
            "Profil yaratildi. Hujjatlarni o'qib chiqing va tasdiqlang."
        ),
        "msg_label_offer": "📄 Offer",
        "msg_label_privacy": "🔒 Maxfiylik siyosati",
        "msg_label_consent": "🧾 Shaxsiy ma'lumotlarni qayta ishlashga rozilik",
        "msg_confirm_docs_fallback": (
            "Platforma hujjatlariga roziligingizni tasdiqlang."
        ),
        "msg_no_orders": "Sizda hali buyurtmalar yo'q. /create_order",
        "msg_no_blogger_orders": (
            "Siz hali javob bermadingiz. Takliflar botga keladi."
        ),
        "msg_blogger_profile_empty": "Bloger profili to'ldirilmagan.",
        "msg_advertiser_profile_empty": "Reklamachi profili to'ldirilmagan.",
        "msg_advertiser_profile_fill": (
            "Reklamachi profili to'ldirilmagan. Buyruq: /advertiser"
        ),
        "msg_creator_profile_fill": "Profil to'ldirilmagan. Buyruq: /creator",
        "msg_confirm_instagram_first": "Javob berishdan oldin Instagram ni tasdiqlang.",
        "msg_confirm_agreement_first": "Avval rozilikni tasdiqlang.",
        # Messages: payments
        "msg_invalid_order_amount": "Buyurtma summasi noto'g'ri.",
        "msg_order_amount_too_large": (
            "Buyurtma summasi Telegram schyot-fakturasi uchun juda katta."
        ),
        "msg_invoice_failed": "Schyot-faktura yaratib bo'lmadi. Keyinroq urinib ko'ring.",
        "msg_pay_order_usage": "Foydalanish: /pay_order <order_id>",
        "msg_invalid_order_id": "Noto'g'ri order_id formati.",
        "msg_invalid_order_format": "Noto'g'ri buyurtma formati.",
        "msg_order_not_found": "Buyurtma topilmadi.",
        "msg_order_not_yours": "Buyurtma reklamachiga tegishli emas.",
        "msg_order_not_new": "Buyurtma NEW holatida emas.",
        "msg_pricing_not_configured": (
            "Narx sozlanmagan. Qo'llab-quvvatlashga murojaat qiling."
        ),
        "msg_payment_provider_not_configured": (
            "To'lov provayderi sozlanmagan."
        ),
        "msg_order_undetermined": "Buyurtmani aniqlab bo'lmadi.",
        "msg_title_payment": "Buyurtma to'lovi",
        # Messages: referral
        "msg_referral_payout_today": "Siz bugun allaqachon to'lov so'radingiz.",
        "msg_referral_payout_unavailable": (
            "To'lov mavjud emas: balans yo'q yoki so'rov mavjud."
        ),
        "msg_referral_payout_sent": "To'lov so'rovi qo'llab-quvvatlashga yuborildi.",
        "msg_referral_payout_notify_failed": (
            "So'rov yaratildi, lekin qo'llab-quvvatlashga xabar bera olmadi. "
            "Qo'llab-quvvatlashga qo'lda murojaat qiling."
        ),
        "msg_referral_payout_blocked": "Siz to'lov so'ray olmaysiz.",
        "msg_referral_payout_pause": "Pauza rejimidagi foydalanuvchilar to'lov so'ray olmaydi.",
        "msg_referral_no_users": "Sizda hali jalb qilingan foydalanuvchilar yo'q.",
        "msg_referral_access_denied": "Kirish taqiqlangan.",
        "msg_referral_blocked": "Bloklangan foydalanuvchilar buyruqdan foydalana olmaydi.",
        "msg_referral_pause": "Pauza rejimidagi foydalanuvchilar buyruqdan foydalana olmaydi.",
        "msg_referral_list_blocked": "Bloklangan foydalanuvchilar ro'yxatni ko'ra olmaydi.",
        "msg_referral_list_pause": "Pauza rejimidagi foydalanuvchilar ro'yxatni ko'ra olmaydi.",
        "msg_referral_list_title": (
            "Sizning referallaringiz (sahifa {page}/{total_pages}):"
        ),
        "msg_referral_list_empty": "Sizning referallaringiz: hali hech kim yo'q.",
        "msg_referral_pending_block": (
            "Kreator profilini to'ldirmagan (to'ldirishni eslatib turing):"
        ),
        "msg_referral_no_pending": "Profili yo'q referallar yo'q.",
        "msg_referral_link_intro": "Sizning referal havolangiz:",
        "lbl_referral_stats": "📊 Referal statistikasi",
        "lbl_referral_creators": "Jalb qilingan kreatorlar",
        "lbl_referral_orders": "Bajarilgan buyurtmalar",
        "lbl_referral_income_month": "Joriy oydagi daromad",
        "lbl_referral_income_total": "Jami to'plangan",
        "lbl_referral_paid": "To'langan",
        "lbl_referral_balance": "Joriy balans",
        "lbl_referral_orders_done": "buyurtma bajarildi",
        "msg_offer_new_response": (
            "Buyurtmangizga yangi javob 🙌\n\n"
            "👤 Kreator: {creator}\n"
            "📍 Shahar: {city}\n"
            "🎬 Format: {format}\n"
            "💼 Offer shartlarida ishlashga tayyor\n"
            "🔗 Kreator profili:\n{profile_url}"
        ),
        "lbl_creator_fallback": "Kreator",
        "lbl_phone_dash": "Telefon: —",
        "lbl_telegram_dash": "Telegram: —",
        "msg_offer_contacts_header": "📞 Buyurtmachi kontaktlari:\n\n",
        "msg_advertiser_new_response_what_next": (
            "🔔 Keyingi qadam\n\n"
            "💬 Kreatorga yozing va tafsilotlarni muhokama qiling\n"
            "✅ Kreator offerni o'qidi va ko'rsatilgan shartlarda ishlashga tayyor\n"
            "⏱ 30 daqiqa ichida bog'lanishni tavsiya qilamiz\n\n"
            "⚠️ Eslatma\n\n"
            "🧷 Offer shartlarini o'zgartirish tavsiya etilmaydi\n"
            "🔄 Shartlar o'zgarsa, kreator hamkorlikdan bosh tortishi mumkin\n"
            "➡️ Muloqot doimo sizdan boshlanadi"
        ),
        "msg_offer_response_blocked": "Bloklangan foydalanuvchilar offerga javob bera olmaydi.",
        "msg_offer_response_pause": "Pauza rejimidagi foydalanuvchilar offerga javob bera olmaydi.",
        "msg_advertiser_contacts_warning": (
            "⚠️ **Blogerlar bilan xavfsiz ishlash tartibi:**\n\n"
            "• Platforma oldindan to'lovni tavsiya etmaydi\n"
            "• Suv belgisi bor preview olgandan keyin to'lang\n"
            "• Yakuniy to'lovdan oldin kontent sifatini tekshiring\n"
            "• Muzokaralar va bitimlar — siz va bloger o'rtasida bevosita"
        ),
        # Messages: orders list
        "msg_my_orders_blocked": "Bloklangan foydalanuvchilar buyurtmalarni ko'ra olmaydi.",
        "msg_my_orders_pause": "Pauza rejimidagilar buyurtmalarni ko'ra olmaydi.",
        "msg_orders_title": "Sizning buyurtmalaringiz (sahifa {page}/{total_pages}):",
        "msg_orders_blogger_title": (
            "Siz javob bergan buyurtmalar (sahifa {page}/{total_pages}):"
        ),
        "msg_order_status": "Holat: {status_label}",
        "msg_order_creators": "Kreatorlar: {bloggers_needed}",
        "msg_order_matched": "Tanlangan: {matched_count} / {bloggers_needed}",
        "msg_order_date_created": "Yaratilgan sana: {date}",
        "msg_order_date_completed": "Tugatilgan sana: {date}",
        "msg_order_link": "Loyiha havolasi: {link}",
        "msg_order_format": "Format: {order_type}",
        "msg_order_type_ugc": "Brend uchun UGC-video",
        "msg_order_type_placement": "UGC + joylashtirish",
        "msg_order_price": "1 UGC narxi: {price}",
        "msg_order_barter": "Barter: {desc}",
        "msg_status_new": "Yaratilgan",
        "msg_status_pending_moderation": "Moderatsiyada",
        "msg_status_active": "Faol",
        "msg_status_closed": "Tugallangan",
        # Messages: blogger registration / profile
        "msg_choose_city": "Ro'yxatdan shahar tanlang.",
        "msg_choose_city_or_type": (
            "Yaqin yirik shaharni kiriting yoki «Shaharni tanlash» ni bosing"
        ),
        "msg_city_multiple_regions": (
            "Bu shahar bir nechta viloyatda bor. Viloyatni tanlang:"
        ),
        "msg_session_expired": "Sessiya tugadi. Qaytadan boshlang.",
        "msg_session_expired_orders": "Sessiya tugadi. «Buyurtma yaratish» dan qaytadan boshlang.",
        "msg_session_expired_profile": "Sessiya tugadi. «Mening profilim» ni qayta oching.",
        "msg_profile_not_found": "Profil topilmadi.",
        "msg_profile_not_found_role": "Profil topilmadi. /role orqali rol tanlang.",
        "msg_profile_incomplete": "Profil to'ldirilmagan.",
        "msg_choose_profile_edit": "Tahrirlash uchun profilni tanlang:",
        "msg_choose_section_edit": "Tahrirlash uchun bo'limni tanlang:",
        "msg_choose_section_keyboard": "Klaviaturadagi bo'limlardan birini tanlang.",
        "msg_profile_updated": "Profil yangilandi.",
        "msg_advertiser_profile_not_found": "Reklamachi profili topilmadi.",
        "msg_unknown_field": "Noma'lum maydon.",
        "msg_profile_update_failed": "Profilni yangilab bo'lmadi.",
        "err_city_not_place_use_map": (
            "Profilni yangilab bo'lmadi. Xaritada joylashuvingizni ko'rsating "
            "yoki geolokatsiyani ulashing."
        ),
        "err_instagram_format_example": "Noto'g'ri havola formati. Misol: instagram.com/name",
        "err_instagram_invalid": "Noto'g'ri Instagram havola formati.",
        "err_instagram_taken": "Bu Instagram allaqachon ro'yxatdan o'tgan. Boshqasini ishlating.",
        "msg_city_picker_edit": (
            "Yaqin yirik shaharni kiriting yoki «Shaharni tanlash» ni bosib ro'yxatdan tanlang."
        ),
        "msg_choose_buttons": "Tugmalardan birini tanlang.",
        "msg_name_updated": "Ism yangilandi.",
        # Profile display
        "lbl_profile_your": "👤 Sizning profilingiz",
        "lbl_profile_general": "📋 Umumiy ma'lumot",
        "lbl_profile_name": "Ism",
        "lbl_profile_roles": "Rollar",
        "lbl_profile_status": "Holat",
        "lbl_profile_blogger": "📸 Kreator profili",
        "lbl_profile_not_filled": "To'ldirilmagan",
        "lbl_profile_advertiser": "🏢 Reklamachi profili",
        "lbl_status_new": "Yangi",
        "lbl_status_active": "Faol",
        "lbl_status_pause": "Pauza",
        "lbl_status_blocked": "Bloklangan",
        "lbl_audience_male": "Erkaklar",
        "lbl_audience_female": "Ayollar",
        "lbl_audience_all": "Barchasi",
        "lbl_blogger_gender_male": "Erkak",
        "lbl_blogger_gender_female": "Ayol",
        "lbl_role_blogger": "Bloger",
        "lbl_role_advertiser": "Reklamachi",
        "lbl_yes": "Ha",
        "lbl_no": "Yo'q",
        "lbl_work_format_ads": "Reklamani o'z akkauntida joylashtirish",
        "lbl_work_format_ugc": "Faqat UGC",
        "lbl_instagram": "Instagram",
        "lbl_confirmed": "Tasdiqlangan",
        "lbl_city": "Shahar",
        "lbl_country": "Mamlakat",
        "lbl_region": "Viloyat",
        "lbl_gender": "Jins",
        "lbl_birth_date": "Tug'ilgan sana",
        "lbl_topics": "Mavzular",
        "lbl_audience": "Maqsadli auditoriya",
        "lbl_geo": "Geografiya",
        "lbl_price": "Narx",
        "lbl_barter": "Barter",
        "lbl_work_format": "Ish formati",
        "lbl_phone": "Telefon",
        "lbl_brand": "Brend",
        "lbl_activity": "Faoliyat",
        "lbl_site": "Sayt",
        "lbl_years": "yosh",
        # Profile edit prompts
        "prompt_edit_nickname": "Yangi ismni kiriting:",
        "prompt_edit_instagram_url": "instagram.com/name havolasini yuboring:",
        "prompt_edit_city": "Qaysi shahardan siz?",
        "prompt_edit_blogger_gender": "Jinsingizni ko'rsating:",
        "prompt_edit_birth_date": "Tug'ilgan sanani KK.OO.YYYY formatida kiriting (masalan 15.05.1995):",
        "prompt_edit_topics": "1–3 mavzuni vergul bilan kiriting:",
        "prompt_edit_audience_gender": "Asosan kim sizning kontentingizni ko'radi?",
        "prompt_edit_audience_age": "Auditoriyangizning asosiy yoshi?",
        "prompt_edit_audience_geo": "3 tagacha shaharni vergul bilan kiriting:",
        "prompt_edit_price": "1 UGC-video narxini kiriting ({currency}):",
        "prompt_edit_barter": "Barter asosida ishlashga tayyormisiz?",
        "prompt_edit_work_format": "Brendlar bilan qanday ishlashga tayyorsiz?",
        "prompt_edit_name": "Ismni kiriting:",
        "prompt_edit_phone": "Aloqa uchun telefon raqamini kiriting. Misol: 998901234567",
        "prompt_edit_brand": "Brendingiz / kompaniyangiz / biznesingiz nomi:",
        "prompt_edit_site_link": "Brend sayti, mahsulot yoki ijtimoiy tarmoq havolasi:",
        "prompt_edit_generic": "Yangi qiymatni kiriting:",
        "lbl_edit_nickname": "Ism",
        "lbl_edit_instagram": "Instagram",
        "lbl_edit_city": "Shahar",
        "lbl_edit_blogger_gender": "Jins",
        "lbl_edit_birth_date": "Tug'ilgan sana",
        "lbl_edit_topics": "Mavzular",
        "lbl_edit_audience_gender": "Auditoriya jinsi",
        "lbl_edit_audience_age": "Auditoriya yoshi",
        "lbl_edit_audience_geo": "Auditoriya geografiyasi",
        "lbl_edit_price": "Narx",
        "lbl_edit_barter": "Barter",
        "lbl_edit_work_format": "Ish formati",
        "lbl_edit_name": "Ism",
        "lbl_edit_phone": "Telefon",
        "lbl_edit_brand": "Brend",
        "lbl_edit_company_activity": "Kompaniya faoliyati",
        "lbl_edit_site_link": "Sayt havolasi",
        # Messages: advertiser registration
        "msg_whats_your_name": "Ismingiz nima?",
        "msg_choose_action": "Amalni tanlang:",
        "msg_what_city": "Qaysi shahardan siz?\nMisol: Toshkent / Samarqand / Buxoro",
        "msg_brand_name": "Brendingiz / kompaniyangiz / biznesingiz nomi:",
        "msg_company_activity": "Kompaniyangiz nima bilan shug'ullanadi?",
        "msg_brand_link": "Brend sayti, mahsulot yoki ijtimoiy tarmoq havolasi:",
        "msg_after_registration": (
            "Endi buyurtma joylashtirishingiz va UGC-kreatorlarni topishingiz mumkin."
        ),
        "msg_advertiser_intro": (
            "Siz «Menga UGC-kreatorlar kerak» rolini tanladingiz.\n"
            "Buyurtma joylashtirish uchun profil yaratamiz."
        ),
        "msg_creator_intro": (
            "Siz UGC-kreatorsiz. Brendlar kreatorlarni shu yerda qidiradi — to'liq profil "
            "tanlovga tushishga va mos buyurtmalar olishga yordam beradi.\n\n"
            "Bir necha daqiqada profilni to'ldiramiz — va siz tanlovda bo'lasiz."
        ),
        # Creator registration: step prompts
        "msg_step_ask_name": "Ismingiz nima?\n\nQadam 1 dan 12",
        "msg_step_ask_instagram": "instagram.com/name formatida havola yuboring\n\nQadam 2 dan 12",
        "msg_step_ask_instagram_first": "instagram.com/name formatida havola yuboring\n\nQadam 1 dan 12",
        "msg_step_ask_city": (
            "Buyurtmachilar kreatorlarni shahar bo'yicha tanlaydi: mahsulot yetkazib berish va "
            "oflayn uchrashuv uchun. Qaysi shahardan siz?\n\nQadam 3 dan 12"
        ),
        "msg_step_ask_birth_date": (
            "Tug'ilgan sanani KK.OO.YYYY formatida kiriting (masalan 15.05.1995):\n\nQadam 4 dan 12"
        ),
        "msg_step_ask_gender": "Jinsingizni ko'rsating:\n\nQadam 5 dan 12",
        "msg_step_ask_topics": (
            "Kontentingiz nima haqida?\n"
            "1–5 mavzuni vergul bilan kiriting: biznes, investitsiya, fitness, "
            "ovqatlanish, go'zallik, teri parvarishi, sayohat, taom, restoranlar, moda, "
            "uslub, bolalar, oila, texnologiya, gadjetlar, lajfstayl, tadbirlar, boshqa\n\nQadam 6 dan 12"
        ),
        "msg_step_ask_audience_gender": (
            "Asosan kim sizning kontentingizni ko'radi? "
            "Kuzatishlar yoki statistika bo'yicha\n\nQadam 7 dan 12"
        ),
        "msg_step_ask_audience_age": "Auditoriyangizning asosiy yoshi?\n\nQadam 8 dan 12",
        "msg_step_ask_audience_geo": (
            "Auditoriyangiz asosan qaysi shaharlarda? 3 tagacha shaharni vergul bilan, "
            "masalan: Toshkent, Samarqand, Buxoro\n\nQadam 9 dan 12"
        ),
        "msg_step_ask_price": (
            "Buyurtmachilar byudjet bo'yicha kreatorlarni tanlaydi — narxingiz bitimni tezlashtiradi. "
            "Bitta UGC-video qancha turadi? Narx ({currency}), masalan: 500, 1000, 2000\n\nQadam 10 dan 12"
        ),
        "msg_step_ask_barter": (
            "Ko'plab buyurtmalar barter asosida — «Ha» javobi offerlar sonini oshiradi. "
            "Ba'zan brendlar bilan barter asosida ishlashga tayyormisiz?\n\nQadam 11 dan 12"
        ),
        "msg_step_ask_work_format": (
            "UGC dan tashqari, brendlar bilan yana qanday ishlashga tayyorsiz? "
            "Tanlov oldidan oxirgi qadam.\n\nQadam 12 dan 12"
        ),
        "msg_agreements_intro_creator": (
            "Deyarli tayyor. "
            "Iltimos, hujjatlarni o'qib chiqing va roziligingizni tasdiqlang."
        ),
        "msg_profile_created": (
            "Profil yaratildi 👍\n\n"
            "Buyurtmachilar kreatorlarni qidirmoqda — to'liq profil offer olish imkoniyatini oshiradi.\n\n"
            "Oxirgi qadam — Instagram-akkauntni tasdiqlash. Bu quyidagilar uchun kerak:\n"
            "— brendlarni soxta akkauntlardan himoya qilish\n"
            "— profilingizga ishonchni oshirish\n"
            "— buyurtmalarni tezroq olish"
        ),
        "msg_instagram_already_registered": (
            "Bu Instagram akkaunt allaqachon ro'yxatdan o'tgan. "
            "Iltimos, boshqa akkauntdan foydalaning yoki qo'llab-quvvatlashga murojaat qiling."
        ),
        "msg_work_format_choose": (
            "Tugmalardan birini tanlang: Reklamani o'z akkauntimda joylashtirish "
            "yoki Faqat UGC (joylashtirishsiz)."
        ),
        "msg_registration_aborted": (
            "Ro'yxatdan o'tish to'xtatildi. Yakunlash uchun «Mening profilim» ni oching "
            "va rozilikni tasdiqlang."
        ),
        # Creator registration: validation errors
        "err_instagram_empty": (
            "Havola bo'sh bo'lishi mumkin emas. instagram.com/name formatida havola yuboring"
        ),
        "err_instagram_format": "Noto'g'ri format. instagram.com/name ko'rinishidagi havola kerak",
        "err_instagram_example": (
            "Noto'g'ri Instagram havola formati. Misol: https://instagram.com/name"
        ),
        "err_gender_choose": "Tugmalardan birini tanlang: Erkak yoki Ayol.",
        "err_audience_choose": (
            "Tanlang: Asosan ayollar, erkaklar yoki Aralash."
        ),
        "err_age_choose": "Yosh tugmalaridan birini tanlang.",
        "err_barter_choose": "Ha yoki Yo'q ni tanlang.",
        "err_price_number": "Raqam kiriting, masalan 500, 1000, 2000.",
        "err_geo_max_cities": "Vergul bilan 3 tagacha shahar kiriting.",
        # Validators (shared)
        "err_not_bot_command": (
            "Bot buyruqlarini javob sifatida ishlatmang. Matnni qaytadan kiriting."
        ),
        "err_offer_text_min": "Vazifani batafsil tasvirlab bering (kamida {min} belgi).",
        "err_offer_text_max": "Matn juda uzun (maksimal {max} belgi).",
        "err_barter_required": "Barter taklifini tasvirlab bering.",
        "err_barter_min": "Barterni tasvirlab bering (min. {min} belgi).",
        "err_barter_max": "Matn uzun (maks. {max} belgi).",
        "err_url_max": "Havola juda uzun (maksimal {max} belgi).",
        "err_url_scheme": "Havola kiriting (http:// yoki https://).",
        "err_url_invalid": "To'g'ri havola kiriting.",
        "err_url_example": (
            "To'g'ri havola kiriting (masalan, example.com yoki site.uz)."
        ),
        "err_product_link_empty": "Havola bo'sh bo'lishi mumkin emas. Qaytadan kiriting:",
        "err_geo_required": (
            "Bitta variant ko'rsating: shahar, viloyat yoki mamlakat. "
            "Misollar: Toshkent, O'zbekiston"
        ),
        "err_geo_max": "Matn juda uzun (maksimal {max} belgi).",
        "err_min_chars": "Kamida {min} belgi kiriting.",
        "err_max_chars": "Maksimal {max} belgi.",
        "err_phone_empty": "Telefon raqami bo'sh bo'lishi mumkin emas. Qaytadan kiriting:",
        "err_phone_digits": (
            "To'g'ri raqam kiriting (10–11 ta raqam). Misol: 998901234567"
        ),
        "err_phone_too_many": "Raqamlar juda ko'p. Misol: 998901234567",
        "err_phone_invalid": "To'g'ri raqam kiriting. Misol: 998901234567",
        "err_birth_date_empty": (
            "Tug'ilgan sanani KK.OO.YYYY formatida kiriting (masalan 15.05.1995)."
        ),
        "err_birth_date_format": (
            "Noto'g'ri format. KK.OO.YYYY dan foydalaning (masalan 15.05.1995)."
        ),
        "err_birth_date_digits": (
            "Sanani raqamlar bilan KK.OO.YYYY formatida kiriting (masalan 15.05.1995)."
        ),
        "err_birth_date_invalid": "Noto'g'ri sana. Kun, oy va yilni tekshiring.",
        "err_birth_date_future": "Tug'ilgan sana kelajakda bo'lishi mumkin emas.",
        "err_birth_date_min_age": "Yosh kamida {age} bo'lishi kerak.",
        "err_birth_date_max_age": (
            "Haqiqiy tug'ilgan sanani kiriting ({age} yoshgacha)."
        ),
        "err_city_required": "Shahanni ko'rsating. Qaytadan kiriting:",
        "err_city_from_location": "Geolokatsiya bo'yicha shaharni aniqlab bo'lmadi. Shahanni qo'lda kiriting yoki qaytadan urinib ko'ring.",
        "err_city_not_found_use_map": (
            "Nom bo'yicha joylashuvni aniqlab bo'lmadi. "
            "Shahar nomini to'g'ri kiriting yoki geolokatsiyani yuboring."
        ),
        "err_company_activity_max": "Maksimal {max} belgi.",
        "err_nickname_no_url": "Ism kiriting, Instagram havola emas.",
        "err_topics_empty": "Kamida bitta mavzu kiriting:",
        "err_topics_max": "{max} tagacha mavzu kiriting.",
        "err_audience_geo_empty": "Kamida bitta shahar ko'rsating. Qaytadan kiriting:",
        "err_audience_geo_max": "Maksimal {max} belgi.",
        "err_price_positive": "Narx 0 dan katta bo'lishi kerak.",
        "err_price_max": (
            "Summa ruxsat etilgan maksimaldan oshib ketdi ({max} {currency})."
        ),
        # Messages: order creation
        "msg_what_do_you_need": "Sizga nima kerak?",
        "msg_choose_from_keyboard": "Klaviaturadagi variantlardan birini tanlang.",
        "msg_coop_format": "Qaysi hamkorlik formati sizga mos?",
        "msg_enter_number": "Raqam kiriting, masalan 1500.",
        "msg_how_many_creators": "Sizga nechta kreator kerak?",
        "msg_product_link": "Mahsulot havolasini kiriting (javob bergan kreatorlar uchun):",
        "msg_choose_count": "Qiymatlardan birini tanlang: {counts}.",
        "msg_where_use_ugc": "UGC-videoni qaerda ishlatmoqchisiz?",
        "msg_send_photo": "Mahsulot fotosini yuboring:",
        "msg_order_task_description": (
            "Kreatorlar uchun vazifani qisqacha tasvirlab bering.\n"
            "Nima va qanday formatda suratga olish. Misol: Qadoqlovchi video."
        ),
        "msg_order_budget": (
            "1 UGC-video uchun byudjet? Narxni kiriting ({currency}): 500, 1000, 2000"
        ),
        "msg_order_barter_ask": (
            "Barter sifatida nima taklif qilasiz?\n"
            "Brend mahsuloti (qisqacha tasvirlab bering) + yetkazib berish"
        ),
        "msg_order_photo_intro": (
            "Foto ilova qiling (ixtiyoriy).\n"
            "Rasm kreatorga buyurtmani tezroq tushunishga yordam beradi va javob berishni oshiradi"
        ),
        "msg_order_photo_choose": (
            "Klaviaturada «Foto qo'shish» yoki «O'tkazib yuborish» ni tanlang, "
            "yoki mahsulot fotosini yuboring."
        ),
        "msg_order_deadline": (
            "Kontentni qachon tayyorlashingiz kerak? "
            "Kelishuvdan necha kun o'tgach preview kutayotganingizni ko'rsating."
        ),
        "msg_order_geo": (
            "Kreator qaysi shahar, viloyat yoki mamlakatda bo'lishi mumkin? "
            "Bitta variant ko'rsating: masalan, Toshkent, Farg'ona yoki O'zbekiston. "
            "Barter buyurtmalari va mahsulot yetkazib berish uchun kerak."
        ),
        # Messages: Instagram
        "msg_profile_empty_creator": (
            "Profil to'ldirilmagan. «Profil yaratish» yoki /creator"
        ),
        "msg_instagram_already_confirmed": "Sizning Instagram-akkauntingiz allaqachon tasdiqlangan",
        "msg_instagram_verify_instruction": (
            "<b>Instagram-akkauntni tasdiqlash uchun 3 qadam bajaring:</b>\n\n"
            "1. Quyidagi kodni nusxalang\n"
            "2. Uni UMC Instagram-akkauntiga shaxsiy xabar sifatida yuboring\n"
            "3. Avtomatik tasdiqlashni kuting\n\n"
            '🔗 Instagram UMC: <a href="{url}">{url}</a>\n\n'
            "🔐 Sizning kodingiz (kod 15 daqiqa amal qiladi) 👇"
        ),
        # Messages: complaints
        "msg_invalid_format": "Noto'g'ri format.",
        "msg_invalid_id_format": "Noto'g'ri identifikator formati.",
        "msg_order_not_found_short": "Buyurtma topilmadi.",
        "msg_no_bloggers_complain": "Shikoyat qilish uchun blogerlar yo'q.",
        "msg_complain_on": "{blogger_name} ga shikoyat qilish",
        "msg_choose_blogger_complain": (
            "Shikoyat qilmoqchi bo'lgan blogerni tanlang:"
        ),
        "msg_no_access_order": "Sizda bu buyurtmaga kirish huquqi yo'q.",
        "msg_choose_complaint_reason": "Shikoyat sababini tanlang:",
        "msg_complaint_no_bloggers": "Shikoyat qilish uchun blogerlar yo'q.",
        "msg_invalid_user_id": "Noto'g'ri foydalanuvchi identifikatori.",
        "msg_invalid_reason": "Noto'g'ri sabab.",
        "msg_data_error": "Ma'lumotlarni qayta ishlashda xato.",
        "msg_describe_complaint": "Shikoyat sababini tasvirlab bering:",
        "msg_error_try_later": "Xato yuz berdi. Keyinroq urinib ko'ring.",
        "msg_enter_complaint_reason": "Iltimos, shikoyat sababini kiriting.",
        # Messages: offer responses
        "msg_order_closed": "Buyurtma allaqachon yopilgan.",
        "msg_order_closed_full": (
            "❗ Buyurtma allaqachon yopilgan\n\n"
            "Javob berganingiz uchun rahmat — bu buyurtma bo'yicha barcha kreatorlar allaqachon tanlangan.\n\n"
            "Yangi buyurtmalar paydo bo'lishi bilan albatta yuboramiz.\n\n"
            "Botdagi bildirishnomalarni kuzatib boring 🙌"
        ),
        "msg_blogger_after_response_what_next": (
            "⏳ Keyingi qadam\n\n"
            "💬 Buyurtmachidan xabar kuting — u Instagram havolangizni oldi "
            "va birinchi o'zi yozadi\n"
            "📩 Direct so'rovlarini tekshiring\n"
            "👀 Namoyish uchun suv belgisi bor previewdan foydalaning\n"
            "💸 Previewni tasdiqlashdan keyin to'lovni oling\n"
            "🎥 Yakuniy UGC-rolikni faqat to'lovdan keyin yuboring\n"
            "❗ Agar buyurtmachi offer shartlarini o'zgartirmasa, javobdan so'ng rad etish\n"
            " akkaunt chekloviga olib kelishi mumkin\n"
            "🤝 Platforma muzokaralar va to'lovda ishtirok etmaydi."
        ),
        "msg_offer_accepted": "Javob qabul qilindi! Reklamachining xabarini kuting.",
        "msg_offer_order_filled": (
            "Joriy kreatorlar ro'yxati yopilgan. Sizni kutish ro'yxatiga qo'shdik — "
            "kreatorni almashtirish kerak bo'lsa yoki buyurtmachi ro'yxatni kengaytirsa, "
            "birinchi bo'lib sizga taklif yuboramiz."
        ),
        "msg_offer_order_filled_toast": "Kutish ro'yxatiga yozildi",
        "msg_advertiser_after_payment_success": (
            "To'lov muvaffaqiyatli o'tdi ✅\n\nBuyurtmangiz bo'yicha kreatorlarni tanlash faollashtirildi."
        ),
        "msg_advertiser_after_payment_what_next": (
            "🔄 **Keyingi qadam**\n\n"
            "📩 Kreatorlar offeringizni oladi\n"
            "🔗 Siz ularning profil havolalari bilan javoblar olasiz\n"
            "💬 Tanlangan kreatorlar bilan o'zingiz bog'lanasiz"
        ),
        "msg_advertiser_after_payment_important": (
            "⚠️ **Muhim**\n\n"
            "🧷 Nashr qilgandan keyin offer shartlarini o'zgartirish tavsiya etilmaydi\n"
            "🔄 Shartlar o'zgarsa, kreator hamkorlikdan bosh tortishi mumkin\n"
            "🤝 Platforma bitim tomoni emas\n"
            "💸 Kreatorlarga to'lovni bevosita o'zingiz amalga oshirasiz\n"
            "👀 Suv belgisi bor previewni ko'rgandan keyin to'lang\n"
            "🚫 Platforma kreatorlar uchun javobgar emas"
        ),
        "msg_phone_request": (
            "Buyurtma bo'yicha aloqa uchun telefon raqamini kiriting.\n"
            "Quyidagi tugmani bosing yoki raqamni qo'lda kiriting "
            "(misol: 998901234567)."
        ),
        "msg_instagram_confirmed": (
            "Instagram tasdiqlandi ✅. Brendlar taklif yuborishi mumkin."
        ),
        "msg_instagram_mismatch": (
            "Profilingizdagi Instagram kod yuborgan akkaunt bilan mos kelmadi. "
            "«Mening profilim» ni oching, "
            "bloger profilini tahrirlang va to'g'ri Instagram kiriting."
        ),
        "msg_too_many_requests": "Juda ko'p so'rovlar. Keyinroq urinib ko'ring.",
        "msg_invalid_order_id_short": "Noto'g'ri buyurtma identifikatori.",
        # Messages: admin / moderation
        "msg_order_activated": "Buyurtma faollashtirildi, blogerlarga yuborilmoqda.",
        # Error middleware (user-facing)
        "err_user_not_found": "Foydalanuvchi topilmadi.",
        "err_blogger_registration": "Bloger ro'yxatdan o'tishda xato.",
        "err_advertiser_registration": "Reklamachi ro'yxatdan o'tishda xato.",
        "err_order_not_found": "Buyurtma topilmadi.",
        "err_order_not_active": "Buyurtma faol emas.",
        "err_order_creation": "Buyurtma yaratishda xato.",
        "err_order_already_responded": "Siz bu buyurtmaga allaqachon javob berdingiz.",
        "err_order_response_limit": "Buyurtma bo'yicha javoblar limiti tugadi.",
        "err_order_not_new": "Buyurtma NEW holatida emas.",
        "err_order_not_yours": "Buyurtma reklamachiga tegishli emas.",
        "err_order_invalid_id": "Noto'g'ri buyurtma identifikatori.",
        "msg_offer_skipped": "Ok, o'tkazib yuborildi.",
        "err_interaction_not_found": "Muloqot topilmadi.",
        "err_interaction": "Muloqotda xato.",
        "err_interaction_status": "Muloqot ISSUE holatida emas.",
        "err_interaction_resolution": "Qo'lda hal qilish uchun noto'g'ri holat.",
        "err_complaint_exists": "Siz bu buyurtma bo'yicha allaqachon shikoyat qildingiz.",
        "err_complaint_not_found": "Shikoyat topilmadi.",
        "err_price_exceeds": "Summa maksimaldan oshib ketdi ({amount} {currency}).",
        "err_generic": "Xato yuz berdi: {error}",
        # Feedback
        "msg_feedback_thanks": "Rahmat, javob saqlandi.",
        "msg_feedback_thanks_short": "Fikr-mulohaza uchun rahmat.",
        "msg_interaction_not_found": "Muloqot topilmadi.",
        "msg_insufficient_rights": "Huquqlar yetarli emas.",
        "msg_feedback_thanks_ok": "Rahmat.",
        "msg_describe_problem": (
            "Muammoni tasvirlab bering va suhbat skrinshotlarini yoki "
            "boshqa dalillarni ilova qiling. Bu tushunishga yordam beradi.\n"
        ),
        "msg_postpone_max": (
            "Maksimal ko'chirish soni tugadi. "
            "Holat «Kelishilmadi» deb belgilandi."
        ),
        "msg_postpone_72": "Tekshiruv 72 soatga ko'chirildi. Ko'chirishlar: {cnt}/{max}",
        "msg_session_expired_feedback": (
            "Sessiya tugadi. Fikr-mulohaza savoliga qaytadan javob bering."
        ),
        "msg_error_try_again": "Xato. Qaytadan urinib ko'ring.",
        "msg_add_description_or_photo": (
            "Tavsif yoki foto qo'shing, so'ng «Yuborish» ni bosing."
        ),
        "msg_add_description_before_send": "Yuborishdan oldin tavsif yoki foto qo'shing.",
        "msg_complaint_error": (
            "So'rov yaratishda xato yuz berdi. Qaytadan urinib ko'ring "
            "yoki menyu orqali qo'llab-quvvatlashga murojaat qiling."
        ),
        "msg_complaint_received": (
            "Sizning so'rovingizni qabul qildik. Qo'llab-quvvatlash vaziyatni ko'rib chiqadi. "
            "Kerak bo'lsa, menyudagi «Qo'llab-quvvatlash» ni bosing."
        ),
        "msg_enter_reason": "Iltimos, sababni yozing:",
        "msg_enter_reason_text": "Sababni matn ko'rinishida kiriting.",
        "msg_nps_thanks": "Baho uchun rahmat!",
        "msg_nps_question": "Bizni tavsiya etishga qanchalik tayyorsiz? (1–5)",
        "msg_nps_thank": "Rahmat! Sizning fikringiz bizga juda muhim.",
        "msg_invalid_format_short": "Noto'g'ri format.",
        "msg_invalid_id": "Noto'g'ri identifikator.",
        "msg_score_1_to_5": "Baho 1 dan 5 gacha bo'lishi kerak.",
        "msg_invalid_status": "Noto'g'ri holat.",
        "msg_invalid_response": "Noto'g'ri javob formati.",
        "msg_error_later": "Xato yuz berdi. Keyinroq urinib ko'ring.",
        # Admin message to user
        "msg_cancelled": "Bekor qilindi.",
        "msg_invalid_uuid": "Noto'g'ri foydalanuvchi identifikatori.",
        "msg_user_not_telegram": "Foydalanuvchi Telegramda yo'q.",
        # Language/country selection
        "language_prompt": "Tilni tanlang / Choose language:",
        "country_prompt": "Mamlakatni tanlang:",
        # Offer texts
        "offer_header": "Yangi buyurtma",
        "offer_details_header": "📋 Buyurtma tafsilotlari:",
        "offer_format": "🎥 Format: {format_label}",
        "offer_task": "📝 Vazifa: {task}",
        "offer_budget": "💰 Byudjet: {price} {currency} 1 UGC-video uchun",
        "offer_barter": "🎁 Barter: {description}",
        "offer_content_usage": "📢 Foydalanish: {usage}",
        "offer_deadlines": "⏱ Muddatlar: {deadlines}",
        "offer_geography": "📍 Geografiya: {geography}",
        "offer_bloggers_needed": "👥 Kreatorlar kerak: {count}",
        "offer_warning": (
            "⚠️ Muhim\n"
            "🧷 Faqat ko'rsatilgan shartlarda ishlashga tayyor bo'lsangiz javob bering\n"
            "❗ Buyurtmachi shartlarni o'zgartirmasa, javobdan so'ng rad etish"
            "   shikoyat va akkaunt chekloviga olib kelishi mumkin"
        ),
        "offer_how_it_works": (
            "⏳ Qanday ishlaydi\n"
            "● Siz offerga javob berasiz\n"
            "● Mahsulot havolasini olasiz\n"
            "● Buyurtmachi profilingizni oladi va birinchi o'zi yozadi\n"
            "● Platforma muzokaralar va to'lovda ishtirok etmaydi"
        ),
        "offer_format_label_ugc_placement": "UGC + joylashtirish",
        "offer_format_label_ugc_only": "Brend uchun UGC-video",
        "btn_offer_accept": "UGC suratga olishga tayyor",
        "btn_offer_skip": "O'tkazib yuborish",
        # Complaint button
        "btn_complaint": "{name} ga shikoyat qilish",
    },
}

# Fill missing keys for kk/be/uz so all locales have full key set
for _k in DEFAULT_TEXTS["ru"]:
    if _k not in DEFAULT_TEXTS["kk"]:
        DEFAULT_TEXTS["kk"][_k] = DEFAULT_TEXTS["ru"][_k]
    if _k not in DEFAULT_TEXTS["be"]:
        DEFAULT_TEXTS["be"][_k] = DEFAULT_TEXTS["ru"][_k]
for _k in DEFAULT_TEXTS["en"]:
    if _k not in DEFAULT_TEXTS["uz"]:
        DEFAULT_TEXTS["uz"][_k] = DEFAULT_TEXTS["en"][_k]

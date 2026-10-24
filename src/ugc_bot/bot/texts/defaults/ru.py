"""RU locale texts."""

RU: dict[str, str] = {
    # Start & support
    "start_message": (
        "UMC — сервис для UGC.\nБизнесу — подбор креаторов, креаторам — заказы."
    ),
    "support_response": (
        "Служба поддержки: @usemycontent\nОбращайтесь по любым вопросам!"
    ),
    "support_chat_prompt": (
        "Напишите ваше сообщение, и мы ответим в ближайшее время."
    ),
    "support_chat_sent": "Сообщение отправлено в поддержку.",
    "support_chat_reply_header": "Ответ от поддержки:",
    "support_chat_exit": "Вы вышли из чата с поддержкой.",
    "support_chat_not_configured": "Чат поддержки временно недоступен.",
    "btn_support_write": "✍️ Написать в поддержку",
    "btn_support_exit": "❌ Завершить диалог",
    "receipt_description": "Услуги платформы Use My Content",
    # Role selection buttons
    "btn_creator": "Я креатор",
    "btn_advertiser": "Мне нужны UGC‑креаторы",
    # Common buttons
    "btn_support": "💬 Поддержка",
    "btn_my_orders": "📂 Мои заказы",
    "btn_change_role": "Смена роли",
    "btn_create_profile": "Создать профиль",
    "btn_partner_program": "Партнёрская программа",
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
    "btn_write_max": "Написать в Макс",
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
    "msg_account_linked": "Мы нашли ваш аккаунт! Все данные сохранены. Теперь вы можете продолжить работу в Max.",
    "btn_retry_instagram": "Указать другой инстаграм",
    "btn_open_direct": "Открыть директ",
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
        "Спасибо за обратную связь 👍 Если понадобится помощь — мы на связи."
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
    "msg_payment_provider_not_configured": ("Платежный провайдер не настроен."),
    "msg_order_undetermined": "Не удалось определить заказ.",
    "msg_title_payment": "Оплата заказа",
    "btn_pay_invoice": "Оплатить {amount}",
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
    "lbl_referral_income_line": "• {amount} {symbol} ({count} заказов)",
    "lbl_referral_approx_total": "≈ {amount} {symbol} (примерный итог)",
    "lbl_referral_paid_currency": "Выплачено: {amount} {symbol}",
    "lbl_referral_pending_currency": "В ожидании: {amount} {symbol}",
    "btn_referral_payout_currency": "Выплатить {amount} {symbol}",
    "msg_referral_payout_today_currency": "Вы уже подавали заявку на вывод {currency} сегодня.",
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
        "Введите корректный номер с кодом страны. "
        "Пример: +79001110777 или +998901234567"
    ),
    "err_phone_too_many": (
        "Слишком много цифр. Пример: +79001110777 или +998901234567"
    ),
    "err_phone_invalid": (
        "Введите корректный номер с кодом страны. "
        "Пример: +79001110777 или +998901234567"
    ),
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
    "msg_order_created": (
        "Заказ создан ✅\n\n"
        "Мы отправим предложение подходящим UGC-креаторам после оплаты.\n\n"
        "🔄 **Как это работает**\n\n"
        "• Креаторы получают оффер с зафиксированными условиями\n"
        "• Откликаются только те, кто готов работать на ваших условиях\n"
        "• Вы получите отклики со ссылками на профили креаторов\n"
        "• Связь начинается с вашей стороны\n\n"
        "⚠️ **Важно**\n\n"
        "• Оплату креатору рекомендуем производить после превью с водяным знаком\n"
        "• Платформа не участвует в переговорах и оплате\n"
        "• Мы не гарантируем, что креатор не изменит своё решение\n"
        "• Креатор не видит ваши контакты и не может написать первым"
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
    "msg_offer_response_unavailable": (
        "Подтверждение отклика сейчас недоступно. Попробуйте позже."
    ),
    "msg_offer_response_verification_required": (
        "Подтвердите Instagram в профиле и повторите отклик."
    ),
    "msg_offer_response_identity_used": (
        "Этот Instagram уже есть в откликах на заказ."
    ),
    "msg_blogger_selection_interest_saved": (
        "Отклик сохранён. Ожидайте сообщения заказчика.\n\n"
        "Условия работы и гонорар согласуйте напрямую. Показывайте превью "
        "с водяным знаком; финальный материал отправляйте после оплаты."
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
    "msg_instagram_account_lost": (
        "Ваш Instagram-аккаунт был удалён или изменён. "
        "Для получения заказов отредактируйте профиль "
        "и пройдите верификацию заново."
    ),
    "msg_instagram_verification_api_unavailable": (
        "Не удалось проверить ваш Instagram-аккаунт. "
        "Попробуйте пройти верификацию позже или напишите "
        "в чат поддержки."
    ),
    "msg_instagram_link_conflict": (
        "Instagram подтверждён. Аккаунты не привязаны: это отдельные "
        "аккаунты. Для решения вопроса обратитесь в поддержку."
    ),
    "msg_instagram_link_unavailable": (
        "Instagram подтверждён, но привязать аккаунт MAX сейчас не удалось. "
        "Обратитесь в поддержку."
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
    "msg_offer_skip_reason_prompt": "Укажите причину отказа:",
    "btn_reject_low_price": "Низкая цена",
    "btn_reject_wrong_format": "Не подходит формат рекламы",
    "btn_reject_uninteresting": "Неинтересный продукт / предложение",
    "btn_reject_no_time": "Нет времени",
    "btn_reject_already_working": "Уже работаю с брендом напрямую",
    "msg_enter_desired_price": "Укажите, за какую стоимость вы готовы разместить рекламу:",
    "msg_invalid_price": "Введите число от {min} до {max} {currency}",
    "msg_offer_skipped_with_reason": "Спасибо за обратную связь. Вы отказались: {reason}. Пропущено.",
    "msg_offer_skipped_low_price": "Спасибо за обратную связь. Вы отказались: Низкая цена. Желаемая сумма: {price} {currency}. Мы можем вернуться с новым предложением.",
    "msg_manager_low_price_notification": "Блогер {blogger} отказался: низкая цена. Готов за {desired_price} {currency} (в оффере: {offer_price} {currency}).\n{product_link}",
    "btn_cancel_price_entry": "Отмена",
    "msg_price_entry_cancelled": "Отказ записан. Пропущено.",
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
    "country_changed": "Страна изменена.",
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
    "btn_offer_confirm": "Готов",
    "btn_offer_cancel": "Отмена",
    "msg_offer_brief_link": "📋 Ссылка на ТЗ:",
    "msg_offer_confirm_response": (
        "Подтвердите отклик\n\n"
        "Нажимая «Готов», вы подтверждаете, что:\n\n"
        "- внимательно прочитали ТЗ\n"
        "- готовы выполнить заказ на указанных условиях\n\n"
        "Если после отклика вы не отвечаете заказчику или отказываетесь "
        "от выполнения без объективной причины, это фиксируется системой. "
        "Повторные случаи могут привести к ограничению доступа к новым заказам.\n\n"
        "Если есть вопросы по ТЗ — рекомендуем уточнить их "
        "в поддержке (http://t.me/usemycontent) до отклика."
    ),
    "msg_offer_confirm_cancelled": "Отклик отменён",
    "msg_ugc_video_saved_creator": "✅ Ваше видео принято менеджером и сохранено.",
    "msg_ugc_video_saved_advertiser": (
        "✅ Креатор {telegram} успешно выполнил заказ!\nСсылка на видео: {url}"
    ),
    # Manager: creator order management
    "msg_creator_removed_from_order": (
        "К сожалению, вы были убраны из заказа менеджером."
    ),
    "msg_creator_added_to_order": (
        "Вас добавили в заказ! Ваш менеджер: {manager_telegram}. "
        "Ждём вашего видео."
    ),
    # Complaint button
    "btn_complaint": "Пожаловаться на {name}",
}

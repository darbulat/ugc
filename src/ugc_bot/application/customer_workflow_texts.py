"""Localized customer reminders and their editable button labels."""

FOLLOWUP_TEXTS = {
    "ru": (
        "✨ Найдём авторов для вашей задачи?\n\n"
        "Расскажите, какой контент нужен вашему бренду, и начните "
        "подбор в Use My Content.",
        "💬 Поможем с подбором авторов\n\n"
        "Есть вопросы по условиям или оформлению? Напишите нам — "
        "поможем разобраться и выбрать следующий шаг.",
        "🤝 Подберём удобный формат работы\n\n"
        "Можно начать с автоподбора или подключить сопровождение "
        "менеджера. Поможем выбрать вариант под вашу задачу и бюджет.\n\n"
        "Посмотрите услуги или напишите нам, чтобы обсудить детали.",
        "Продолжить",
    ),
    "en": (
        "✨ Ready to find creators for your brand?\n\n"
        "Tell us what content your brand needs and start your "
        "creator selection with Use My Content.",
        "💬 Need help choosing creators?\n\n"
        "Have questions about the terms or placing an order? "
        "Message us and we’ll help you work out the next step.",
        "🤝 Let’s find the right way to work together\n\n"
        "Start with automatic selection or add manager support. "
        "We’ll help you choose an option for your goals and budget.\n\n"
        "Explore our services or message us to discuss the details.",
        "Continue",
    ),
    "kk": (
        "✨ Мақсатыңызға сай авторларды табайық па?\n\n"
        "Брендіңізге қандай контент қажет екенін айтыңыз және "
        "Use My Content арқылы авторларды іріктеуді бастаңыз.",
        "💬 Авторларды таңдауға көмектесеміз\n\n"
        "Шарттар немесе тапсырыс беру туралы сұрақтарыңыз бар ма? "
        "Бізге жазыңыз — түсіндіріп, келесі қадамды таңдауға көмектесеміз.",
        "🤝 Ыңғайлы жұмыс форматын таңдайық\n\n"
        "Автоматты іріктеуден бастауға немесе менеджердің сүйемелдеуін "
        "қосуға болады. Мақсатыңыз бен бюджетіңізге сай нұсқаны "
        "таңдауға көмектесеміз.\n\n"
        "Қызметтерді қараңыз немесе егжей-тегжейін талқылау үшін жазыңыз.",
        "Жалғастыру",
    ),
    "be": (
        "✨ Знойдзем аўтараў для вашай задачы?\n\n"
        "Раскажыце, які кантэнт патрэбны вашаму брэнду, і пачніце "
        "падбор у Use My Content.",
        "💬 Дапаможам з падборам аўтараў\n\n"
        "Ёсць пытанні пра ўмовы ці афармленне? Напішыце нам — "
        "дапаможам разабрацца і выбраць наступны крок.",
        "🤝 Падбяром зручны фармат працы\n\n"
        "Можна пачаць з аўтападбору або падключыць суправаджэнне "
        "менеджара. Дапаможам выбраць варыянт пад вашу задачу і бюджэт.\n\n"
        "Паглядзіце паслугі або напішыце нам, каб абмеркаваць дэталі.",
        "Працягнуць",
    ),
    "uz": (
        "✨ Maqsadingizga mos mualliflarni topamizmi?\n\n"
        "Brendingizga qanday kontent kerakligini ayting va "
        "Use My Content orqali mualliflarni tanlashni boshlang.",
        "💬 Mualliflarni tanlashda yordam beramiz\n\n"
        "Shartlar yoki buyurtma berish bo‘yicha savollaringiz bormi? "
        "Bizga yozing — tushuntirib, keyingi qadamni tanlashga yordam beramiz.",
        "🤝 Qulay ish shaklini tanlaymiz\n\n"
        "Avtomatik tanlovdan boshlang yoki menejer yordamini qo‘shing. "
        "Maqsadingiz va budjetingizga mos variantni tanlashga yordam "
        "beramiz.\n\n"
        "Xizmatlarni ko‘ring yoki tafsilotlarni muhokama qilish uchun yozing.",
        "Davom etish",
    ),
}

FOLLOWUP_ACTIONS = {
    "ru": ("Посмотреть услуги", "💬 Поддержка"),
    "en": ("Explore services", "💬 Support"),
    "kk": ("Қызметтерді қарау", "💬 Қолдау"),
    "be": ("Паглядзець паслугі", "💬 Падтрымка"),
    "uz": ("Xizmatlarni ko‘rish", "💬 Yordam"),
}


def bot_text_defaults() -> dict[str, dict[str, str]]:
    return {
        locale: {
            **{
                f"customer_followup_{index}": values[index - 1]
                for index in (1, 2, 3)
            },
            "customer_followup_action": values[3],
            "customer_followup_services_action": FOLLOWUP_ACTIONS[locale][0],
            "customer_followup_support": FOLLOWUP_ACTIONS[locale][1],
        }
        for locale, values in FOLLOWUP_TEXTS.items()
    }

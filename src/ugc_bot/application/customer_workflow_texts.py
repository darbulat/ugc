"""Fallback copy for BotTextsService keys customer_followup_1/2/3/action."""

FOLLOWUP_TEXTS = {
    "ru": (
        "Уточним вашу задачу и подберём авторов. Вернитесь к "
        "заказу, чтобы продолжить.",
        "Нужна помощь с подбором авторов? Менеджер поможет уточнить "
        "условия и следующий шаг.",
        "Обсудим подходящий формат работы с авторами и экономику "
        "вашей задачи. Оставьте заявку команде.",
        "Продолжить",
    ),
    "en": (
        "Tell us about your goal and continue your creator order.",
        "Need help choosing creators? A manager can help with the "
        "brief and next step.",
        "Let’s discuss the right creator format and economics for "
        "your goal. Contact our team.",
        "Continue",
    ),
    "kk": (
        "Мақсатыңызды нақтылап, авторларды таңдайық. Тапсырысты жалғастырыңыз.",
        "Авторларды таңдауға көмек керек пе? Менеджер шарттар мен "
        "келесі қадамды нақтылайды.",
        "Авторлармен жұмыстың қолайлы форматы мен экономикасын "
        "талқылайық. Командаға өтінім қалдырыңыз.",
        "Жалғастыру",
    ),
    "be": (
        "Удакладнім вашу задачу і падбяром аўтараў. Вярніцеся да замовы.",
        "Патрэбна дапамога з падборам аўтараў? Менеджар дапаможа "
        "ўдакладніць умовы і наступны крок.",
        "Абмяркуем фармат працы з аўтарамі і эканоміку вашай "
        "задачы. Пакіньце заяўку камандзе.",
        "Працягнуць",
    ),
    "uz": (
        "Maqsadingizni aniqlab, mualliflarni tanlaymiz. Buyurtmani "
        "davom ettiring.",
        "Mualliflarni tanlashda yordam kerakmi? Menejer shartlar va "
        "keyingi qadamni aniqlashga yordam beradi.",
        "Mualliflar bilan ishlash shakli va iqtisodiyotini muhokama "
        "qilamiz. Jamoaga ariza qoldiring.",
        "Davom etish",
    ),
}


def bot_text_defaults() -> dict[str, dict[str, str]]:
    return {
        locale: {
            **{
                f"customer_followup_{index}": values[index - 1]
                for index in (1, 2, 3)
            },
            "customer_followup_action": values[3],
        }
        for locale, values in FOLLOWUP_TEXTS.items()
    }

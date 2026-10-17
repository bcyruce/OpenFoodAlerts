"""Email strings for the Python mailer jobs, en/nl/zh (spec §10.5).

The website keeps its email strings in web/messages/*.json (`Email`); the pipeline does
not read the web's files at run time, so the shared ones (`footer`) are copied here
verbatim. Keep them in step when either side changes. Terms follow GLOSSARY.md: Digest,
Instant email, Subscription; never "alert" for an email.

Placeholders use str.format: {name}.
"""

MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "footer": (
            "OpenFoodAlerts archives official food-safety notifications from RASFF, NVWA and"
            " openFDA. It is not an official source."
        ),
        "digest.reason": "You receive this Digest because you subscribed on {site}.",
        "digest.subject": "OpenFoodAlerts Digest, {date}",
        "digest.intro": (
            "New and updated official food-safety notifications that match your filters,"
            " since {since} (Amsterdam time)."
        ),
        "digest.new": "New ({count})",
        "digest.updated": "Updated ({count})",
        "digest.news": "RASFF News ({count})",
        "digest.newsIntro": "RASFF News is listed whatever your other filters.",
        "item.sentInstantly": "sent instantly",
        "item.severity": "Official severity: {value}",
        "item.notGraded": "not graded",
        "item.hazardCategory": "Hazard category: {value}",
        "item.productCategory": "Product category: {value}",
        "item.ai": "{value} (AI)",
        "item.sourceText": "Source text: {text}",
        "item.aiSummary": "AI summary: {text}",
        "item.updatedOn": "Substantial update seen on {date}",
        "item.details": "Details on OpenFoodAlerts",
        "item.official": "Official record ({source})",
        "item.aiNote": (
            "Values marked AI were assigned by the OpenFoodAlerts AI layer and may be wrong;"
            " the official record prevails."
        ),
        "links.manage": "Change your filters or language",
        "links.unsubscribe": "Unsubscribe",
        "instant.subject": "{source}, {classification}: {title}",
        "instant.nvwaWarning": "safety warning",
        "instant.intro": (
            "{source} has published a new notification, classified as {classification},"
            " that matches your filters. You chose Instant emails for {source}."
        ),
        "instant.digestNote": (
            "It will also be listed in your next Digest. You receive at most 5 Instant emails"
            " a day; any further notifications appear in the Digest only."
        ),
        "instant.reason": (
            "You receive this Instant email because you turned on Instant emails on {site}."
        ),
    },
    "nl": {
        "footer": (
            "OpenFoodAlerts archiveert officiële voedselveiligheidsmeldingen van RASFF, NVWA en"
            " openFDA. Het is geen officiële bron."
        ),
        "digest.reason": "U ontvangt deze Digest omdat u zich hebt aangemeld op {site}.",
        "digest.subject": "OpenFoodAlerts-Digest, {date}",
        "digest.intro": (
            "Nieuwe en bijgewerkte officiële voedselveiligheidsmeldingen die bij uw filters"
            " passen, sinds {since} (Nederlandse tijd)."
        ),
        "digest.new": "Nieuw ({count})",
        "digest.updated": "Bijgewerkt ({count})",
        "digest.news": "RASFF News ({count})",
        "digest.newsIntro": "RASFF News wordt altijd getoond, ongeacht uw andere filters.",
        "item.sentInstantly": "al direct verstuurd",
        "item.severity": "Officiële ernst: {value}",
        "item.notGraded": "niet ingedeeld",
        "item.hazardCategory": "Gevarencategorie: {value}",
        "item.productCategory": "Productcategorie: {value}",
        "item.ai": "{value} (AI)",
        "item.sourceText": "Brontekst: {text}",
        "item.aiSummary": "AI-samenvatting: {text}",
        "item.updatedOn": "Wezenlijke wijziging gezien op {date}",
        "item.details": "Details op OpenFoodAlerts",
        "item.official": "Officieel record ({source})",
        "item.aiNote": (
            "Waarden met AI zijn toegekend door de AI-laag van OpenFoodAlerts en kunnen"
            " fout zijn; het officiële record gaat voor."
        ),
        "links.manage": "Filters of taal wijzigen",
        "links.unsubscribe": "Afmelden",
        "instant.subject": "{source}, {classification}: {title}",
        "instant.nvwaWarning": "veiligheidswaarschuwing",
        "instant.intro": (
            "{source} heeft een nieuwe melding gepubliceerd, ingedeeld als {classification},"
            " die bij uw filters past. U hebt Instant e-mail voor {source} aangezet."
        ),
        "instant.digestNote": (
            "De melding staat ook in uw volgende Digest. U ontvangt maximaal 5 Instant"
            " e-mails per dag; verdere meldingen staan alleen in de Digest."
        ),
        "instant.reason": (
            "U ontvangt deze Instant e-mail omdat u Instant e-mail hebt aangezet op {site}."
        ),
    },
    "zh": {
        "footer": (
            "OpenFoodAlerts 存档来自 RASFF、NVWA 和 openFDA 的官方食品安全通报，本站不是官方来源。"
        ),
        "digest.reason": "您收到这封 Digest，是因为您在 {site} 上订阅了。",
        "digest.subject": "OpenFoodAlerts 每日 Digest（{date}）",
        "digest.intro": (
            "自 {since}（荷兰时间）以来，符合您筛选条件的新增和更新的官方食品安全通报。"
        ),
        "digest.new": "新增（{count}）",
        "digest.updated": "更新（{count}）",
        "digest.news": "RASFF News（{count}）",
        "digest.newsIntro": "RASFF News 不受其他筛选条件限制，全部列出。",
        "item.sentInstantly": "已即时发送",
        "item.severity": "官方严重度：{value}",
        "item.notGraded": "未分级",
        "item.hazardCategory": "危害类别：{value}",
        "item.productCategory": "产品类别：{value}",
        "item.ai": "{value}（AI）",
        "item.sourceText": "原文：{text}",
        "item.aiSummary": "AI 生成摘要：{text}",
        "item.updatedOn": "{date} 发现实质性更新",
        "item.details": "在 OpenFoodAlerts 查看详情",
        "item.official": "官方原文（{source}）",
        "item.aiNote": "标有 AI 的内容由 OpenFoodAlerts 的 AI 生成，可能有误，以官方原文为准。",
        "links.manage": "修改筛选条件或语言",
        "links.unsubscribe": "退订",
        "instant.subject": "{source} {classification}：{title}",
        "instant.nvwaWarning": "安全警告",
        "instant.intro": (
            "{source} 发布了一条符合您筛选条件的新通报，官方分类为 {classification}。"
            "您为 {source} 开启了 Instant email。"
        ),
        "instant.digestNote": (
            "这条通报也会列在您的下一封 Digest 中。每天最多发送 5 封 Instant email，"
            "其余通报只列在 Digest 中。"
        ),
        "instant.reason": "您收到这封 Instant email，是因为您在 {site} 上开启了 Instant email。",
    },
}


class Translator:
    def __init__(self, locale: str) -> None:
        self.locale = locale
        self._messages = MESSAGES[locale]

    def __call__(self, key: str, **values: object) -> str:
        return self._messages[key].format(**values)

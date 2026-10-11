/**
 * The consent text shown next to the subscription form (spec §11.1 #1, #3). Every
 * Subscription stores the version it was given under; change the version whenever any
 * locale's text changes, and keep old versions here so stored versions stay readable.
 */
import type { SubscriptionLocale } from "./validate";

export const CONSENT_TEXT_VERSION = "2026-10-25";

export const CONSENT_TEXTS: Record<string, Record<SubscriptionLocale, string>> = {
  "2026-10-25": {
    en: "I agree that OpenFoodAlerts stores my email address, language and filters to send me a daily Digest and, if I chose them, Instant emails. I can unsubscribe or delete my data at any time with the link in every email.",
    nl: "Ik ga ermee akkoord dat OpenFoodAlerts mijn e-mailadres, taal en filters bewaart om mij een dagelijkse Digest en, als ik die kies, Instant e-mails te sturen. Ik kan me op elk moment afmelden of mijn gegevens laten verwijderen via de link in elke e-mail.",
    zh: "我同意 OpenFoodAlerts 保存我的邮箱地址、语言和筛选条件，用于每天向我发送 Digest，以及（如我选择）Instant email。我可以随时通过每封邮件中的链接退订或删除我的数据。",
  },
};

export function consentText(locale: SubscriptionLocale): string {
  return CONSENT_TEXTS[CONSENT_TEXT_VERSION][locale];
}

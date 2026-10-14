/**
 * About (spec §11.3): who builds the site, the interest disclosure (SnelVink) and the
 * referral rules with their review date. The one link to SnelVink is a plain text link
 * with utm_medium=about; no advertisement box on this page (rule 3).
 */
import Link from "next/link";
import type { JSX, ReactNode } from "react";
import type { Locale } from "@/i18n/routing";
import { formatDate } from "@/lib/format";
import { REFERRAL_RULES_REVIEWED_ON, SNELVINK, snelvinkUrl } from "@/lib/legal";
import { REPO_URL } from "@/lib/site";
import { Email, OwnerName } from "./shared";

const AD_LABEL = "Advertentie / 广告 — van de maker van deze site";
const UTM = "utm_source=openfoodalerts.nl&utm_medium={footer|about|home_box|zh_box}&utm_campaign=v1";
const BOT = "OpenFoodAlerts-bot/1.0 (+https://openfoodalerts.nl/about)";

function SnelVinkLink({ children }: { children: ReactNode }) {
  return (
    <a href={snelvinkUrl("about")} data-testid="snelvink-link" rel="noopener">
      {children}
    </a>
  );
}

function En() {
  const locale = "en";
  return (
    <>
      <p>
        OpenFoodAlerts is a free, open-source archive of official food-safety Notifications from
        the EU’s RASFF Window, the Dutch NVWA and the US FDA (openFDA). It puts them on one
        footing, classifies the ones without official categories with a publicly evaluated AI
        layer, and sends them by email to whoever subscribes. It is not an official source (see
        the <Link href="/en/disclaimer">disclaimer</Link>).
      </p>
      <h2>Who builds it</h2>
      <p>
        OpenFoodAlerts is built by <OwnerName locale={locale} />, a food-safety specialist, in
        their own time. The code, the evaluation set and the labelling guidelines are public on{" "}
        <a href={REPO_URL}>GitHub</a>. Legal details are in the <Link href="/en/colofon">colofon</Link>.
      </p>
      <h2 id="interest">Interest disclosure</h2>
      <p>
        The maker of OpenFoodAlerts is also the founder of {SNELVINK.name}, which sells HACCP
        software to food businesses. Some visitors of this site may be potential SnelVink
        customers, so the maker has a commercial interest in this site. OpenFoodAlerts itself
        earns nothing: no fees, no paid placements, no data sales. The data, the classifications
        and the evaluation are the same for everyone and do not depend on SnelVink in any way.
      </p>
      <p>
        You can read about SnelVink on <SnelVinkLink>snelvink.nl</SnelVinkLink>.
      </p>
      <h2 id="referral-rules">Referral rules</h2>
      <p>To keep that interest apart from the content, the site follows these rules:</p>
      <ol>
        <li>The footer says who built the site, with a link to SnelVink; this page discloses the interest.</li>
        <li>No banners, pop-ups or interstitials.</li>
        <li>
          One small box about SnelVink appears only at the bottom of the home page and on the
          Chinese pages. It never appears on the dashboard, search, Notification pages, the
          evaluation page, the data page or this page.
        </li>
        <li>
          That box is labelled “{AD_LABEL}” and is visually separated from the content (Dutch
          Advertising Code, article 11.1).
        </li>
        <li>
          No scandal framing and no appeals to fear. Factual statements on the Chinese pages link
          to NVWA.
        </li>
        <li>Emails (Digest and Instant email) contain no promotion.</li>
        <li>
          Links to SnelVink carry the parameters <code>{UTM}</code>, so that SnelVink can count
          visits from this site. OpenFoodAlerts itself sets no cookies and does not track you.
        </li>
        <li>These rules are reviewed every year.</li>
      </ol>
      <p data-testid="rules-reviewed">
        Rules last reviewed on {formatDate(locale, REFERRAL_RULES_REVIEWED_ON)}.
      </p>
      <h2 id="crawler">For source operators: our crawler</h2>
      <p>
        Our jobs identify themselves as <code>{BOT}</code>. They send one request at a time,
        follow each source’s rate limits, retry server errors with increasing pauses and store
        every response, so nothing is fetched twice without need. If our requests cause you any
        trouble, please write to <Email locale={locale} />.
      </p>
      <h2>Contact</h2>
      <p>
        Email: <Email locale={locale} />. Data errors and suggestions are also welcome as{" "}
        <a href={`${REPO_URL}/issues`}>GitHub issues</a>.
      </p>
    </>
  );
}

function Nl() {
  const locale = "nl";
  return (
    <>
      <p>
        OpenFoodAlerts is een gratis, open-source archief van officiële
        voedselveiligheidsmeldingen van RASFF Window (EU), de NVWA en de Amerikaanse FDA
        (openFDA). Het brengt ze samen in één structuur, deelt meldingen zonder officiële
        categorie in met een openbaar geëvalueerde AI-laag en stuurt ze per e-mail naar wie zich
        aanmeldt. Het is geen officiële bron (zie de <Link href="/nl/disclaimer">disclaimer</Link>).
      </p>
      <h2>Wie het maakt</h2>
      <p>
        OpenFoodAlerts wordt in eigen tijd gemaakt door <OwnerName locale={locale} />, specialist
        in voedselveiligheid. De code, de evaluatieset en de annotatierichtlijnen staan openbaar
        op <a href={REPO_URL}>GitHub</a>. De wettelijke gegevens staan in het{" "}
        <Link href="/nl/colofon">colofon</Link>.
      </p>
      <h2 id="interest">Belangenverklaring</h2>
      <p>
        De maker van OpenFoodAlerts is ook de oprichter van {SNELVINK.name}, dat HACCP-software
        verkoopt aan levensmiddelenbedrijven. Sommige bezoekers van deze site zijn mogelijk
        klanten van SnelVink; de maker heeft dus een commercieel belang bij deze site.
        OpenFoodAlerts zelf verdient niets: geen abonnementsgeld, geen betaalde plaatsingen, geen
        verkoop van gegevens. De gegevens, de indelingen en de evaluatie zijn voor iedereen
        gelijk en staan los van SnelVink.
      </p>
      <p>
        Meer over SnelVink leest u op <SnelVinkLink>snelvink.nl</SnelVinkLink>.
      </p>
      <h2 id="referral-rules">Regels voor verwijzingen</h2>
      <p>Om dat belang gescheiden te houden van de inhoud, volgt de site deze regels:</p>
      <ol>
        <li>
          In de voettekst staat wie de site heeft gemaakt, met een link naar SnelVink; deze
          pagina maakt het belang bekend.
        </li>
        <li>Geen banners, pop-ups of tussenpagina’s.</li>
        <li>
          Eén klein vak over SnelVink staat alleen onderaan de startpagina en op de Chinese
          pagina’s. Het staat nooit op het dashboard, de zoekpagina, meldingspagina’s, de
          evaluatiepagina, de datapagina of deze pagina.
        </li>
        <li>
          Dat vak heeft het label “{AD_LABEL}” en is visueel gescheiden van de inhoud
          (Nederlandse Reclame Code, artikel 11.1).
        </li>
        <li>
          Geen sensatie en geen inspelen op angst. Feitelijke uitspraken op de Chinese pagina’s
          linken naar de NVWA.
        </li>
        <li>E-mails (Digest en Instant e-mail) bevatten geen promotie.</li>
        <li>
          Links naar SnelVink hebben de parameters <code>{UTM}</code>, zodat SnelVink bezoeken
          vanaf deze site kan tellen. OpenFoodAlerts zelf plaatst geen cookies en volgt u niet.
        </li>
        <li>Deze regels worden elk jaar herzien.</li>
      </ol>
      <p data-testid="rules-reviewed">
        Regels laatst herzien op {formatDate(locale, REFERRAL_RULES_REVIEWED_ON)}.
      </p>
      <h2 id="crawler">Voor bronbeheerders: onze crawler</h2>
      <p>
        Onze taken identificeren zich als <code>{BOT}</code>. Ze sturen één verzoek tegelijk,
        houden zich aan de limieten van elke bron, proberen serverfouten opnieuw met steeds
        langere pauzes en bewaren elk antwoord, zodat niets onnodig twee keer wordt opgehaald.
        Hebt u last van onze verzoeken, schrijf dan naar <Email locale={locale} />.
      </p>
      <h2>Contact</h2>
      <p>
        E-mail: <Email locale={locale} />. Fouten in de gegevens en suggesties zijn ook welkom
        als <a href={`${REPO_URL}/issues`}>GitHub-issue</a>.
      </p>
    </>
  );
}

function Zh() {
  const locale = "zh";
  return (
    <>
      <p>
        OpenFoodAlerts 是一个免费、开源的官方食品安全通报存档，收录欧盟 RASFF Window、荷兰 NVWA 和美国
        FDA（openFDA）发布的通报。本站把它们统一到同一结构中，用一个公开评测过的 AI
        层为缺少官方分类的通报补充分类，并通过邮件发送给订阅者。本站不是官方来源（见
        <Link href="/zh/disclaimer">免责声明</Link>）。
      </p>
      <h2>谁在做这个网站</h2>
      <p>
        OpenFoodAlerts 由食品安全专业人士 <OwnerName locale={locale} />
        利用业余时间开发。代码、评测集和标注指南都公开在
        <a href={REPO_URL}>GitHub</a> 上。法律信息见<Link href="/zh/colofon">网站信息（Colofon）</Link>。
      </p>
      <h2 id="interest">利益披露</h2>
      <p>
        OpenFoodAlerts 的开发者同时是 {SNELVINK.name} 的创始人。SnelVink 向食品企业销售 HACCP
        软件。本站的部分访客可能是 SnelVink
        的潜在客户，因此开发者与本站存在商业利益关系。OpenFoodAlerts
        本身没有任何收入：不收费、不接受付费推广、不出售数据。所有人看到的数据、分类和评测都相同，与
        SnelVink 无关。
      </p>
      <p>
        关于 SnelVink 的介绍见 <SnelVinkLink>snelvink.nl</SnelVinkLink>。
      </p>
      <h2 id="referral-rules">引流规则</h2>
      <p>为了把这一利益与内容分开，本站遵守以下规则：</p>
      <ol>
        <li>页脚写明网站由谁开发，并链接到 SnelVink；本页披露利益关系。</li>
        <li>没有横幅、弹窗或插页。</li>
        <li>
          关于 SnelVink 的小广告框只出现在首页底部和中文页面上；从不出现在仪表盘、搜索页、通报页面、评测页、数据页和本页。
        </li>
        <li>
          广告框标注“{AD_LABEL}”，并在视觉上与内容分开（荷兰广告守则 Nederlandse Reclame Code 第 11.1 条）。
        </li>
        <li>不渲染丑闻，不使用恐惧诉求；中文页面上的事实陈述都链接到 NVWA。</li>
        <li>邮件（Digest 和 Instant email）中不放任何推广内容。</li>
        <li>
          指向 SnelVink 的链接带有参数 <code>{UTM}</code>，以便 SnelVink 统计来自本站的访问。OpenFoodAlerts
          本身不设置 cookie，也不追踪您。
        </li>
        <li>以上规则每年复核一次。</li>
      </ol>
      <p data-testid="rules-reviewed">
        规则最近一次复核日期：{formatDate(locale, REFERRAL_RULES_REVIEWED_ON)}。
      </p>
      <h2 id="crawler">致数据源运营方：我们的抓取程序</h2>
      <p>
        我们的任务以 <code>{BOT}</code>
        标识自己。它们一次只发一个请求，遵守各来源的限速，对服务器错误按逐渐加长的间隔重试，并保存每个响应，避免不必要的重复抓取。如果我们的请求给您造成困扰，请写信至{" "}
        <Email locale={locale} />。
      </p>
      <h2>联系方式</h2>
      <p>
        邮箱：<Email locale={locale} />。也欢迎通过 <a href={`${REPO_URL}/issues`}>GitHub issue</a>
        报告数据错误或提出建议。
      </p>
    </>
  );
}

export const ABOUT: Record<Locale, () => JSX.Element> = { en: En, nl: Nl, zh: Zh };

/**
 * Privacy statement (spec §11.1 #8). Must stay consistent with docs/privacy/ropa.md (the
 * record of processing activities): purposes, legal bases, processors and retention
 * periods are taken from there. Facts the owner has not supplied yet render as <Todo>.
 */
import type { JSX } from "react";
import type { Locale } from "@/i18n/routing";
import { AP_URL, OPERATOR } from "@/lib/legal";
import { CONSENT_TEXT_VERSION, consentText } from "@/lib/subscriptions/consent";
import { Address, Email, OperatorName, Todo, Value } from "./shared";

function Controller({ locale, labels }: { locale: Locale; labels: [string, string, string, string] }) {
  const [name, address, kvk, email] = labels;
  return (
    <dl data-testid="controller">
      <dt>{name}</dt>
      <dd>
        <OperatorName locale={locale} /> ({OPERATOR.tradeName})
      </dd>
      <dt>{address}</dt>
      <dd>
        <Address locale={locale} />
      </dd>
      <dt>{kvk}</dt>
      <dd>
        <Value value={OPERATOR.kvk} locale={locale} />
      </dd>
      <dt>{email}</dt>
      <dd>
        <Email locale={locale} />
      </dd>
    </dl>
  );
}

function Consent({ locale }: { locale: Locale }) {
  return (
    <blockquote data-testid="consent-text">
      {consentText(locale)}
    </blockquote>
  );
}

function En() {
  const locale = "en";
  return (
    <>
      <p>
        This statement explains which personal data OpenFoodAlerts processes, why, for how long,
        and what your rights are. In short: browsing the site needs no personal data and sets no
        cookies; if you subscribe to emails, we keep your email address and your settings until
        you unsubscribe.
      </p>
      <h2 id="controller">Who is responsible</h2>
      <p>The controller under the General Data Protection Regulation (GDPR) is:</p>
      <Controller locale={locale} labels={["Name", "Address", "KvK number", "Email"]} />
      <p>There is no data protection officer; one is not required for this processing.</p>

      <h2 id="website">Visiting the website</h2>
      <ul>
        <li>
          <strong>No cookies</strong>, no analytics, no tracking pixels, no advertising networks
          and no third-party scripts or fonts. You do not need to accept anything.
        </li>
        <li>
          To deliver a page, the web server necessarily receives your IP address and the address
          of the page you request. Our hosting provider keeps server logs only as long as needed
          to run and secure the server: <Todo locale={locale} />.
        </li>
        <li>
          The subscription and manage forms keep your IP address in memory for at most 10
          minutes, to limit abuse (for example someone entering many addresses). It is never
          stored.
        </li>
      </ul>

      <h2 id="subscriptions">Email subscriptions</h2>
      <p>If you subscribe to the Digest or Instant emails, we process:</p>
      <ul>
        <li>your email address, email language, filters (Sources, Hazard and Product categories, countries of origin) and Instant email settings;</li>
        <li>the status of your Subscription and when you requested, confirmed or ended it;</li>
        <li>
          evidence of your consent: the time, the version of the consent text and a keyed hash
          of your IP address (the IP address itself is not stored);
        </li>
        <li>which emails were sent to you and when (the Notifications they listed and the email provider’s message id).</li>
      </ul>
      <p>We use these data only for these purposes, on these legal bases:</p>
      <div className="table-scroll" tabIndex={0} role="region" aria-label="Purposes and legal bases">
        <table>
          <thead>
            <tr>
              <th scope="col">Purpose</th>
              <th scope="col">Legal basis</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Sending the confirmation email, the daily Digest and the Instant emails you chose</td>
              <td>Your consent (GDPR article 6(1)(a)), which you can withdraw at any time</td>
            </tr>
            <tr>
              <td>Letting you view and change your settings, unsubscribe or delete your data</td>
              <td>Your consent and your rights under articles 7(3), 16 and 17</td>
            </tr>
            <tr>
              <td>Being able to show that you gave consent</td>
              <td>Legal obligation (articles 7(1) and 6(1)(c))</td>
            </tr>
            <tr>
              <td>Never emailing an address again after “delete my data” (only a keyed hash is kept)</td>
              <td>Legitimate interest in honouring that request (article 6(1)(f))</td>
            </tr>
            <tr>
              <td>Limiting abuse of the forms</td>
              <td>Legitimate interest in protecting others and the service (article 6(1)(f))</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p>
        The consent text you agree to is stored with its version. The current version (
        {CONSENT_TEXT_VERSION}) reads:
      </p>
      <Consent locale={locale} />
      <p>
        Our emails contain only official Notifications and the links to manage your
        Subscription, with no promotion. Our email provider, Brevo, adds a tracking pixel (an
        invisible image) to every email and routes the links through its own servers, so that
        it can count opens and clicks; Brevo does not let us switch this off. We tell Brevo to
        anonymise these events: they are only counted as totals and are not linked to your
        address. There is no profiling and no automated decision-making.
      </p>

      <h2 id="recipients">Who receives the data</h2>
      <p>
        We do not sell or share your data, and subscription data are never part of any public
        data export. These service providers process data on our behalf (processors), under a
        data processing agreement:
      </p>
      <ul data-testid="processors">
        <li>
          <strong>Brevo</strong> (Sendinblue SAS, France): sends the emails. Receives your email
          address and the content of the emails, and counts opens and clicks anonymously.
        </li>
        <li>
          <strong>Hosting provider</strong> (website and database): <Todo locale={locale} />
        </li>
        <li>
          <strong>Backup storage</strong> (encrypted database backups): <Todo locale={locale} />
        </li>
      </ul>
      <p>
        We do not intend to transfer data outside the European Economic Area. Confirmation for
        Brevo’s sub-processors and our hosting providers: <Todo locale={locale} />
      </p>

      <h2 id="retention">How long we keep the data</h2>
      <div className="table-scroll" tabIndex={0} role="region" aria-label="Retention periods">
        <table data-testid="retention">
          <thead>
            <tr>
              <th scope="col">Data</th>
              <th scope="col">Kept for</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Subscription that was never confirmed</td>
              <td>Deleted 7 days after the last request</td>
            </tr>
            <tr>
              <td>Confirmation link</td>
              <td>Valid for 24 hours</td>
            </tr>
            <tr>
              <td>Active Subscription</td>
              <td>Until you unsubscribe or delete your data</td>
            </tr>
            <tr>
              <td>Subscription after unsubscribing, with its email records</td>
              <td>Deleted within 30 days</td>
            </tr>
            <tr>
              <td>After “delete my data”</td>
              <td>Your Subscriptions and email records are deleted at once; only a keyed hash of the address remains on the do-not-send list, for as long as the service runs</td>
            </tr>
            <tr>
              <td>Records of sent emails</td>
              <td>12 months</td>
            </tr>
            <tr>
              <td>IP address in the form rate limiter</td>
              <td>At most 10 minutes, in memory only</td>
            </tr>
            <tr>
              <td>Backups</td>
              <td>
                <Todo locale={locale} />
              </td>
            </tr>
            <tr>
              <td>Brevo’s sending logs</td>
              <td>
                <Todo locale={locale} />
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <h2 id="rights">Your rights</h2>
      <p>
        You have the right to access, rectify and erase your data, to restrict or object to
        processing, to data portability and to withdraw your consent at any time (withdrawal
        does not affect earlier processing). Most of this you can do yourself:
      </p>
      <ul>
        <li>every email has a one-click unsubscribe link and a link to your manage page;</li>
        <li>on the manage page you can see and change your settings, unsubscribe, or delete all your data;</li>
        <li>
          for anything else, such as a full copy of your data, write to <Email locale={locale} />.
          We answer within one month.
        </li>
      </ul>
      <p>
        If you think we handle your data wrongly, you can complain to the Dutch data protection
        authority, the <a href={AP_URL}>Autoriteit Persoonsgegevens</a>. We would appreciate
        hearing from you first.
      </p>

      <h2 id="changes">Changes</h2>
      <p>
        When this statement changes, the date at the top changes. If a change affects what you
        consented to, we ask for your consent again.
      </p>
    </>
  );
}

function Nl() {
  const locale = "nl";
  return (
    <>
      <p>
        Deze verklaring legt uit welke persoonsgegevens OpenFoodAlerts verwerkt, waarom, hoe
        lang, en welke rechten u hebt. Kort gezegd: voor het bekijken van de site zijn geen
        persoonsgegevens nodig en er worden geen cookies geplaatst; als u zich aanmeldt voor
        e-mails, bewaren we uw e-mailadres en uw instellingen tot u zich afmeldt.
      </p>
      <h2 id="controller">Wie is verantwoordelijk</h2>
      <p>Verwerkingsverantwoordelijke in de zin van de Algemene verordening gegevensbescherming (AVG) is:</p>
      <Controller locale={locale} labels={["Naam", "Adres", "KvK-nummer", "E-mail"]} />
      <p>Er is geen functionaris voor gegevensbescherming; die is voor deze verwerking niet verplicht.</p>

      <h2 id="website">De website bezoeken</h2>
      <ul>
        <li>
          <strong>Geen cookies</strong>, geen analytics, geen trackingpixels, geen
          advertentienetwerken en geen scripts of lettertypen van derden. U hoeft nergens mee
          akkoord te gaan.
        </li>
        <li>
          Om een pagina te kunnen leveren, ontvangt de webserver noodzakelijkerwijs uw IP-adres
          en het adres van de opgevraagde pagina. Onze hostingprovider bewaart serverlogs alleen
          zo lang als nodig is om de server te laten werken en te beveiligen:{" "}
          <Todo locale={locale} />.
        </li>
        <li>
          Het aanmeld- en beheerformulier houden uw IP-adres maximaal 10 minuten in het geheugen
          om misbruik te beperken (bijvoorbeeld iemand die veel adressen invoert). Het wordt nooit
          opgeslagen.
        </li>
      </ul>

      <h2 id="subscriptions">E-mailabonnementen</h2>
      <p>Als u zich aanmeldt voor de Digest of Instant e-mails, verwerken we:</p>
      <ul>
        <li>uw e-mailadres, de taal van de e-mails, uw filters (bronnen, gevaren- en productcategorieën, landen van herkomst) en de instellingen voor Instant e-mails;</li>
        <li>de status van uw abonnement en wanneer u het hebt aangevraagd, bevestigd of beëindigd;</li>
        <li>
          het bewijs van uw toestemming: het tijdstip, de versie van de toestemmingstekst en een
          hash met geheime sleutel van uw IP-adres (het IP-adres zelf wordt niet opgeslagen);
        </li>
        <li>welke e-mails u wanneer zijn gestuurd (de meldingen erin en het berichtnummer van de e-mailprovider).</li>
      </ul>
      <p>We gebruiken deze gegevens alleen voor deze doelen, op deze grondslagen:</p>
      <div className="table-scroll" tabIndex={0} role="region" aria-label="Doelen en grondslagen">
        <table>
          <thead>
            <tr>
              <th scope="col">Doel</th>
              <th scope="col">Grondslag</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>De bevestigingsmail, de dagelijkse Digest en de door u gekozen Instant e-mails versturen</td>
              <td>Uw toestemming (artikel 6, lid 1, onder a AVG), die u altijd kunt intrekken</td>
            </tr>
            <tr>
              <td>U uw instellingen laten bekijken en wijzigen, u laten afmelden of uw gegevens laten verwijderen</td>
              <td>Uw toestemming en uw rechten volgens de artikelen 7, lid 3, 16 en 17</td>
            </tr>
            <tr>
              <td>Kunnen aantonen dat u toestemming hebt gegeven</td>
              <td>Wettelijke verplichting (artikel 7, lid 1, en artikel 6, lid 1, onder c)</td>
            </tr>
            <tr>
              <td>Een adres na “mijn gegevens verwijderen” nooit meer mailen (alleen een hash met geheime sleutel blijft bewaard)</td>
              <td>Gerechtvaardigd belang bij het naleven van dat verzoek (artikel 6, lid 1, onder f)</td>
            </tr>
            <tr>
              <td>Misbruik van de formulieren beperken</td>
              <td>Gerechtvaardigd belang bij het beschermen van anderen en de dienst (artikel 6, lid 1, onder f)</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p>
        De toestemmingstekst waarmee u akkoord gaat, wordt met zijn versie opgeslagen. De huidige
        versie ({CONSENT_TEXT_VERSION}) luidt:
      </p>
      <Consent locale={locale} />
      <p>
        Onze e-mails bevatten alleen officiële meldingen en de links om uw abonnement te beheren,
        zonder promotie. Onze e-mailprovider Brevo voegt aan elke e-mail een trackingpixel (een
        onzichtbaar plaatje) toe en leidt de links via zijn eigen servers, zodat hij openingen en
        klikken kan tellen; Brevo laat ons dit niet uitschakelen. We laten Brevo deze gegevens
        anonimiseren: ze worden alleen als totalen geteld en niet aan uw adres gekoppeld. Er is
        geen profilering en geen geautomatiseerde besluitvorming.
      </p>

      <h2 id="recipients">Wie de gegevens ontvangt</h2>
      <p>
        We verkopen of delen uw gegevens niet, en abonnementsgegevens zitten nooit in een openbare
        data-export. Deze dienstverleners verwerken gegevens in onze opdracht (verwerkers), op
        basis van een verwerkersovereenkomst:
      </p>
      <ul data-testid="processors">
        <li>
          <strong>Brevo</strong> (Sendinblue SAS, Frankrijk): verstuurt de e-mails. Ontvangt uw
          e-mailadres en de inhoud van de e-mails, en telt openingen en klikken anoniem.
        </li>
        <li>
          <strong>Hostingprovider</strong> (website en database): <Todo locale={locale} />
        </li>
        <li>
          <strong>Opslag van back-ups</strong> (versleutelde databaseback-ups): <Todo locale={locale} />
        </li>
      </ul>
      <p>
        We zijn niet van plan gegevens buiten de Europese Economische Ruimte door te geven.
        Bevestiging voor de subverwerkers van Brevo en onze hostingproviders:{" "}
        <Todo locale={locale} />
      </p>

      <h2 id="retention">Hoe lang we de gegevens bewaren</h2>
      <div className="table-scroll" tabIndex={0} role="region" aria-label="Bewaartermijnen">
        <table data-testid="retention">
          <thead>
            <tr>
              <th scope="col">Gegevens</th>
              <th scope="col">Bewaartermijn</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Abonnement dat nooit is bevestigd</td>
              <td>Verwijderd 7 dagen na de laatste aanvraag</td>
            </tr>
            <tr>
              <td>Bevestigingslink</td>
              <td>24 uur geldig</td>
            </tr>
            <tr>
              <td>Actief abonnement</td>
              <td>Tot u zich afmeldt of uw gegevens verwijdert</td>
            </tr>
            <tr>
              <td>Abonnement na afmelden, met de gegevens over verstuurde e-mails</td>
              <td>Binnen 30 dagen verwijderd</td>
            </tr>
            <tr>
              <td>Na “mijn gegevens verwijderen”</td>
              <td>Uw abonnementen en e-mailgegevens worden direct verwijderd; alleen een hash met geheime sleutel van het adres blijft op de niet-mailen-lijst staan, zolang de dienst bestaat</td>
            </tr>
            <tr>
              <td>Gegevens over verstuurde e-mails</td>
              <td>12 maanden</td>
            </tr>
            <tr>
              <td>IP-adres in de begrenzing van de formulieren</td>
              <td>Maximaal 10 minuten, alleen in het geheugen</td>
            </tr>
            <tr>
              <td>Back-ups</td>
              <td>
                <Todo locale={locale} />
              </td>
            </tr>
            <tr>
              <td>Verzendlogs van Brevo</td>
              <td>
                <Todo locale={locale} />
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <h2 id="rights">Uw rechten</h2>
      <p>
        U hebt het recht op inzage, rectificatie en wissing van uw gegevens, op beperking van en
        bezwaar tegen de verwerking, op overdraagbaarheid van gegevens en om uw toestemming op
        elk moment in te trekken (intrekken heeft geen gevolgen voor eerdere verwerking). Het
        meeste kunt u zelf doen:
      </p>
      <ul>
        <li>elke e-mail heeft een link om u met één klik af te melden en een link naar uw beheerpagina;</li>
        <li>op de beheerpagina kunt u uw instellingen bekijken en wijzigen, u afmelden of al uw gegevens verwijderen;</li>
        <li>
          voor al het andere, zoals een volledige kopie van uw gegevens, schrijft u naar{" "}
          <Email locale={locale} />. We antwoorden binnen een maand.
        </li>
      </ul>
      <p>
        Vindt u dat we niet goed met uw gegevens omgaan, dan kunt u een klacht indienen bij de{" "}
        <a href={AP_URL}>Autoriteit Persoonsgegevens</a>. We horen het graag eerst van u.
      </p>

      <h2 id="changes">Wijzigingen</h2>
      <p>
        Als deze verklaring verandert, verandert de datum bovenaan. Raakt een wijziging aan
        waarvoor u toestemming gaf, dan vragen we opnieuw om uw toestemming.
      </p>
    </>
  );
}

function Zh() {
  const locale = "zh";
  return (
    <>
      <p>
        本声明说明 OpenFoodAlerts
        处理哪些个人数据、为什么处理、保存多久，以及您享有哪些权利。简而言之：浏览本站不需要任何个人数据，也不设置
        cookie；如果您订阅邮件，我们会保存您的邮箱地址和设置，直到您退订为止。
      </p>
      <h2 id="controller">谁负责</h2>
      <p>《通用数据保护条例》（GDPR）意义上的数据控制者是：</p>
      <Controller locale={locale} labels={["名称", "地址", "KvK 编号", "邮箱"]} />
      <p>本站没有数据保护官；此类处理不要求设立。</p>

      <h2 id="website">访问网站</h2>
      <ul>
        <li>
          <strong>不使用 cookie</strong>，不使用分析工具、追踪像素、广告网络，也不加载第三方脚本或字体。您无需同意任何内容。
        </li>
        <li>
          为了向您提供页面，网站服务器必然会收到您的 IP
          地址和您请求的页面地址。托管服务商只在运行和保护服务器所需的期限内保存服务器日志：
          <Todo locale={locale} />。
        </li>
        <li>订阅和管理表单为了防止滥用（例如有人批量填写他人地址），会把您的 IP 地址在内存中保留最多 10 分钟，从不写入存储。</li>
      </ul>

      <h2 id="subscriptions">邮件订阅</h2>
      <p>如果您订阅 Digest 或 Instant email，我们会处理：</p>
      <ul>
        <li>您的邮箱地址、邮件语言、筛选条件（来源、危害类别、产品类别、原产国）以及 Instant email 设置；</li>
        <li>订阅的状态，以及您申请、确认或结束订阅的时间；</li>
        <li>您同意的证据：时间、同意文本的版本，以及您 IP 地址的带密钥哈希（不保存 IP 地址本身）；</li>
        <li>向您发送过哪些邮件、何时发送（邮件中列出的通报和邮件服务商的消息编号）。</li>
      </ul>
      <p>我们只为以下目的、依据以下法律基础使用这些数据：</p>
      <div className="table-scroll" tabIndex={0} role="region" aria-label="目的与法律依据">
        <table>
          <thead>
            <tr>
              <th scope="col">目的</th>
              <th scope="col">法律依据</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>发送确认邮件、每日 Digest 以及您选择的 Instant email</td>
              <td>您的同意（GDPR 第 6(1)(a) 条），可随时撤回</td>
            </tr>
            <tr>
              <td>让您查看和修改设置、退订或删除数据</td>
              <td>您的同意，以及第 7(3)、16、17 条规定的权利</td>
            </tr>
            <tr>
              <td>能够证明您曾表示同意</td>
              <td>法律义务（第 7(1) 条及第 6(1)(c) 条）</td>
            </tr>
            <tr>
              <td>在“删除我的数据”之后不再向该地址发信（只保留带密钥的哈希）</td>
              <td>履行该请求的正当利益（第 6(1)(f) 条）</td>
            </tr>
            <tr>
              <td>防止表单被滥用</td>
              <td>保护他人和本服务的正当利益（第 6(1)(f) 条）</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p>您同意的文本会连同版本号一起保存。当前版本（{CONSENT_TEXT_VERSION}）的内容是：</p>
      <Consent locale={locale} />
      <p>我们的邮件只包含官方通报和管理订阅的链接，没有推广内容。我们的邮件服务商 Brevo 会在每封邮件里加入一个追踪像素（一张看不见的图片），并让链接先经过它自己的服务器，用来统计打开和点击次数；Brevo 不允许我们关闭这项功能。我们要求 Brevo 把这些记录匿名化：只计入总数，不与您的邮箱地址关联。不做用户画像，也没有自动化决策。</p>

      <h2 id="recipients">谁会收到这些数据</h2>
      <p>
        我们不出售、不分享您的数据，订阅数据也绝不会出现在任何公开的数据导出中。以下服务商代表我们处理数据（处理者），双方签有数据处理协议：
      </p>
      <ul data-testid="processors">
        <li>
          <strong>Brevo</strong>（Sendinblue SAS，法国）：发送邮件，会收到您的邮箱地址和邮件内容，并匿名统计打开和点击次数。
        </li>
        <li>
          <strong>托管服务商</strong>（网站和数据库）：<Todo locale={locale} />
        </li>
        <li>
          <strong>备份存储</strong>（加密的数据库备份）：<Todo locale={locale} />
        </li>
      </ul>
      <p>
        我们不打算把数据传输到欧洲经济区以外。Brevo 的子处理者和托管服务商的确认情况：<Todo locale={locale} />
      </p>

      <h2 id="retention">保存期限</h2>
      <div className="table-scroll" tabIndex={0} role="region" aria-label="保存期限">
        <table data-testid="retention">
          <thead>
            <tr>
              <th scope="col">数据</th>
              <th scope="col">保存期限</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>从未确认的订阅</td>
              <td>最后一次申请后 7 天删除</td>
            </tr>
            <tr>
              <td>确认链接</td>
              <td>24 小时内有效</td>
            </tr>
            <tr>
              <td>有效订阅</td>
              <td>直到您退订或删除数据</td>
            </tr>
            <tr>
              <td>退订后的订阅及其邮件发送记录</td>
              <td>30 天内删除</td>
            </tr>
            <tr>
              <td>“删除我的数据”之后</td>
              <td>您的订阅和邮件记录立即删除；只有邮箱地址的带密钥哈希保留在禁发名单上，直到本服务停止运行</td>
            </tr>
            <tr>
              <td>邮件发送记录</td>
              <td>12 个月</td>
            </tr>
            <tr>
              <td>表单限流中的 IP 地址</td>
              <td>最多 10 分钟，仅在内存中</td>
            </tr>
            <tr>
              <td>备份</td>
              <td>
                <Todo locale={locale} />
              </td>
            </tr>
            <tr>
              <td>Brevo 的发送日志</td>
              <td>
                <Todo locale={locale} />
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <h2 id="rights">您的权利</h2>
      <p>
        您有权访问、更正和删除您的数据，有权限制或反对处理，有权要求数据可携带，并可随时撤回同意（撤回不影响此前的处理）。大部分操作您可以自己完成：
      </p>
      <ul>
        <li>每封邮件都有一键退订链接和管理页面链接；</li>
        <li>在管理页面上，您可以查看和修改设置、退订，或删除全部数据；</li>
        <li>
          其他请求（例如获取数据的完整副本）请写信至 <Email locale={locale} />，我们会在一个月内答复。
        </li>
      </ul>
      <p>
        如果您认为我们处理您的数据不当，可以向荷兰数据保护机构
        <a href={AP_URL}>Autoriteit Persoonsgegevens</a>
        投诉。我们希望您先告诉我们。
      </p>

      <h2 id="changes">变更</h2>
      <p>本声明变更时，页首的日期会随之更新。如果变更涉及您所同意的内容，我们会重新征求您的同意。</p>
    </>
  );
}

export const PRIVACY: Record<Locale, () => JSX.Element> = { en: En, nl: Nl, zh: Zh };

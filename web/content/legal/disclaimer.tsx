/**
 * Disclaimer (spec §11.3). The statement in `data-testid="disclaimer-statement"` is the
 * spec's text: verbatim in zh, translated for en and nl (owner to review).
 */
import Link from "next/link";
import type { JSX } from "react";
import type { Locale } from "@/i18n/routing";

function En() {
  return (
    <>
      <p data-testid="disclaimer-statement" className="text-lg">
        This site is not an official source and is not affiliated with NVWA, the European
        Commission or FDA. Information may be delayed or contain errors. Check the official
        notification before you take any action. AI classification fields may be wrong.
      </p>
      <h2>What this means</h2>
      <ul>
        <li>
          OpenFoodAlerts copies Notifications from RASFF Window (European Commission), NVWA and
          openFDA. Every Notification page links to the official source; the official text
          prevails.
        </li>
        <li>
          We check the sources several times a day, but a Notification can appear here later
          than at the source, and a change at the source can take a while to reach this site.
        </li>
        <li>
          Fields with an AI badge were filled in by a language model. They can be wrong. How
          often they are wrong is measured and published on the{" "}
          <Link href="/en/evaluation">evaluation page</Link>. Use “Official classifications only” to
          leave them out.
        </li>
        <li>
          Severity is only ever the official one (RASFF risk decision, FDA classification); NVWA
          does not grade its warnings and we do not grade them either.
        </li>
        <li>
          Licences and attribution of each source are on the <Link href="/en/data">data page</Link>.
          If you find an error, use “Report an error on this page” on the Notification page.
        </li>
      </ul>
    </>
  );
}

function Nl() {
  return (
    <>
      <p data-testid="disclaimer-statement" className="text-lg">
        Deze site is geen officiële bron en is niet verbonden aan de NVWA, de Europese Commissie
        of de FDA. Informatie kan vertraagd zijn of fouten bevatten. Controleer de officiële
        melding voordat u actie onderneemt. Velden met een AI-indeling kunnen onjuist zijn.
      </p>
      <h2>Wat dit betekent</h2>
      <ul>
        <li>
          OpenFoodAlerts neemt meldingen over van RASFF Window (Europese Commissie), de NVWA en
          openFDA. Elke meldingspagina linkt naar de officiële bron; de officiële tekst gaat
          voor.
        </li>
        <li>
          We controleren de bronnen meerdere keren per dag, maar een melding kan hier later
          verschijnen dan bij de bron, en een wijziging bij de bron kan enige tijd nodig hebben
          voordat zij hier zichtbaar is.
        </li>
        <li>
          Velden met een AI-label zijn ingevuld door een taalmodel. Ze kunnen onjuist zijn. Hoe
          vaak dat gebeurt, meten en publiceren we op de{" "}
          <Link href="/en/evaluation" hrefLang="en">
            evaluatiepagina
          </Link>{" "}
          (Engels). Met “Alleen officiële indelingen” laat u ze weg.
        </li>
        <li>
          De ernst is altijd de officiële (RASFF-risicobeoordeling, FDA-classificatie); de NVWA
          deelt haar waarschuwingen niet in en wij doen dat ook niet.
        </li>
        <li>
          Licenties en bronvermelding per bron staan op de{" "}
          <Link href="/en/data" hrefLang="en">
            datapagina
          </Link>{" "}
          (Engels). Ziet u een fout, gebruik dan “Meld een fout op deze pagina” op de meldingspagina.
        </li>
      </ul>
    </>
  );
}

function Zh() {
  return (
    <>
      <p data-testid="disclaimer-statement" className="text-lg">
        本站非官方来源，与 NVWA、欧盟委员会、FDA 无关联；信息可能延迟或有误；采取任何行动前请核对官方通报；AI
        分类字段可能出错。
      </p>
      <h2>具体说明</h2>
      <ul>
        <li>
          OpenFoodAlerts 转载 RASFF Window（欧盟委员会）、NVWA 和 openFDA
          发布的通报。每条通报的页面都链接到官方来源，以官方原文为准。
        </li>
        <li>我们每天多次检查各来源，但通报在本站出现的时间可能晚于官方，官方的更正也可能需要一段时间才反映到本站。</li>
        <li>
          带 AI 标记的字段由语言模型生成，可能出错。出错的频率经过测量，公布在
          <Link href="/en/evaluation" hrefLang="en">
            评测页
          </Link>
          （英文）。打开“仅官方分类”即可排除这些字段。
        </li>
        <li>严重程度只显示官方评级（RASFF 风险判定、FDA 分级）；NVWA 不对警告分级，本站也不分级。</li>
        <li>
          各来源的许可与署名见
          <Link href="/en/data" hrefLang="en">
            数据页
          </Link>
          （英文）。发现错误时，请使用通报页面上的“报告错误”链接。
        </li>
      </ul>
    </>
  );
}

export const DISCLAIMER: Record<Locale, () => JSX.Element> = { en: En, nl: Nl, zh: Zh };

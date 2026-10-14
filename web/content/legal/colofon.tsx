/**
 * Colofon: the information a service provider must make available under BW article 3:15d
 * (name, address, email, KvK number, VAT identification number), from lib/legal.ts.
 */
import Link from "next/link";
import type { JSX } from "react";
import type { Locale } from "@/i18n/routing";
import { OPERATOR } from "@/lib/legal";
import { REPO_URL, SITE_URL } from "@/lib/site";
import { Address, Email, OwnerName, Value } from "./shared";

type Labels = {
  intro: string;
  tradeName: string;
  legalName: string;
  address: string;
  email: string;
  kvk: string;
  btwId: string;
  website: string;
  builtBy: string;
  code: string;
  codeText: string;
  data: string;
  dataText: string;
  dataHref: string;
};

function Colofon({ locale, l }: { locale: Locale; l: Labels }) {
  return (
    <>
      <p>{l.intro}</p>
      <dl data-testid="colofon">
        <dt>{l.tradeName}</dt>
        <dd>{OPERATOR.tradeName}</dd>
        <dt>{l.legalName}</dt>
        <dd>
          <Value value={OPERATOR.legalName} locale={locale} />
        </dd>
        <dt>{l.address}</dt>
        <dd>
          <Address locale={locale} />
        </dd>
        <dt>{l.email}</dt>
        <dd>
          <Email locale={locale} />
        </dd>
        <dt>{l.kvk}</dt>
        <dd>
          <Value value={OPERATOR.kvk} locale={locale} />
        </dd>
        <dt>{l.btwId}</dt>
        <dd>
          <Value value={OPERATOR.btwId} locale={locale} />
        </dd>
        <dt>{l.website}</dt>
        <dd>
          <a href={SITE_URL}>{SITE_URL.replace(/^https?:\/\//, "")}</a>
        </dd>
        <dt>{l.builtBy}</dt>
        <dd>
          <OwnerName locale={locale} />
        </dd>
        <dt>{l.code}</dt>
        <dd>
          <a href={REPO_URL}>GitHub</a> ({l.codeText})
        </dd>
        <dt>{l.data}</dt>
        <dd>
          {l.dataText} <Link href="/en/data" hrefLang="en">{l.dataHref}</Link>
        </dd>
      </dl>
    </>
  );
}

const EN: Labels = {
  intro: "OpenFoodAlerts is a trade name of the business below.",
  tradeName: "Trade name",
  legalName: "Business (eenmanszaak)",
  address: "Address",
  email: "Email",
  kvk: "Chamber of Commerce (KvK) number",
  btwId: "VAT identification number (btw-id)",
  website: "Website",
  builtBy: "Built by",
  code: "Source code",
  codeText: "Apache License 2.0",
  data: "Data",
  dataText: "Sources, licences and attribution:",
  dataHref: "data page",
};

const NL: Labels = {
  intro: "OpenFoodAlerts is een handelsnaam van de onderstaande onderneming.",
  tradeName: "Handelsnaam",
  legalName: "Onderneming (eenmanszaak)",
  address: "Adres",
  email: "E-mail",
  kvk: "KvK-nummer",
  btwId: "Btw-identificatienummer",
  website: "Website",
  builtBy: "Gemaakt door",
  code: "Broncode",
  codeText: "Apache License 2.0",
  data: "Gegevens",
  dataText: "Bronnen, licenties en bronvermelding:",
  dataHref: "datapagina (Engels)",
};

const ZH: Labels = {
  intro: "OpenFoodAlerts 是以下企业的商号（handelsnaam）。",
  tradeName: "商号",
  legalName: "企业（eenmanszaak，个体经营）",
  address: "地址",
  email: "邮箱",
  kvk: "荷兰商会（KvK）注册号",
  btwId: "增值税识别号（btw-id）",
  website: "网站",
  builtBy: "开发者",
  code: "源代码",
  codeText: "Apache License 2.0",
  data: "数据",
  dataText: "来源、许可与署名：",
  dataHref: "数据页（英文）",
};

export const COLOFON: Record<Locale, () => JSX.Element> = {
  en: () => <Colofon locale="en" l={EN} />,
  nl: () => <Colofon locale="nl" l={NL} />,
  zh: () => <Colofon locale="zh" l={ZH} />,
};

/**
 * Legal identity of the operator and the referral settings (spec §11.3). This is the one
 * place for them: the colofon, privacy statement, about page and (ticket 26) the footer
 * read from here.
 *
 * TODO (owner, before launch): fill in every `null` below. Until then the pages show a
 * visible "to be added" placeholder; `missingLegalFields()` lists what is missing. These
 * are public facts (BW 3:15d requires them on the site), not secrets, so they live in the
 * repository rather than in environment variables.
 */

export type Operator = {
  /** Handelsnaam. */
  tradeName: string;
  /** Name of the eenmanszaak as registered with the KvK. */
  legalName: string | null;
  /** The owner, as named in "Built by …, founder of SnelVink". */
  ownerName: string | null;
  /** Postal address lines (decide on a business address before launch, spec §11.3 / V6). */
  address: readonly string[] | null;
  /** Contact address, also used for privacy requests. */
  email: string | null;
  /** KvK number (8 digits). */
  kvk: string | null;
  /** btw-identificatienummer (NL…B..), not the omzetbelastingnummer that contains the BSN. */
  btwId: string | null;
};

export const OPERATOR: Operator = {
  tradeName: "OpenFoodAlerts",
  legalName: null, // TODO (owner)
  ownerName: null, // TODO (owner)
  address: null, // TODO (owner)
  email: null, // TODO (owner)
  kvk: null, // TODO (owner)
  btwId: null, // TODO (owner)
};

const REQUIRED = ["legalName", "ownerName", "address", "email", "kvk", "btwId"] as const;

export type LegalField = (typeof REQUIRED)[number];

/** Fields that must be filled in before launch. */
export function missingLegalFields(operator: Operator = OPERATOR): LegalField[] {
  return REQUIRED.filter((field) => operator[field] === null);
}

/** SnelVink, the owner's HACCP software company (interest disclosure, spec §11.3). */
export const SNELVINK = { name: "SnelVink", url: "https://snelvink.nl/" } as const;

export type UtmMedium = "footer" | "about" | "home_box" | "zh_box";

/** Link to SnelVink with the UTM parameters of spec §11.3 rule 7. */
export function snelvinkUrl(medium: UtmMedium): string {
  const params = new URLSearchParams({
    utm_source: "openfoodalerts.nl",
    utm_medium: medium,
    utm_campaign: "v1",
  });
  return `${SNELVINK.url}?${params.toString()}`;
}

/**
 * When the owner last reviewed the referral rules (spec §11.3 rule 8: yearly, date shown
 * on the about page). 2026-10-25 is the date the rules were set in the spec.
 */
export const REFERRAL_RULES_REVIEWED_ON = "2026-10-25";

/** Version (date) of the privacy statement, disclaimer, about and colofon texts. */
export const LEGAL_TEXTS_VERSION = "2026-10-25";

/** Dutch data protection authority, for complaints (spec §11.1 #8). */
export const AP_URL = "https://autoriteitpersoonsgegevens.nl/";

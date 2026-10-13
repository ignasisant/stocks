/**
 * Yahoo names a listing's country in English ("United States"). The page
 * prints it in the reader's language: the common ones map to their ISO code
 * and `Intl.DisplayNames` words it; anything else prints as Yahoo wrote it.
 */

const CODES: Record<string, string> = {
  "United States": "US",
  Spain: "ES",
  "United Kingdom": "GB",
  Germany: "DE",
  France: "FR",
  Italy: "IT",
  Netherlands: "NL",
  Switzerland: "CH",
  Ireland: "IE",
  Belgium: "BE",
  Portugal: "PT",
  Sweden: "SE",
  Denmark: "DK",
  Norway: "NO",
  Finland: "FI",
  Austria: "AT",
  Luxembourg: "LU",
  Canada: "CA",
  Mexico: "MX",
  Brazil: "BR",
  Argentina: "AR",
  Chile: "CL",
  Japan: "JP",
  China: "CN",
  "Hong Kong": "HK",
  Taiwan: "TW",
  "South Korea": "KR",
  India: "IN",
  Singapore: "SG",
  Australia: "AU",
  Israel: "IL",
  Uruguay: "UY",
};

export function countryName(name: string, lang: string): string {
  const code = CODES[name];
  if (!code) return name;
  try {
    return new Intl.DisplayNames([lang], { type: "region" }).of(code) ?? name;
  } catch {
    return name;
  }
}

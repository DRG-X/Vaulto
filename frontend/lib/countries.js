import { COUNTRY_CURRENCY_MAP } from "./currencies";
import { UNIVERSITIES } from "./universities";

/**
 * One table of countries, with everything a screen needs about each of them:
 * name, flag, currency and dialling code.
 *
 * Onboarding used to draw its country list from `universities.js`, which only
 * lists the twelve countries we happen to have a university list for. Anyone
 * sending money home to Pakistan, Nigeria or Vietnam simply could not say so.
 * The corridor matters more than the university, so the corridor gets the full
 * list and the university list narrows off it.
 */
export const COUNTRIES_FULL = [
  { code: "IN", name: "India",                flag: "🇮🇳", dial: "+91"  },
  { code: "GB", name: "United Kingdom",       flag: "🇬🇧", dial: "+44"  },
  { code: "US", name: "United States",        flag: "🇺🇸", dial: "+1"   },
  { code: "AU", name: "Australia",            flag: "🇦🇺", dial: "+61"  },
  { code: "CA", name: "Canada",               flag: "🇨🇦", dial: "+1"   },
  { code: "IE", name: "Ireland",              flag: "🇮🇪", dial: "+353" },
  { code: "DE", name: "Germany",              flag: "🇩🇪", dial: "+49"  },
  { code: "FR", name: "France",               flag: "🇫🇷", dial: "+33"  },
  { code: "NL", name: "Netherlands",          flag: "🇳🇱", dial: "+31"  },
  { code: "CH", name: "Switzerland",          flag: "🇨🇭", dial: "+41"  },
  { code: "SG", name: "Singapore",            flag: "🇸🇬", dial: "+65"  },
  { code: "NZ", name: "New Zealand",          flag: "🇳🇿", dial: "+64"  },
  { code: "AE", name: "United Arab Emirates", flag: "🇦🇪", dial: "+971" },
  { code: "SA", name: "Saudi Arabia",         flag: "🇸🇦", dial: "+966" },
  { code: "QA", name: "Qatar",                flag: "🇶🇦", dial: "+974" },
  { code: "KW", name: "Kuwait",               flag: "🇰🇼", dial: "+965" },
  { code: "JP", name: "Japan",                flag: "🇯🇵", dial: "+81"  },
  { code: "CN", name: "China",                flag: "🇨🇳", dial: "+86"  },
  { code: "HK", name: "Hong Kong",            flag: "🇭🇰", dial: "+852" },
  { code: "MY", name: "Malaysia",             flag: "🇲🇾", dial: "+60"  },
  { code: "PH", name: "Philippines",          flag: "🇵🇭", dial: "+63"  },
  { code: "TH", name: "Thailand",             flag: "🇹🇭", dial: "+66"  },
  { code: "ID", name: "Indonesia",            flag: "🇮🇩", dial: "+62"  },
  { code: "VN", name: "Vietnam",              flag: "🇻🇳", dial: "+84"  },
  { code: "PK", name: "Pakistan",             flag: "🇵🇰", dial: "+92"  },
  { code: "BD", name: "Bangladesh",           flag: "🇧🇩", dial: "+880" },
  { code: "NG", name: "Nigeria",              flag: "🇳🇬", dial: "+234" },
  { code: "KE", name: "Kenya",                flag: "🇰🇪", dial: "+254" },
  { code: "GH", name: "Ghana",                flag: "🇬🇭", dial: "+233" },
  { code: "ZA", name: "South Africa",         flag: "🇿🇦", dial: "+27"  },
  { code: "MX", name: "Mexico",               flag: "🇲🇽", dial: "+52"  },
  { code: "BR", name: "Brazil",               flag: "🇧🇷", dial: "+55"  },
  { code: "TR", name: "Türkiye",              flag: "🇹🇷", dial: "+90"  },
].map(c => ({ ...c, currency: COUNTRY_CURRENCY_MAP[c.code] || null }));

const BY_CODE = Object.fromEntries(COUNTRIES_FULL.map(c => [c.code, c]));

export function countryByCode(code) {
  return code ? BY_CODE[String(code).toUpperCase()] || null : null;
}

export function currencyForCountry(code) {
  return countryByCode(code)?.currency || null;
}

export function dialCodeForCountry(code) {
  return countryByCode(code)?.dial || null;
}

/** Universities we can offer for a country — empty means "type it in". */
export function universitiesForCountry(code) {
  return (code && UNIVERSITIES[String(code).toUpperCase()]) || [];
}

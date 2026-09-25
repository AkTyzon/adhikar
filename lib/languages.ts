/**
 * Supported interface and answer languages.
 *
 * `nativeName` is what the selector shows, because a Tamil speaker looking for
 * Tamil scans for "தமிழ்", not for "Tamil". `script` drives the `lang` attribute
 * so screen readers switch pronunciation correctly — an answer rendered in Hindi
 * inside a `lang="en"` container is read out as mispronounced English.
 */
export interface Language {
  code: string;
  name: string;
  nativeName: string;
  /** BCP 47 tag for the `lang` attribute. */
  tag: string;
  /** Instruction fragment given to the model. */
  directive: string;
}

export const LANGUAGES: readonly Language[] = [
  { code: "en", name: "English", nativeName: "English", tag: "en-IN", directive: "Respond in English." },
  {
    code: "hi",
    name: "Hindi",
    nativeName: "हिंदी",
    tag: "hi-IN",
    directive: "Respond in Hindi (Devanagari script). Keep statute names and section numbers in English.",
  },
  {
    code: "hinglish",
    name: "Hinglish",
    nativeName: "Hinglish",
    tag: "en-IN",
    directive:
      "Respond in Hinglish: conversational Hindi written in the Latin script, the way people message each other. Keep statute names and section numbers in English.",
  },
  {
    code: "ta",
    name: "Tamil",
    nativeName: "தமிழ்",
    tag: "ta-IN",
    directive: "Respond in Tamil. Keep statute names and section numbers in English.",
  },
  {
    code: "te",
    name: "Telugu",
    nativeName: "తెలుగు",
    tag: "te-IN",
    directive: "Respond in Telugu. Keep statute names and section numbers in English.",
  },
  {
    code: "mr",
    name: "Marathi",
    nativeName: "मराठी",
    tag: "mr-IN",
    directive: "Respond in Marathi. Keep statute names and section numbers in English.",
  },
  {
    code: "bn",
    name: "Bengali",
    nativeName: "বাংলা",
    tag: "bn-IN",
    directive: "Respond in Bengali. Keep statute names and section numbers in English.",
  },
  {
    code: "kn",
    name: "Kannada",
    nativeName: "ಕನ್ನಡ",
    tag: "kn-IN",
    directive: "Respond in Kannada. Keep statute names and section numbers in English.",
  },
] as const;

export const DEFAULT_LANGUAGE = "en";

const INDEX = new Map(LANGUAGES.map((language) => [language.code, language]));

export function getLanguage(code: string | null | undefined): Language {
  return INDEX.get(code ?? "") ?? INDEX.get(DEFAULT_LANGUAGE)!;
}

export function isLanguageCode(value: unknown): value is string {
  return typeof value === "string" && INDEX.has(value);
}

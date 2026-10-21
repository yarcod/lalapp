import { useLocale } from 'next-intl'

// Lalapp's own interface strings, kept out of upstream's catalogs to avoid merge conflicts.
// Locales without an entry fall back to English.
const MESSAGES = {
  en: {
    personaCardTitle: 'Conversation partner',
    personaHint:
      'Choose who you talk with in chat and voice practice. You can switch character in any conversation.',
    personaGuideNote:
      '{name} is your guide: ask them to explain grammar or words, in Swedish if you like.',
    talkingWith: 'With {name}',
    switchCharacter: 'Switch character',
    role_peer: 'partner',
    role_guide: 'guide',
    age: '{age} years',
    'dialect_en-GB': 'British English',
    'dialect_en-US': 'American English',
    'dialect_es-ES': 'Spain',
    'dialect_es-MX': 'Mexico',
    saveError: 'Something went wrong. Please try again.',
  },
  sv: {
    personaCardTitle: 'Samtalspartner',
    personaHint:
      'Välj vem du pratar med i chatt- och röstövningar. Du kan byta karaktär i varje samtal.',
    personaGuideNote:
      '{name} är din guide: be hen förklara grammatik eller ord, gärna på svenska.',
    talkingWith: 'Med {name}',
    switchCharacter: 'Byt karaktär',
    role_peer: 'partner',
    role_guide: 'guide',
    age: '{age} år',
    'dialect_en-GB': 'brittisk engelska',
    'dialect_en-US': 'amerikansk engelska',
    'dialect_es-ES': 'Spanien',
    'dialect_es-MX': 'Mexiko',
    saveError: 'Något gick fel. Försök igen.',
  },
  es: {
    personaCardTitle: 'Compañero de conversación',
    personaHint:
      'Elige con quién hablas en el chat y en la práctica oral. Puedes cambiar de personaje en cada conversación.',
    personaGuideNote:
      '{name} es tu guía: pídele que te explique gramática o palabras.',
    talkingWith: 'Con {name}',
    switchCharacter: 'Cambiar de personaje',
    role_peer: 'compañero',
    role_guide: 'guía',
    age: '{age} años',
    'dialect_en-GB': 'inglés británico',
    'dialect_en-US': 'inglés americano',
    'dialect_es-ES': 'España',
    'dialect_es-MX': 'México',
    saveError: 'Algo salió mal. Inténtalo de nuevo.',
  },
} as const

export type LalappMessageKey = keyof (typeof MESSAGES)['en']

export function lalappMessage(
  locale: string,
  key: LalappMessageKey,
  values: Record<string, string | number> = {}
): string {
  const catalog =
    (MESSAGES as Record<string, Record<string, string>>)[locale] ?? MESSAGES.en
  const template = catalog[key] ?? MESSAGES.en[key]
  return template.replace(/\{(\w+)\}/g, (_, name: string) =>
    String(values[name] ?? `{${name}}`)
  )
}

export function useLalappT() {
  const locale = useLocale()
  return (key: LalappMessageKey, values?: Record<string, string | number>) =>
    lalappMessage(locale, key, values)
}

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
    nextUpTitle: 'Next up · picked for you',
    nextUpReason_practice:
      'Practise {skill}, where you have the most room to grow.',
    nextUpReason_review:
      'Review {focus}: your recent answers show it needs another look.',
    nextUpReason_preview: 'You are ahead in grammar: a first look at {unit}.',
    nextUpExpected: '{level} · about {percent}% expected right',
    nextUpCreate: 'Make this lesson',
    nextUpCreating: 'Writing your lesson…',
    nextUpStart: 'Start lesson',
    nextUpFailed: 'The lesson could not be created. Try again in a moment.',
    levelUpTitle: 'Ready for {level}',
    levelUpDesc:
      'Your recent results are confidently above the level of your current plan.',
    levelUpAction: 'Move up to {level}',
    levelUpConfirm:
      'This starts a new {level} plan with the same schedule. Your skill estimates carry over.',
    levelUpYes: 'Start {level} plan',
    cancel: 'Cancel',
    skill_grammar: 'grammar',
    skill_vocabulary: 'vocabulary',
    skill_reading: 'reading',
    skill_writing: 'writing',
    skill_listening: 'listening',
    skill_speaking: 'speaking',
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
    nextUpTitle: 'Nästa steg · valt åt dig',
    nextUpReason_practice: 'Öva {skill}, där du har mest att vinna.',
    nextUpReason_review:
      'Repetera {focus}: dina senaste svar visar att det behöver nötas.',
    nextUpReason_preview:
      'Du ligger före i grammatik: en första titt på {unit}.',
    nextUpExpected: '{level} · du väntas klara cirka {percent} %',
    nextUpCreate: 'Skapa lektionen',
    nextUpCreating: 'Skriver din lektion…',
    nextUpStart: 'Starta lektionen',
    nextUpFailed: 'Lektionen kunde inte skapas. Försök igen om en stund.',
    levelUpTitle: 'Redo för {level}',
    levelUpDesc:
      'Dina senaste resultat ligger tydligt över nivån i din nuvarande plan.',
    levelUpAction: 'Gå upp till {level}',
    levelUpConfirm:
      'Det här startar en ny plan på {level} med samma upplägg. Dina färdighetsuppskattningar följer med.',
    levelUpYes: 'Starta plan för {level}',
    cancel: 'Avbryt',
    skill_grammar: 'grammatik',
    skill_vocabulary: 'ordförråd',
    skill_reading: 'läsförståelse',
    skill_writing: 'skrivande',
    skill_listening: 'hörförståelse',
    skill_speaking: 'tal',
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
    nextUpTitle: 'Lo siguiente · elegido para ti',
    nextUpReason_practice: 'Practica {skill}, donde más puedes mejorar.',
    nextUpReason_review:
      'Repasa {focus}: tus últimas respuestas muestran que hace falta.',
    nextUpReason_preview:
      'Vas por delante en gramática: un primer vistazo a {unit}.',
    nextUpExpected: '{level} · se espera un {percent} % de aciertos',
    nextUpCreate: 'Crear la lección',
    nextUpCreating: 'Escribiendo tu lección…',
    nextUpStart: 'Empezar la lección',
    nextUpFailed:
      'No se pudo crear la lección. Inténtalo de nuevo en un momento.',
    levelUpTitle: 'Listo para {level}',
    levelUpDesc:
      'Tus resultados recientes están claramente por encima del nivel de tu plan.',
    levelUpAction: 'Subir a {level}',
    levelUpConfirm:
      'Esto empieza un plan nuevo de {level} con el mismo horario. Tus estimaciones de habilidad se conservan.',
    levelUpYes: 'Empezar plan de {level}',
    cancel: 'Cancelar',
    skill_grammar: 'gramática',
    skill_vocabulary: 'vocabulario',
    skill_reading: 'lectura',
    skill_writing: 'escritura',
    skill_listening: 'comprensión auditiva',
    skill_speaking: 'expresión oral',
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

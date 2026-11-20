export type Messages = { [key: string]: MessageValue }
type MessageValue = string | MessageValue[] | Messages

function isRecord(value: unknown): value is Messages {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

// Deep merge: the overlay wins on conflict, arrays are replaced, not merged.
export function mergeMessages(base: Messages, overlay: Messages): Messages {
  const merged: Messages = { ...base }
  for (const [key, value] of Object.entries(overlay)) {
    const current = merged[key]
    merged[key] =
      isRecord(current) && isRecord(value)
        ? mergeMessages(current, value)
        : value
  }
  return merged
}

async function readHomeFile(locale: string): Promise<Messages | null> {
  try {
    return (await import(`../../../messages/home/${locale}.json`)).default
  } catch {
    return null
  }
}

// Home strings for a locale. English fills any missing locale file or key, so
// a raw message key is never shown.
export async function loadHomeMessages(locale: string): Promise<Messages> {
  const english = (await readHomeFile('en')) ?? {}
  if (locale === 'en') return english
  const localized = await readHomeFile(locale)
  return localized ? mergeMessages(english, localized) : english
}

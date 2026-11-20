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

// Imports messages/home/<locale>.json. The caller supplies the import so the path
// sits next to upstream's messages import and resolves in the same layout.
export type HomeMessagesLoader = (
  locale: string
) => Promise<{ default: Messages }>

// Home strings for a locale. English fills any missing locale file or key, so
// a raw message key is never shown. A missing English file is a broken build
// (wrong path or layout), so it throws instead of rendering raw keys.
export async function loadHomeMessages(
  locale: string,
  load: HomeMessagesLoader
): Promise<Messages> {
  let english: Messages
  try {
    english = (await load('en')).default
  } catch (error) {
    throw new Error('Home messages for "en" could not be loaded', {
      cause: error,
    })
  }
  if (locale === 'en') return english
  try {
    return mergeMessages(english, (await load(locale)).default)
  } catch {
    return english
  }
}

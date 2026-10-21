// Lalapp feature switches. Build-time, so they can be turned off without code changes.
export const LALAPP_PLACEMENT_ENABLED =
  process.env.NEXT_PUBLIC_LALAPP_PLACEMENT !== 'false'

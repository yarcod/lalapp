// Lalapp feature switches. Build-time, so they can be turned off without code changes.
export const LALAPP_PLACEMENT_ENABLED =
  process.env.NEXT_PUBLIC_LALAPP_PLACEMENT !== 'false'
export const LALAPP_PERSONAS_ENABLED =
  process.env.NEXT_PUBLIC_LALAPP_PERSONAS !== 'false'
export const LALAPP_ADAPTIVE_ENABLED =
  process.env.NEXT_PUBLIC_LALAPP_ADAPTIVE !== 'false'
export const LALAPP_SCENARIOS_ENABLED =
  process.env.NEXT_PUBLIC_LALAPP_SCENARIOS !== 'false'

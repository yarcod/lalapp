import { LALAPP_SCENARIOS_ENABLED } from '@/lalapp/config'
import { useLalappT } from '@/lalapp/i18n'

type NavItem = { href: string; label: string }

function useScenarioNavItems(): NavItem[] {
  const t = useLalappT()
  return [{ href: '/scenarios', label: t('navScenarios') }]
}

function noNavItems(): NavItem[] {
  return []
}

/** Lalapp entries for the main navigation. Chosen once per build, so hook order is stable. */
export const useLalappNavItems = LALAPP_SCENARIOS_ENABLED
  ? useScenarioNavItems
  : noNavItems

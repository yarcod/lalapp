import { useSpeechSession } from '@/home/hooks/useSpeechSession'
import { useEnsureHomeProfile } from '@/home/store/profile'

/**
 * Home work for a signed-in app page: keeps the speech session open and loads
 * the learner's home profile. The app layout calls it once.
 */
export function useHomeSession(active: boolean): void {
  useSpeechSession(active)
  useEnsureHomeProfile(active)
}

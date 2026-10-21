'use client'

import { LalappNextUp } from '@/lalapp/adaptive/NextUp'
import { RhythmCard } from '@/lalapp/rhythm/RhythmCard'

/** Lalapp's dashboard cards, rendered by one hook in upstream's dashboard grid. */
export function LalappDashboard() {
  return (
    <>
      <LalappNextUp />
      <RhythmCard />
    </>
  )
}

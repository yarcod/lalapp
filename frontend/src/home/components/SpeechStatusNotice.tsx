'use client'

import Link from 'next/link'
import { useTranslations } from 'next-intl'
import { useSpeechSessionStore } from '@/home/store/speech-session'

// Explains why voice cannot start yet and, when it will not recover soon,
// points to the text tutor.
export function SpeechStatusNotice() {
  const t = useTranslations('conversation')
  const speechState = useSpeechSessionStore((s) => s.state)
  if (
    speechState !== 'switching' &&
    speechState !== 'off' &&
    speechState !== 'busy' &&
    speechState !== 'away'
  )
    return null
  return (
    <div
      role="status"
      className="border-fl-border bg-fl-surface text-fl-muted-1 mb-4 flex flex-wrap items-center gap-x-3 gap-y-1 border px-4 py-3 font-sans text-sm"
    >
      <span>
        {speechState === 'switching' || speechState === 'off'
          ? t('speechSwitching')
          : speechState === 'busy'
            ? t('speechBusy')
            : t('speechAway')}
      </span>
      {speechState !== 'switching' && speechState !== 'off' && (
        <Link href="/chat" className="text-fl-accent underline">
          {t('speechUseText')}
        </Link>
      )}
    </div>
  )
}

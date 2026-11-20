'use client'

import { useTranslations } from 'next-intl'

// Shown under the latest user bubble: marks it as what Lingu heard and offers
// a redo that discards the turn.
export function HeardLine({ onRedo }: { onRedo: () => void }) {
  const t = useTranslations('conversation')
  return (
    <div className="flex items-center justify-end gap-3 pr-9">
      <span className="text-fl-caption text-fl-muted-2 font-sans">
        {t('heardLabel')}
      </span>
      <button
        type="button"
        onClick={onRedo}
        className="text-fl-muted-1 border-fl-border hover:border-fl-border-2 hover:text-fl-fg border px-3 py-1 font-mono text-xs tracking-wide transition-colors"
      >
        {t('redo')}
      </button>
    </div>
  )
}

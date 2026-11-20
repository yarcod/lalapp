'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { useEnsureHomeProfile, useHomeProfileStore } from '@/home/store/profile'

export function ChildProfileToggle() {
  const t = useTranslations('settings')
  const isChild = useHomeProfileStore((s) => s.isChild)
  const setChild = useHomeProfileStore((s) => s.setChild)
  const [failed, setFailed] = useState(false)
  const [saving, setSaving] = useState(false)
  useEnsureHomeProfile()

  async function onChange(value: boolean) {
    setFailed(false)
    setSaving(true)
    try {
      await setChild(value)
    } catch {
      setFailed(true)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <div className="flex items-start gap-3">
        <input
          id="is-child"
          type="checkbox"
          checked={isChild}
          disabled={saving}
          onChange={(e) => void onChange(e.target.checked)}
          className="accent-fl-accent mt-0.5 h-4 w-4 flex-shrink-0 cursor-pointer"
        />
        <label
          htmlFor="is-child"
          className="text-fl-muted-2 cursor-pointer font-mono text-xs tracking-widest uppercase select-none"
        >
          {t('isChild')}
        </label>
      </div>
      <p className="text-fl-hint text-fl-muted-4 mt-1 font-mono">
        {t('isChildHint')}
      </p>
      {failed && (
        <p className="border-fl-error/40 text-fl-error mt-2 border px-4 py-3 font-mono text-xs">
          {'✕ '}
          {t('saveFailed')}
        </p>
      )}
    </div>
  )
}

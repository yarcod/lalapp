import { readdirSync, readFileSync } from 'fs'
import path from 'path'
import { describe, expect, it } from 'vitest'
import {
  loadHomeMessages,
  mergeMessages,
  type HomeMessagesLoader,
} from '@/home/i18n'

const HOME_DIR = path.resolve(import.meta.dirname, '../../../messages/home')

function readHome(file: string) {
  return JSON.parse(readFileSync(path.join(HOME_DIR, file), 'utf-8'))
}

// Tests read the repo files directly; the app's import path is Docker-relative
// (request.ts imports ../../messages, which only exists in the image layout).
const readRepoHome: HomeMessagesLoader = async (locale) => ({
  default: readHome(`${locale}.json`),
})

function keyPaths(value: unknown, prefix = ''): string[] {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return Object.entries(value).flatMap(([key, child]) =>
      keyPaths(child, prefix ? `${prefix}.${key}` : key)
    )
  }
  return [prefix]
}

describe('home translation overlay', () => {
  it('keeps the base and adds the overlay', () => {
    const merged = mergeMessages(
      { games: { title: 'Games' }, other: 'x' },
      { games: { stockEmpty: 'Empty' } }
    )
    expect(merged).toEqual({
      games: { title: 'Games', stockEmpty: 'Empty' },
      other: 'x',
    })
  })

  it('lets the overlay win on conflict and replaces arrays', () => {
    const merged = mergeMessages(
      { a: { b: 'base', list: ['1', '2'] } },
      { a: { b: 'overlay', list: ['3'] } }
    )
    expect(merged).toEqual({ a: { b: 'overlay', list: ['3'] } })
  })

  it('falls back to English for a missing locale', async () => {
    expect(await loadHomeMessages('xx', readRepoHome)).toEqual(
      readHome('en.json')
    )
  })

  it('fills a key missing from a locale with the English string', async () => {
    const en = readHome('en.json')
    const loaded = await loadHomeMessages('de', readRepoHome)
    expect(keyPaths(loaded).sort()).toEqual(keyPaths(en).sort())
  })

  it('throws when the English home file cannot be loaded', async () => {
    const missing: HomeMessagesLoader = () =>
      Promise.reject(new Error('Cannot find module'))
    await expect(loadHomeMessages('sv', missing)).rejects.toThrow(
      'Home messages for "en" could not be loaded'
    )
  })

  it('imports home messages from beside the upstream messages import', () => {
    const source = readFileSync(
      path.resolve(import.meta.dirname, '../../src/i18n/request.ts'),
      'utf-8'
    )
    const upstream = source.match(
      /import\(`([./]*)messages\/\$\{locale\}\.json`\)/
    )
    const home = source.match(
      /import\(`([./]*)messages\/home\/\$\{l\}\.json`\)/
    )
    expect(upstream, 'upstream messages import').not.toBeNull()
    expect(home, 'home messages hook import').not.toBeNull()
    expect(home![1]).toBe(upstream![1])
  })

  it('has the same key set in every home locale as English', () => {
    const expected = keyPaths(readHome('en.json')).sort()
    const files = readdirSync(HOME_DIR).filter((f) => f.endsWith('.json'))
    expect(files.length).toBeGreaterThan(1)
    for (const file of files) {
      expect(keyPaths(readHome(file)).sort(), file).toEqual(expected)
    }
  })
})

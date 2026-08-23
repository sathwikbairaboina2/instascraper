export type Themed = {
  name: string
  accent: string
  /** Text colour that rides on top of the accent. antd defaults to white,
   *  which fails contrast on the lighter accents. */
  onAccent: string
  darkBg: string
  lightBg: string
  note: string
}

export const THEMES: Themed[] = [
  { name: 'Graphite', accent: '#5b8cff', onAccent: '#ffffff', darkBg: '#0a0c10', lightBg: '#f5f6f8', note: 'Neutral. The photography carries the colour.' },
  { name: 'Coral', accent: '#ff6b57', onAccent: '#1b0d09', darkBg: '#0d0a0a', lightBg: '#fbf6f4', note: 'Warm and energetic.' },
  { name: 'Lime', accent: '#ccff42', onAccent: '#12160a', darkBg: '#0a0b0d', lightBg: '#f7f9f0', note: 'Loudest option.' },
  { name: 'Iris', accent: '#8b7bff', onAccent: '#12102a', darkBg: '#0b0a10', lightBg: '#f7f5fc', note: 'Soft and social.' },
  { name: 'Sea', accent: '#2fd6b0', onAccent: '#04201a', darkBg: '#080d0c', lightBg: '#f2faf7', note: 'Cool and calm.' },
]

export const DEFAULT_THEME = THEMES[0]

const KEY = 'instascraper:theme'

export type ThemePref = { name: string; dark: boolean }

export function loadPref(): ThemePref {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return { name: DEFAULT_THEME.name, dark: true }
    const parsed = JSON.parse(raw)
    const known = THEMES.some((t) => t.name === parsed?.name)
    return { name: known ? parsed.name : DEFAULT_THEME.name, dark: parsed?.dark !== false }
  } catch {
    return { name: DEFAULT_THEME.name, dark: true }
  }
}

export function savePref(pref: ThemePref) {
  try {
    localStorage.setItem(KEY, JSON.stringify(pref))
  } catch {
    // private window or blocked storage: the choice just is not remembered
  }
}

export function byName(name: string): Themed {
  return THEMES.find((t) => t.name === name) ?? DEFAULT_THEME
}

export type Tokens = {
  ground: string
  surface: string
  hairline: string
  text: string
  textSecondary: string
  action: string
  destructive: string
}

/** Instagram's own palette. One set, two modes -- the app follows the thing
 *  it indexes rather than inventing a look of its own. */
export const IG: { dark: Tokens; light: Tokens } = {
  dark: {
    ground: '#000000',
    surface: '#121212',
    hairline: '#262626',
    text: '#f5f5f5',
    textSecondary: '#a8a8a8',
    action: '#0095f6',
    destructive: '#ed4956',
  },
  light: {
    ground: '#ffffff',
    surface: '#fafafa',
    hairline: '#dbdbdb',
    text: '#000000',
    textSecondary: '#737373',
    action: '#0095f6',
    destructive: '#ed4956',
  },
}

/** The story ring, and nothing else. Instagram spends this sparingly and so
 *  do we: on buttons and headers it stops reading as Instagram and starts
 *  reading as an imitation of it. */
export const GRADIENT = 'conic-gradient(from 200deg, #fcb045, #fd1d1d, #833ab4, #fcb045)'

const KEY = 'instascraper:theme'

export type ThemePref = { dark: boolean }

export function loadPref(): ThemePref {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return { dark: true }
    // The key used to hold {name, dark}. Reading only `dark` back means an
    // existing user keeps their light/dark choice and loses a theme name
    // that no longer refers to anything.
    return { dark: JSON.parse(raw)?.dark !== false }
  } catch {
    return { dark: true }
  }
}

export function savePref(pref: ThemePref) {
  try {
    localStorage.setItem(KEY, JSON.stringify(pref))
  } catch {
    // private window or blocked storage: the choice just is not remembered
  }
}

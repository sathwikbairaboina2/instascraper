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
    action: '#e1306c',
    destructive: '#ed4956',
  },
  light: {
    ground: '#ffffff',
    surface: '#fafafa',
    hairline: '#dbdbdb',
    text: '#000000',
    textSecondary: '#5e5e5e',
    action: '#e1306c',
    destructive: '#c9303e',
  },
}

/** antd derives its layout ground (a #f5f5f5-ish grey) and container colour from the base colour, which leaves the
 *  content area a grey off the shared ground. Pinning them keeps the ground at `ground` and surfaces at `surface`. */
export function layoutTokens(t: Tokens) {
  return { colorBgLayout: t.ground, colorBgContainer: t.surface }
}

/** The story ring: a cone, so the sweep reads as a ring rather than a wipe. */
export const GRADIENT = 'conic-gradient(from 200deg, #fcb045, #fd1d1d, #833ab4, #fcb045)'

/** The same colours as a linear sweep, for anything rectangular: primary
 *  buttons, the active tab, the logo mark.
 *
 *  antd's `colorPrimary` takes one colour, not a gradient, so this cannot
 *  reach a focus ring, a checkbox tick or a 1px border. Those fall back to
 *  `action`, which is the magenta sampled from the middle of this sweep so
 *  the two read as the same family. */
export const GRADIENT_LINEAR = 'linear-gradient(135deg, #fcb045, #fd1d1d, #833ab4)'

const KEY = 'instascraper:theme'

export type ThemePref = { dark: boolean }

export function loadPref(): ThemePref {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return { dark: false }
    // The key used to hold {name, dark}. Reading only `dark` back means an
    // existing user keeps their light/dark choice and loses a theme name
    // that no longer refers to anything. Nothing stored means light.
    return { dark: JSON.parse(raw)?.dark === true }
  } catch {
    return { dark: false }
  }
}

export function savePref(pref: ThemePref) {
  try {
    localStorage.setItem(KEY, JSON.stringify(pref))
  } catch {
    // private window or blocked storage: the choice just is not remembered
  }
}

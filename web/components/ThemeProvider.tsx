'use client'

import { ConfigProvider, theme as antdTheme } from 'antd'
import { createContext, useContext, useEffect, useMemo, useState } from 'react'

import { mono, sans } from '@/lib/fonts'
import { byName, DEFAULT_THEME, loadPref, savePref, type Themed } from '@/lib/themes'

type Ctx = {
  themed: Themed
  dark: boolean
  setThemeName: (name: string) => void
  setDark: (dark: boolean) => void
}

const ThemeCtx = createContext<Ctx>({
  themed: DEFAULT_THEME,
  dark: true,
  setThemeName: () => {},
  setDark: () => {},
})

export const useThemePref = () => useContext(ThemeCtx)

export default function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [name, setName] = useState(DEFAULT_THEME.name)
  const [dark, setDarkState] = useState(true)

  // Read the stored preference after mount: localStorage does not exist on the
  // server, and reading it during render would desync the first paint.
  useEffect(() => {
    const pref = loadPref()
    setName(pref.name)
    setDarkState(pref.dark)
  }, [])

  const themed = useMemo(() => byName(name), [name])

  const value = useMemo<Ctx>(
    () => ({
      themed,
      dark,
      setThemeName: (n) => {
        setName(n)
        savePref({ name: n, dark })
      },
      setDark: (d) => {
        setDarkState(d)
        savePref({ name, dark: d })
      },
    }),
    [themed, dark, name],
  )

  return (
    <ThemeCtx.Provider value={value}>
      <ConfigProvider
        theme={{
          algorithm: dark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
          token: {
            colorPrimary: themed.accent,
            colorInfo: themed.accent,
            colorTextLightSolid: themed.onAccent,
            colorBgBase: dark ? themed.darkBg : themed.lightBg,
            borderRadius: 10,
            fontFamily: sans.style.fontFamily,
            fontFamilyCode: mono.style.fontFamily,
            fontSize: 14,
            controlHeight: 34,
            wireframe: false,
          },
          components: {
            Button: { borderRadius: 999, fontWeight: 600 },
            Input: { borderRadius: 999 },
            Segmented: {
              borderRadius: 999,
              itemSelectedColor: themed.onAccent,
              itemSelectedBg: themed.accent,
            },
            Tag: { borderRadiusSM: 999 },
          },
        }}
      >
        {children}
      </ConfigProvider>
    </ThemeCtx.Provider>
  )
}

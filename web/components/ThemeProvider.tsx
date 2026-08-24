'use client'

import { ConfigProvider, theme as antdTheme } from 'antd'
import { createContext, useContext, useEffect, useMemo, useState } from 'react'

import { mono, sans } from '@/lib/fonts'
import { IG, loadPref, savePref, type Tokens } from '@/lib/themes'

type Ctx = {
  tokens: Tokens
  dark: boolean
  setDark: (dark: boolean) => void
}

const ThemeCtx = createContext<Ctx>({
  tokens: IG.dark,
  dark: true,
  setDark: () => {},
})

export const useThemePref = () => useContext(ThemeCtx)

export default function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [dark, setDarkState] = useState(true)

  // Read the stored preference after mount: localStorage does not exist on the
  // server, and reading it during render would desync the first paint.
  useEffect(() => {
    setDarkState(loadPref().dark)
  }, [])

  const tokens = dark ? IG.dark : IG.light

  const value = useMemo<Ctx>(
    () => ({
      tokens,
      dark,
      setDark: (d) => {
        setDarkState(d)
        savePref({ dark: d })
      },
    }),
    [tokens, dark],
  )

  return (
    <ThemeCtx.Provider value={value}>
      <ConfigProvider
        theme={{
          algorithm: dark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
          token: {
            colorPrimary: tokens.action,
            colorInfo: tokens.action,
            colorError: tokens.destructive,
            colorTextLightSolid: '#ffffff',
            colorBgBase: tokens.ground,
            colorBorder: tokens.hairline,
            // Instagram's own controls are near-square. The pill radii went
            // with the five accent themes.
            borderRadius: 8,
            fontFamily: sans.style.fontFamily,
            fontFamilyCode: mono.style.fontFamily,
            fontSize: 14,
            controlHeight: 34,
            wireframe: false,
          },
          components: {
            Button: { borderRadius: 8, fontWeight: 600 },
            Input: { borderRadius: 8 },
            Segmented: { borderRadius: 8 },
            Tag: { borderRadiusSM: 6 },
          },
        }}
      >
        {children}
      </ConfigProvider>
    </ThemeCtx.Provider>
  )
}

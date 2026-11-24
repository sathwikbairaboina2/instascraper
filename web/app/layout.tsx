import { AntdRegistry } from '@ant-design/nextjs-registry'

import { RecreateProvider } from '@/components/RecreateProvider'
import ThemeProvider from '@/components/ThemeProvider'
import { sans } from '@/lib/fonts'

import './globals.css'
import './mobile.css'

export const metadata = { title: 'instascraper' }

// viewport-fit=cover lets the bars sit under the notch; mobile.css pads them with the safe-area insets.
export const viewport = { width: 'device-width', initialScale: 1, viewportFit: 'cover' } as const

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={sans.className}>
        <AntdRegistry>
          <ThemeProvider>
            <RecreateProvider>{children}</RecreateProvider>
          </ThemeProvider>
        </AntdRegistry>
      </body>
    </html>
  )
}

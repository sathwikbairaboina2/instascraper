import { AntdRegistry } from '@ant-design/nextjs-registry'

import { RecreateProvider } from '@/components/RecreateProvider'
import ThemeProvider from '@/components/ThemeProvider'
import { sans } from '@/lib/fonts'

import './globals.css'

export const metadata = { title: 'instascraper' }

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

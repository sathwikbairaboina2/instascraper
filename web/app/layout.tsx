import Link from 'next/link'

import Banner from '@/components/Banner'

import './globals.css'

export const metadata = { title: 'instascraper' }

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header>
          <Link href="/">instascraper</Link>
          <Link href="/activity">Activity</Link>
        </header>
        <Banner />
        <main>{children}</main>
      </body>
    </html>
  )
}

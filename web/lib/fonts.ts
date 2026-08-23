import { Geist, Geist_Mono } from 'next/font/google'

// Shared by the root layout and the theme provider.

export const sans = Geist({ subsets: ['latin'], display: 'swap' })
export const mono = Geist_Mono({ subsets: ['latin'], display: 'swap' })

import { Geist, Geist_Mono } from 'next/font/google'

// Kept out of layout.tsx: Next only allows a known set of exports from a
// layout module, so sharing anything else from there is a type error.
export const sans = Geist({ subsets: ['latin'], display: 'swap' })
export const mono = Geist_Mono({ subsets: ['latin'], display: 'swap' })

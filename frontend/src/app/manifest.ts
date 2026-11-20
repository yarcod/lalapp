import type { MetadataRoute } from 'next'

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: 'FreeLingo',
    short_name: 'FreeLingo',
    description: 'AI-powered language learning platform',
    start_url: '/',
    display: 'standalone',
    background_color: '#0c1316',
    theme_color: '#0c1316',
    icons: [
      { src: '/favicon.png', sizes: '256x256', type: 'image/png' },
      { src: '/logo.png', sizes: '1254x1254', type: 'image/png' },
    ],
  }
}

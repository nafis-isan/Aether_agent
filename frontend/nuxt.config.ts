export default defineNuxtConfig({
  compatibilityDate: '2025-07-15',
  devtools: { enabled: true },
  app: {
    head: {
      title: 'Aether',
      meta: [{ name: 'description', content: 'Aether personal AI assistant foundation' }],
      link: [{ rel: 'icon', type: 'image/png', href: '/aether-monogram.png' }]
    }
  },
  runtimeConfig: {
    public: {
      apiBase: process.env.NUXT_PUBLIC_API_BASE || 'http://localhost:8000/api/v1',
      wsBase: process.env.NUXT_PUBLIC_WS_BASE || 'ws://localhost:8000'
    }
  }
})

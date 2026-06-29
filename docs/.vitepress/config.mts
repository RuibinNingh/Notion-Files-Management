import { defineConfig } from 'vitepress'

const docsBase = process.env.DOCS_BASE || '/'

export default defineConfig({
  title: 'Notion Files Management',
  description: 'Notion Files Management 用户文档与开放 API 文档',
  lang: 'zh-CN',
  base: docsBase,
  cleanUrls: true,
  lastUpdated: true,
  themeConfig: {
    logo: '/logo.png',
    siteTitle: 'NFM Docs',
    nav: [
      { text: '用户指南', link: '/user/getting-started' },
      { text: '部署', link: '/deployment/docker' },
      { text: '开放 API', link: '/api/overview' },
      { text: '版本记录', link: '/version/v2.0.0-Beta-6-github-release' },
    ],
    sidebar: [
      {
        text: '开始使用',
        items: [
          { text: '文档首页', link: '/' },
          { text: '快速开始', link: '/user/getting-started' },
          { text: '配置说明', link: '/user/configuration' },
          { text: 'Windows 迁移包', link: '/user/windows' },
          { text: '常见问题', link: '/user/faq' },
        ],
      },
      {
        text: '部署',
        items: [
          { text: 'Docker', link: '/deployment/docker' },
          { text: 'systemd + venv', link: '/deployment/systemd-venv' },
          { text: 'GitHub Pages 文档站', link: '/deployment/github-pages' },
        ],
      },
      {
        text: '开放 API',
        items: [
          { text: '总览', link: '/api/overview' },
          { text: '鉴权与权限', link: '/api/auth' },
          { text: '调用示例', link: '/api/examples' },
        ],
      },
      {
        text: '版本记录',
        collapsed: true,
        items: [
          { text: 'v2.0.0 Beta 6 (2026-06-29)', link: '/version/v2.0.0-Beta-6-github-release' },
          { text: 'v2.0.0 Beta 5 (2026-06-29)', link: '/version/v2.0.0-Beta-5-github-release' },
          { text: 'v2.0.0 Beta 4 (2026-06-29)', link: '/version/v2.0.0-Beta-4-github-release' },
          { text: 'v2.0.0 Beta 3 (2026-06-28)', link: '/version/v2.0.0-Beta-3-github-release' },
          { text: 'v2.0.0 Beta 2 (2026-06-28)', link: '/version/v2.0.0-Beta-2-github-release' },
          { text: 'v2.0.0 Beta 1 (2026-06-28)', link: '/version/v2.0.0-Beta-1-github-release' },
          { text: 'v2.0.0 Beta 0 重构首发 (2026-06-28)', link: '/version/v2.0.0-Beta-0-github-release' },
          { text: 'v1.5.2 Status', link: '/version/v1.5.2-Status-github-release' },
          { text: 'v1.5.0 Status', link: '/version/v1.5.0-Status-github-release' },
          { text: 'v1.5.0 Beta', link: '/version/v1.5.0-Beta-github-release' },
          { text: 'v1.4.6 Beta', link: '/version/v1.4.6-Beta-github-release' },
        ],
      },
    ],
    socialLinks: [
      { icon: 'github', link: 'https://github.com/RuibinNingh/Notion-Files-Management' },
    ],
    search: {
      provider: 'local',
    },
    footer: {
      message: 'Released under the MIT License.',
      copyright: 'Copyright 2026 Ruibin_Ningh & Zyx_2012',
    },
  },
})

import type { Config } from 'tailwindcss';

/**
 * 设计系统说明：
 *
 * 颜色/阴影/圆角全部指向 globals.css 里的语义 CSS 变量，
 * 三套主题（theme-pastel / theme-soft / theme-warm）只改变量值，
 * 页面里统一用语义类：bg-canvas、bg-card、text-ink、text-muted、
 * bg-primary、text-on-primary、rounded-card、shadow-card …
 *
 * 注意：值是纯 var() 字符串，不要在类名里用透明度修饰符（如 bg-primary/50），
 * 需要半透明时使用令牌里现成的 *-soft 变量。
 */
const config: Config = {
  content: ['./src/**/*.{js,ts,jsx,tsx,mdx}'],
  theme: {
    extend: {
      colors: {
        /* 表面 */
        canvas: 'var(--canvas)',
        card: {
          DEFAULT: 'var(--card)',
          soft: 'var(--card-soft)',
        },
        /* 文字 */
        ink: 'var(--ink)',
        muted: 'var(--muted)',
        faint: 'var(--faint)',
        /* 主色 */
        primary: {
          DEFAULT: 'var(--primary)',
          strong: 'var(--primary-strong)',
          soft: 'var(--primary-soft)',
          softer: 'var(--primary-softer)',
        },
        'on-primary': 'var(--on-primary)',
        /* 功能色 */
        success: {
          DEFAULT: 'var(--success)',
          soft: 'var(--success-soft)',
        },
        danger: {
          DEFAULT: 'var(--danger)',
          soft: 'var(--danger-soft)',
        },
        warning: {
          DEFAULT: 'var(--warning)',
          soft: 'var(--warning-soft)',
        },
        accent: {
          DEFAULT: 'var(--accent)',
          soft: 'var(--accent-soft)',
        },
        /* 分组淡彩（pastel 系） */
        lilac: {
          DEFAULT: 'var(--lilac)',
          soft: 'var(--lilac-soft)',
        },
        mint: 'var(--mint)',
        butter: 'var(--butter)',
        coral: 'var(--coral)',
        /* 描边 */
        hairline: {
          DEFAULT: 'var(--hairline)',
          strong: 'var(--hairline-strong)',
        },
        /* 导航层 */
        nav: {
          DEFAULT: 'var(--nav-bg)',
          ink: 'var(--nav-ink)',
          muted: 'var(--nav-muted)',
        },
      },
      fontFamily: {
        body: 'var(--font-body)',
        display: 'var(--font-display)',
      },
      fontSize: {
        base: '18px',
      },
      borderRadius: {
        card: 'var(--radius-card)',
        btn: 'var(--radius-btn)',
        input: 'var(--radius-input)',
        pill: '999px',
      },
      boxShadow: {
        card: 'var(--shadow-card)',
        'card-hover': 'var(--shadow-card-hover)',
        btn: 'var(--shadow-btn)',
        float: 'var(--shadow-float)',
      },
    },
  },
  plugins: [],
};
export default config;

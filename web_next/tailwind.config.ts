import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./src/**/*.{js,ts,jsx,tsx,mdx}'],
  theme: {
    extend: {
      colors: {
        warm: {
          primary: '#F59E0B',
          bg: '#FFFBEB',
          dark: '#D97706',
          light: '#FEF3C7',
        },
      },
      fontSize: {
        base: '18px',
      },
    },
  },
  plugins: [],
};
export default config;

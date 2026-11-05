// Official Tailwind CSS v4 integration for Next.js. Next applies this PostCSS
// config in both bundlers (Turbopack by default, and `next build --webpack`).
const config = {
  plugins: {
    "@tailwindcss/postcss": {},
  },
};

export default config;

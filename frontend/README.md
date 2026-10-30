# IntentCut Frontend

Minimal Next.js App Router foundation generated with the official
`create-next-app` CLI. Uses TypeScript strict mode, Tailwind CSS v4, ESLint,
and npm. Application code lives in `src/`; `@/*` resolves to `src/*`.

Requires Node.js 20.9 or newer. Verified with Node.js 24.21.0 and npm 11.19.0.

Run these commands from `frontend/`:

```bash
npm ci
npm run dev -- --hostname 127.0.0.1
```

Open http://127.0.0.1:3000. The initial page is in `src/app/page.tsx`.

Validation:

```bash
npm run lint
npx tsc --noEmit
npm run build
```

For a production server, run `npm run start -- --hostname 127.0.0.1`
after building.

M3.1.1 contains only the foundation and a static placeholder. The design
system, studio layout, shadcn/ui, and backend integrations are deferred.

CLI reference: [create-next-app](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

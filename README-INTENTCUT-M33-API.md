# IntentCut M3.3 — modular typed API layer (manual, no Codex)

This is an overlay for the local repo. It **does not** contain backend changes, TanStack Query hooks, or Zustand stores. It maintains all existing named exports from `frontend/src/lib/api/client.ts` for backward compatibility, while adding AI Job and Artifact functions.

## Install safely

1. From the repository root, verify the current branch and inspect existing unstaged changes (`git status -sb`). If `frontend/src/lib/api/client.ts` has uncommitted work, make a backup before copying.
2. Download the ZIP, then unzip it into the repository root, preserving `frontend/src/lib/api` paths. The only intentionally replaced source file is `frontend/src/lib/api/client.ts`; it becomes a backward-compatible re-export facade.

```sh
cd ~/Documents/Hackaton-Meta/intentcut
cp frontend/src/lib/api/client.ts /tmp/intentcut-client-before-m33.ts
unzip -o ~/Downloads/intentcut_m33_api_layer.zip
```

Adapt the ZIP path to wherever your browser downloads it.
3. Add `"allowImportingTsExtensions": true` to the frontend `tsconfig.json` under `compilerOptions` **only if not already enabled**. All imports use explicit `.ts` suffixes so Node's native TypeScript runner can resolve tests.
4. Run from `frontend/` (also run existing project/media E2E later):

```sh
npm run lint
npx tsc --noEmit
node --test src/lib/api/client.test.mjs
node --test src/lib/api/modular-api.test.mjs
```

5. Run the existing UI E2E project/media tests when available. The actual FastAPI server must run for integration checks. No paid inference is invoked by these tests.

## Exports

- `client.ts` preserves `Project`, `MediaAsset`, `MediaList`, `ApiError`, `isProjectId`, `createProject`, `listMedia`, `listAllMedia`, `uploadMedia`.
- Added `getMedia`, `FirstCutRequest`, `AIJob`, `AIJobAccepted`, `createAIJob`, `getAIJob`, `AIArtifact`, `listAIArtifacts`, `downloadAIArtifact`, `loadAIArtifactJSON`.
- `transport.ts` is an internal HTTP implementation; domain modules should not be imported by unrelated UI components unless needed.

## Security and validation notes

- Like the current M3.2 frontend, API base URL is **local-only** and `credentials: 'omit'`; it is NOT production-ready.
- CORS does not supply authentication/authorization. The existing backend AI browser access guard remains in force.
- `FirstCutRequest` cannot send server-only source fingerprints. `POST` mutations are **never automatically retried**.
- Job `status` and artifact `kind` remain strings because the actual backend enum definitions were not provided; narrow them only after reading the backend domain contracts.
- Artifact JSON is returned as `unknown` because its actual schema is not yet established.
- This client preserves the conservative 500 MiB frontend request cap from M3.2 (backend default is 512 MiB).
- The UI must revoke any `URL.createObjectURL` it creates after a Blob preview is disposed.
- No upload byte progress is fabricated; server confirmation is the only upload-success signal.

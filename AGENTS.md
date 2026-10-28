## IntentCut Frontend Design Engineering Rules

For every approved frontend UI task:

1. Consult the installed UI/UX design skill before implementing visual components.
2. Apply the IntentCut design direction: premium cinematic dark editing studio, restrained mint/teal accents, excellent typography, deliberate spacing, and professional creative-software interactions.
3. Consult shadcn MCP when selecting UI primitives. Install components only when explicitly approved.
4. Implement only the currently approved micro-task.
5. When browser verification is applicable, use Playwright MCP to inspect the running local frontend.
6. Review screenshots at desktop (1440px), laptop (1024px), and mobile (375px).
7. Check responsiveness, accessibility, overflow, spacing, typography, empty states, and interaction feedback.
8. Run the relevant tests, lint, typecheck, and production build as applicable.
9. Report screenshots, findings, files changed, test results, and known limitations.
10. STOP and wait for Pilot review.

Never implement additional features, install unapproved dependencies, modify unrelated files, or automatically continue to the next task.

Plan Mode remains read-only. Browser interaction and code modification require explicit approval for the execution task.
---
name: codetutor-experience-contract
description: React 19 experience contract for the Code Tutor learning loop; state owner and lifetime, visible UI states, semantic tokens, Lucide, keyboard, focus and reduced motion.
keywords: [codetutor, learning, submission, react, ui, state, stories, accessibility]
min_score: 3
---
Record the owner and lifetime of every piece of state before writing a component. Server records (account, problem, submission, result, history) are owned by the backend and reach the UI only through a fetched, cache-keyed query. Draft code, form input and a pending submission are local state with an explicit lifetime; a pending state is never rendered as an accepted result.

Every screen renders visible loading, empty, error and success states, each reachable by keyboard with a managed focus target. Use semantic design tokens (surface, text, accent, danger) instead of literal colors, and Lucide icons only with an accessible label. Respect prefers-reduced-motion for every transition.

Do not claim the design is complete until real stories for loading, empty, error, success and pending exist and a visual test has run in a browser; a described story is not a rendered one.

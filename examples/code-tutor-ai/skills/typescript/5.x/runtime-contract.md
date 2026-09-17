---
name: codetutor-runtime-contract
description: TypeScript 5.9 runtime contract for Code Tutor submissions; pinned compiler and config, schema plus HTTP status checks, server-side ownership, cache reset and canonical results.
keywords: [codetutor, learning, submission, typescript, tsconfig, schema, authorization, cache]
min_score: 3
---
Load tsconfig and build with the project's pinned compiler (5.9 per package declaration). Do not paste a moduleResolution recipe such as node20 from another document, and treat a passing type check as separate from a runtime check.

Validate every API response at the boundary with a runtime schema and check the HTTP status explicitly; an unparsed 401, 403, 404 or 5xx is an error state, never an empty success. The server owns authorization: a client role, a cached list or a hidden button is not an authorization decision, and ownership of a submission is decided by the backend on each request.

Reset the query cache and any local store on logout or account switch so one user never sees another user's problems, submissions or history. Mark a submission solved only after the canonical server result (status plus counts) is fetched; the pending value is not the result, and history updates from the server record.

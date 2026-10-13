# Working agreement

Read `gpt.md` and `README.md` before changing this project. Update `gpt.md` at each milestone and at the end of work with architecture decisions, completed checks, unresolved issues, and next steps. Preserve unrelated files.

Students are records, never login accounts. Only admins and section-assigned teachers may operate attendance. Recognition only proposes a match: a teacher must explicitly confirm it. Enforce roster, session, liveness, time, and duplicate checks on the server. Never expose biometric embeddings or private files. Fail closed; never replace unavailable recognition with a fake successful match. Keep secrets, biometric data, model artifacts, uploads, and exports out of source control.

Use the lightweight Django test suite and frontend build for routine checks; use PostgreSQL integration tests for concurrency. Do not report real recognition accuracy without independent held-out capture groups. Update migrations with model changes. Keep the manual demo usable without downloading AI weights.

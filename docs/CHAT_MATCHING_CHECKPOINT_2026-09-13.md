# Chat matching checkpoint — 2026-09-13

## Scope

Carry the lawyer service's result envelope into both chat response paths and
render ranked matches separately from unranked browsing results. Preserve notices,
handle malformed candidate/profile shapes, reject non-finite scores and ratings,
and test the extracted presentation panel. Ranking and eligibility are unchanged.

Evidence-coverage propagation is a separate, already-existing commit:
`c625400609bad7060b3474ded30c3c34ec53b2d9`. It was not recreated or amended.

## Verification performed for this checkpoint

- Backend: **83 passed, 68 deselected, 0 failed, 0 errors** (39.40 seconds).
  Command from `backend/`:
  `venv/Scripts/python.exe -m pytest tests/test_chat_lawyer_match_contract.py tests/test_chat_socket.py tests/test_lawyer_matching.py -m "not llm and not integration" -p no:cacheprovider --junitxml=.test-tmp/chat-checkpoint-20260913.xml`
  Integration/provider tests were excluded; this does not revalidate the live matching engine.
- Frontend: **29 passed, 0 failed** (51.46 seconds), including 12 mounted panel tests.
  Command from `frontend/`:
  `node --import ./tests/support/register.mjs --test --test-force-exit tests/lawyer_match.test.mjs tests/lawyer_match_panel_dom.test.mjs`
- `git diff --check`: no whitespace errors.
- The initial backend attempt had **83 setup errors** because the sandbox denied
  pytest's temporary directory; no tests executed successfully in that attempt.
  The approved rerun above passed. No product code was changed to bypass the error.

## Earlier results reported by the implementer, not rerun here

- Evidence-coverage revision: backend **4855 passed, 86 skipped, 2 xfailed,
  0 failed**; frontend **595 passed**, build successful (also recorded in its commit).
- Initial chat fix, before subsequent hardening: full backend **4868 passed,
  86 skipped, 2 xfailed, 0 failed**. This is not a full-suite result for the final code.
- Following panel extraction: full frontend **624 passed, 0 failed**, build successful.
  Later changes were backend-only.
- Final finite-number hardening: contract file **54 passed**; a separately reported
  affected-backend run **47 passed**. These counts are not added together because
  their overlap is unspecified.

The full backend suite and frontend build were not rerun for this checkpoint.
Skipped, deselected, and expected-failure tests are not counted as passes.

## Follow-up boundary

Dependency declarations are a separate task. No OCR implementation, live provider
calls, production changes, or push are part of this checkpoint.

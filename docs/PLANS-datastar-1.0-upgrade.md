# Datastar 1.0 upgrade plan

Focused execution plan for moving fieldcam from Datastar RC.7 to the
1.0.0 stable release that shipped April 16, 2026 (Python SDK on the
17th). Pulled out of `PLANS-2026-05.md` so it can be tracked as a single
PR.

---

## 0. Goal

Get fieldcam onto Datastar **v1.0.0** (core JS) and **`datastar-py>=1.0.0`**,
verify all existing flows still work, and unblock the cleanup
opportunities (`data-bind`, `data-indicator`, `data-on-signal-patch`,
etc.) that the 1.0 line enables.

Out of scope for this PR (deliberately, to keep the diff reviewable):

- Switching CDN → local-only assets (tracked separately in
  `PLANS-2026-05.md` §1, plan-04 §6.2).
- The cleanup template rewrites in §7 below — those land as follow-up
  PRs once we know the upgrade itself is green.

---

## 1. Current state

| Component                                  | Version           | Where               |
| ------------------------------------------ | ----------------- | ------------------- |
| Core JS via CDN `<script>`                 | **v1.0.0-RC.7**   | `base_shell.html.j2` line 136 |
| Local copy in `static/`                    | **v1.0.0-RC.7**   | `cam-app/app/static/datastar.js` (header) |
| Python SDK                                 | **>=0.8.0**       | `cam-app/pyproject.toml` |
| Resolved by `uv.lock`                      | **0.8.0**         | `cam-app/uv.lock` |

Templates already use **post-RC.6 attribute syntax** (`data-foo:bar`,
not `data-foo-bar`), so no syntax migration is needed.

## 2. Target state

| Component                | Version       | Source |
| ------------------------ | ------------- | ------ |
| Core JS                  | **v1.0.0**    | https://cdn.jsdelivr.net/gh/starfederation/datastar@1.0.0/bundles/datastar.js |
| Python SDK               | **>=1.0.0**   | https://pypi.org/project/datastar-py/1.0.0/ |

---

## 3. What is *not* changing (API stability)

These behaviors we depend on are unchanged across RC.7 → 1.0.0:

- The HTTP fragment-patch contract (`datastar-selector`, `datastar-mode`)
  used by `_fragment_response()` and `DatastarResponse(SSE.patch_elements(...))`.
- `data-on:click="@post('/path', {contentType: 'form'})"` — form posts
  initiated from buttons inside `<form onsubmit="event.preventDefault()">`.
- `data-init="@get('/sse/list')"` style of opening an SSE stream on
  element creation. (See §4 below for the related cleanup-on-removal
  semantics, which actually got *safer* for our usage.)
- `data-signals:foo="..."`, `data-show`, `data-class`, `data-attr`,
  `data-text`, `data-on:event`, modal toggling via signals on `<body>`.
- The `Datastar-Request: true` header we already check in `csrf.py`
  and `routes._is_fragment_request()`.

## 4. What *is* changing (notable behavior deltas)

Pulled from the GitHub release notes for RC.8 and 1.0.0; only items
that could affect fieldcam are listed.

### 4.1 RC.7 → RC.8 (March 2, 2026)

- **`requestCancellation: auto` no longer cancels** the request when
  the **initiating element/attribute is removed from the DOM**. Opt in
  with the new `cleanup` option if you want the old behavior.
  - **Impact on fieldcam:** **Positive.** Our SSE streams open from
    `data-init="@get('/sse/list')"` on a `<div id="list-content">`.
    When the list HTML is morphed by an SSE patch, the wrapper div
    *can* be re-created. Under the new default, in-flight requests are
    not auto-killed by morph churn, which is what we want.
- **Backend action requests now resend signals on retry**, not the
  initial state — only matters if we use the auto-retry option (we
  don't set it explicitly).
- **Dollar-sign-in-string-literals** are no longer parsed as signal
  references. We do not currently have inline expressions of the form
  `'$foo'`, so this is safe.
- **`@capture` event-listener cleanup bug fix** — irrelevant (we don't
  use `__capture`).
- **`data-on-intersect __threshold` fix** — irrelevant.

### 4.2 RC.8 → 1.0.0 (April 16, 2026)

- **`Content-Type: application/json` is only set when the request has a
  body.** All our `@post` calls use `{contentType: 'form'}`, so we
  send `application/x-www-form-urlencoded`. No impact.
- **A `body` is only sent for non-GET, non-DELETE requests.** No
  impact (we use GET for SSE/fragments, POST for mutations).
- **Improved morphing of `input`, `select`, `textarea`.** Could
  improve the settings modal where we morph the form on save. Verify
  the dirty-state logic in `_settings_content.html.j2` still works
  (`data-on:input__this` reading `inp.dataset.original`).
- **`datastar-prop-change` event** — new, additive. We don't listen
  for it. No impact.
- **Submit-button value bug fix** — additive.
- **`__viewtransition` modifier interaction fixes** — we don't use
  `__viewtransition`. No impact.
- **`retryMaxWaitMs` renamed to `retryMaxWait`.** We do not set this
  option anywhere in the codebase. No code change needed; flagged so
  reviewers don't search for it.
- **Rocket rewritten as a JS API** — Rocket is a Pro/separate concept,
  not used by fieldcam.
- **New `data-bind` `__prop` and `__event` modifiers** — additive
  capability we can adopt later (§7 below).
- **New `data-on:event__document` modifier** — additive convenience.

### 4.3 Datastar-Py 0.8.0 → 1.0.0

The 1.0.0 release tracks core 1.0.0. Re-confirm at upgrade time, but
the API shape we use is stable:

- `datastar_py.ServerSentEventGenerator as SSE` — used in `routes.py`.
- `datastar_py.consts.ElementPatchMode` — used in `routes.py`.
- `datastar_py.fastapi.DatastarResponse` — used in `routes.py` and
  `main.py`.

No documented breaking renames in the 0.8.0 → 1.0.0 window for these
symbols. Follow §6.4 to verify imports still resolve after the bump.

---

## 5. Pre-flight check (do before merging)

Run from `cam-app/`:

```bash
rg -n "datastar" app/ pyproject.toml
rg -n "retryMaxWaitMs" app/
rg -n "__capture|__viewtransition|requestCancellation|cleanup" app/
rg -n "ServerSentEventGenerator|DatastarResponse|ElementPatchMode" app/
```

Expected:

- No hits for `retryMaxWaitMs`, `__capture`, or `__viewtransition`
  (confirms the §4 deltas don't affect us in surprise places).
- The Datastar imports are concentrated in `routes.py` and `main.py`.

---

## 6. Upgrade steps

Order matters: bump the JS first so the browser side is on 1.0 before
we change Python deps that might emit 1.0-only events.

### 6.1 Bump the local `static/datastar.js`

Replace `cam-app/app/static/datastar.js` with the v1.0.0 bundle:

```bash
curl -fsSL \
  -o cam-app/app/static/datastar.js \
  https://cdn.jsdelivr.net/gh/starfederation/datastar@1.0.0/bundles/datastar.js
head -1 cam-app/app/static/datastar.js   # should read: // Datastar v1.0.0
```

### 6.2 Bump the CDN reference

In `cam-app/app/templates/base_shell.html.j2`, change line 136:

```html
<script type="module" src="https://cdn.jsdelivr.net/gh/starfederation/datastar@1.0.0/bundles/datastar.js"></script>
```

(Both files are bumped in the same PR so the local copy and the CDN
fall-through agree.)

### 6.3 Bump `datastar-py`

In `cam-app/pyproject.toml`:

```toml
dependencies = [
    "apscheduler",
    "datastar-py>=1.0.0",
    ...
]
```

Then:

```bash
cd cam-app && uv lock && uv sync
```

### 6.4 Smoke-import check

```bash
cd cam-app
uv run python -c "
from datastar_py import ServerSentEventGenerator as SSE
from datastar_py.consts import ElementPatchMode
from datastar_py.fastapi import DatastarResponse
print('imports OK', SSE, ElementPatchMode, DatastarResponse)
"
```

### 6.5 Lint + format

```bash
cd cam-app && uv run ruff check . && uv run ruff format .
```

### 6.6 Rebuild and run

```bash
./cam-app/build.sh now    # docker build + compose up
# or for local dev:
cd cam-app && ./run.sh
```

---

## 7. Verification checklist

Run through each **manually** (or via a future TestClient script).
Tick each in the PR description.

### 7.1 Login + shell

- [ ] `GET /` while logged out → SPA shell with login fragment, no
      redirect (URL stays `/`).
- [ ] Bad password → red toast, `_fail_counts[ip]` increments
      (check logs).
- [ ] Good password → cookie set, list page renders.
- [ ] `GET /logout` → cookie cleared, login fragment shown.

### 7.2 List page + SSE

- [ ] List page renders with field thumbnail and detection text.
- [ ] `data-init="@get('/sse/list')"` opens an SSE connection (verify
      in DevTools Network tab — long-lived `text/event-stream` request).
- [ ] Schedule a job in another browser tab → first tab updates the
      list within ~2 s without a manual refresh.
- [ ] Modals open/close: `$showScheduleModal`, `$showHistoryModal`,
      `$showSettingsModal` (admin only).
- [ ] Escape key closes any open modal.

### 7.3 Schedule form (`/submit`)

- [ ] All inputs render, defaults present (date, time, 2h 30m).
- [ ] Destination radios switch the visible URL/key hint
      (`$addDest === 'youtube'`, etc.).
- [ ] "Ends at HH:MM" computed text updates as you change duration or
      start time. (This exercises the inline `data-text` IIFE.)
- [ ] Submit posts, returns Datastar SSE payload, modal closes, list
      patches in.
- [ ] Submit with empty stream key → form validation prevents POST.
- [ ] Custom destination requires `customUrl` starting with `rtmp(s)://`.

### 7.4 Active stream (live RTMP)

- [ ] Start a 60-second stream against a test key.
- [ ] List shows row with LIVE badge.
- [ ] `data-init="@get('/sse/stream-health')"` opens an SSE connection.
- [ ] Status cell updates with bitrate ("LIVE 4Mb/s"); duration cell
      updates ("MM:SS of MM:SS") roughly once per second.
- [ ] Cancel button: stream terminates, row disappears within ~2 s.

### 7.5 History modal

- [ ] Opens, body fragment loads from `/fragment/history`.
- [ ] Admin: trash icon visible per row. Click deletes and patches the
      modal body.

### 7.6 Settings modal (admin)

- [ ] Opens, body loads from `/fragment/settings`.
- [ ] Save button is disabled until any input differs from
      `data-original` (this is the trickiest 1.0 behavior to verify;
      see §4.2 morph note).
- [ ] Save toast shows; in dev with `--reload` the page reloads after
      ~5 s. (In prod, it does not reload — see `PLANS-2026-05.md` §3.6.)

### 7.7 Static asset

- [ ] `GET /static/datastar.js` returns 200 and the first line reads
      `// Datastar v1.0.0`.

### 7.8 Auth + CSRF

- [ ] POST without an Origin header (e.g. `curl -X POST /submit`) is
      either blocked by CSRF or login (depending on cookie).
- [ ] Datastar requests carry `Datastar-Request: true`; the helper
      `_is_fragment_request()` still returns true.

---

## 8. Rollback

If anything in §7 fails and isn't fixable in-PR:

```bash
git revert <upgrade-commit>
cd cam-app && uv lock && uv sync
./cam-app/build.sh now
```

The local `static/datastar.js` is restored by the revert. The CDN URL
falls back to RC.7. The Python SDK version pin returns to `>=0.8.0`.

---

## 9. Post-upgrade cleanup opportunities (follow-up PRs)

Tracked here so they aren't lost. None of these block the upgrade.

### 9.1 `data-bind` on the schedule form

`_add_form_body.html.j2` currently mirrors inputs to signals manually:

```html
<input ... data-on:input="$addStartTime = el.value"
            data-on:change="$addStartTime = el.value">
<select ... data-on:change="$addDurH = +el.value">...</select>
```

Replace with `data-bind:add-start-time` and `data-bind:add-dur-h` (the
1.0 `__prop` modifier handles non-default property bindings if needed).
Cuts ~10 lines and keeps two-way sync automatically.

### 9.2 `data-indicator` on submit / cancel

Both the schedule submit button and the cancel-stream icon fire on
`data-on:click="@post(...)"` with no in-flight feedback, so an
impatient double-click submits twice. Add:

```html
<button data-indicator:submitting
        data-attr:disabled="$submitting"
        data-on:click="@post('/submit', {contentType: 'form'})">
  ...
</button>
```

### 9.3 `data-computed` for "Ends at HH:MM"

Promote the inline IIFE in `_add_form_body.html.j2` to a named computed
signal so other elements can reuse it and the template gets readable.

### 9.4 `data-on:event__document` modifier

Replace `data-on:keydown.escape.window="..."` with
`data-on:keydown.escape__document="..."` for the stylistic upgrade.

### 9.5 `data-on-signal-patch`

Available since RC.7 but unused. Worth experimenting with for the
list-content fragment so it can react to specific signal changes
without server-side re-renders for every change.

### 9.6 `attribute_generator` Python helper

Adopt in the proposed `routes/_html.py` (see `PLANS-2026-05.md` §5.1)
for the toast and stream-health patches — replaces hand-rolled HTML
strings with a typed builder.

---

## 10. Datastar Pro: license analysis for fieldcam

Some appealing 1.0-era features (`data-match-media`, `data-persist`,
`@intl`, `data-animate`, `data-query-string`, `data-replace-url`,
Datastar Inspector, etc.) are **Datastar Pro**, which is a separate
commercial license sold by Star Federation (the 501(c)(3) non-profit
behind Datastar). Source: https://data-star.dev/pro.

### 10.1 Pricing (one-time, lifetime)

- **Solo** — $349 (sale) / $399 list — single developer or freelancer.
- **Team** — $1,299 / $1,499 list — organisations with up to 25
  employees.
- **Enterprise** — contact for pricing — organisations with 25+
  employees; adds dedicated support, custom licensing, optional
  training/launch help.

The license covers all current and future Pro features.

### 10.2 What you get

- Pro **attributes**: `data-animate`, `data-custom-validity`,
  `data-match-media`, `data-on-raf`, `data-on-resize`, `data-persist`,
  `data-query-string`, `data-replace-url`, `data-scroll-into-view`,
  `data-view-transition`.
- Pro **actions**: `@clipboard`, `@fit`, `@intl`.
- **Bundler** — generate a custom Datastar bundle with only the Pro
  plugins you need, optionally with an aliased attribute prefix
  (`data-{alias}-*`) to avoid collisions.
- **Datastar Inspector** — debugging web component for live signal
  inspection, signal-patch event log, SSE event log, persisted-signal
  viewer.
- **Rocket** — JS custom-element API for typed-prop encapsulated
  components (currently beta).
- **Stellar CSS** — variables-based design system, no build step
  (currently alpha).

### 10.3 The license restriction that matters for fieldcam

Quoting `data-star.dev/pro` directly:

> Adding the software to an open-source project is a violation of the
> license, and is strictly prohibited.
>
> Making the software available in a public repo is a form of
> redistribution, and is strictly prohibited.
>
> Source maps are not provided, and may not be used in non-development
> environments.

**Implication for this repo:** `jkrauska/fieldcam` is a public GitHub
repo. **Committing the Datastar Pro JS bundle (or its attributes
referenced in templates that are served from a public repo) violates
the license.** This is true regardless of whether we have purchased a
Solo, Team, or Enterprise license.

### 10.4 Realistic options if we want any Pro feature

In rough order of practicality:

1. **Skip Pro.** Replicate Pro features ourselves with vanilla JS or
   the existing free attributes. Star Federation explicitly says this
   is fine — equivalent functionality is achievable without Pro.
   - For `@intl`: 5 lines of `Intl.DateTimeFormat` in
     `base_shell.html.j2` already does what `convertLocalTimes()`
     does today.
   - For `data-persist`: a tiny `localStorage` watcher in vanilla JS.
   - For `data-match-media`: `window.matchMedia('(max-width: 600px)')`
     and a signal write in a `data-on:load` block.
2. **Make the repo private.** Commit the Pro bundle, comply with the
   "no public repos / no redistribution" clause. This contradicts the
   project's current posture.
3. **Two-repo split.** Keep `fieldcam` public **without** any Pro
   files; build the deployable container from a separate **private**
   repo / build pipeline that pulls in the Pro bundle as an "end
   product" (the license explicitly allows distributing in finished
   end-products that don't expose the Pro plugins for reuse). The
   public repo references the bundle by URL only and has no Pro
   attributes in committed templates. Operational overhead is real.
4. **Use only Datastar Inspector during development.** The Inspector
   is a Pro feature too, but it can live in a developer's local
   browser dev-tools / extension rather than in the repo. Worth a
   re-read of the license terms before relying on this.

### 10.5 Recommendation

Given fieldcam's size, the volunteer/OSS posture, and that **no Pro
feature is on the critical path for any planned work**, the
recommendation is **Option 1: stay on the free MIT core**.

Re-evaluate Pro only if:

- We actively need `data-match-media` for the mobile-card layout
  (plan 04 §5.4) **and** decide rolling our own `matchMedia` listener
  is not acceptable, **and**
- We are willing to either restructure into the two-repo split (10.4
  Option 3) or accept making the repo private.

If we do buy Pro for unrelated reasons (e.g. developer convenience on
other projects), donating it to Star Federation is itself a worthwhile
support gesture for the OSS framework we depend on, but the license
text is unambiguous about not vending the Pro bits through this
public repo.

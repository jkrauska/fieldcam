# Datastar Pro feasibility study for fieldcam

Companion to `PLANS-datastar-1.0-upgrade.md` §10. That section called for
"a deeper look at the Pro features" — this doc *is* that deeper look.

For each Pro feature, the format is:

1. **What it is** (one line, plus the official `data-*` reference link).
2. **Where it would map in fieldcam** (file + concrete pattern, or "no
   real use case").
3. **Free alternative** (vanilla JS / existing free Datastar attribute,
   with an honest line-count estimate).
4. **Verdict** (Buy, Skip, or Defer).

A summary table and final recommendation are at the bottom.

---

## Reminder of the licensing constraint

Pro features cannot legally be committed to this repo as long as
`jkrauska/fieldcam` is a public GitHub repository. The license:

> Adding the software to an open-source project is a violation of the
> license, and is strictly prohibited.
>
> Making the software available in a public repo is a form of
> redistribution, and is strictly prohibited.

So "would we use it" has two parts:

- **Would the code benefit?** (Pure technical merit.)
- **Could we actually ship it?** (License-compatible path: private
  repo, two-repo split, or developer-local only.)

Each verdict below addresses both.

---

## 1. Pro Attributes

### 1.1 `data-animate`

Animates element attributes over time, reactively from a signal.

**Where in fieldcam:** the toast notification has a CSS keyframe fade:

```50:50:cam-app/app/templates/base_shell.html.j2
        @keyframes toast-fade { 0%,70% { opacity:1 } 100% { opacity:0; visibility:hidden } }
```

Used from the toast HTML constructed in `routes.py`:

```542:545:cam-app/app/routes.py
    toast = (
        f'<div class="toast show align-items-center text-white {bg} border-0"'
        ' role="alert" style="animation:toast-fade 2s ease-in forwards">'
        f'<div class="toast-body text-center">{message}</div></div>'
    )
```

Could in theory animate per-row "LIVE" badges or the field-thumb
crossfade on snapshot update, but those are not requested features.

**Free alternative:** the existing 1-line CSS `@keyframes` is already
the simplest possible solution. The Pro attribute does not improve it.

**Verdict: Skip.** No technical benefit over `@keyframes` for this
codebase.

---

### 1.2 `data-custom-validity`

Sets HTML5 custom validity from a Datastar expression. Best for
**cross-field** validation (e.g. "end > start").

**Where in fieldcam:** four places use HTML5 `reportValidity()`:

```9:9:cam-app/app/templates/_login_content.html.j2
        <button type="button" id="login-btn" class="btn btn-primary w-100" data-on:click="if(el.closest('form').reportValidity()){@post('/login', {contentType: 'form'})}">Login</button>
```

```91:91:cam-app/app/templates/_add_form_body.html.j2
    <button type="button" class="btn btn-primary" data-on:click="if(el.closest('form').reportValidity()){@post('/submit', {contentType: 'form'}); $showScheduleModal = false}"><i class="bi bi-plus-circle-fill" style="color: white; font-size: 1rem;"></i> Submit This Stream</button>
```

```33:34:cam-app/app/templates/_settings_content.html.j2
        data-on:click="if(el.closest('form').reportValidity()){@post('/settings/save', {contentType: 'form'})}">
    <i class="bi bi-save me-1"></i> Save &amp; Restart
```

These all rely on **single-field** validation (`required`,
`pattern="rtmps?://.*"`). The only **cross-field** rule we have is
"end_time must not be in the past", and even that is enforced only
server-side in `submit_job()`:

```411:415:cam-app/app/routes.py
    if end_datetime < now:
        raise HTTPException(
            status_code=400,
            detail="This stream's end time is in the past. Please pick a later date or time.",
        )
```

Pro `data-custom-validity` would let us catch that client-side. Worth?
The form has `$addStartTime`, `$addDurH`, `$addDurM` signals already
(once we adopt `data-bind`, see upgrade doc §9.1). A computed
`endsInPast` signal feeding `data-custom-validity` would prevent the
round-trip.

**Free alternative:** ~5 lines of vanilla JS in
`_add_form_body.html.j2`:

```js
function onChange() {
  const inp = document.getElementById('add-startTime');
  const ends = startPlusDuration(); // tiny helper
  inp.setCustomValidity(ends < new Date() ? 'End time is in the past.' : '');
}
```

Or even simpler: server already returns a 400 with a clear message; we
could just surface that as a toast.

**Verdict: Skip.** Real benefit (one client-side check) but the free
fallback is trivial. Not worth a license alone.

---

### 1.3 `data-match-media`

Two-way binds a signal to a `window.matchMedia(...)` query and keeps
it in sync as the query state changes.

**Where in fieldcam:** there is no current responsive logic — the
list uses `table-responsive` (Bootstrap horizontal scroll on small
screens) and not a separate card layout. Plan-04 §5.4 ("Mobile card
layout") would be the user. With `data-match-media:is-narrow="'(max-width: 600px)'"`
plus a `data-show` on each layout, the swap is one line per layout.

**Free alternative:** ~6 lines in `base_shell.html.j2`:

```js
const mq = window.matchMedia('(max-width: 600px)');
function sync() { /* set a top-level signal via Datastar's signal API */ }
mq.addEventListener('change', sync); sync();
```

Or just CSS media queries with `display: none` swaps — no JS at all.
For a table↔cards swap that's the natural solution.

**Verdict: Skip.** Pure CSS handles the layout swap; no Datastar
involvement is needed.

---

### 1.4 `data-on-raf`

Runs an expression on every `requestAnimationFrame` tick.

**Where in fieldcam:** **nowhere.** No 60-fps animations, no game
loop, no canvas. The closest thing is a 1-second SSE update of stream
stats — three orders of magnitude too slow for `raf`.

**Verdict: Skip.** No use case.

---

### 1.5 `data-on-resize`

Runs an expression whenever an element's dimensions change
(`ResizeObserver` under the hood).

**Where in fieldcam:** **nowhere currently.** Possible future use if
we ever do an in-page chart that has to re-fit when the modal opens.
None today.

**Free alternative:** `new ResizeObserver(...)` is one line of JS.

**Verdict: Skip.** No current use case.

---

### 1.6 `data-persist`

Persists signals to `localStorage` (or `sessionStorage` with
`__session`) automatically. Filterable via include/exclude regex.

**Where in fieldcam:** **no signals are persisted today.** Plausible
future signals worth persisting:

- Dark mode preference (we have no dark mode yet).
- "Remember last destination" (`$addDest`) so a returning operator
  doesn't have to re-pick GameChanger every time.
- "Default duration" (`$addDurH`, `$addDurM`).
- Dismissed banner state (none today).

Of those, the only one I would actually want is "remember last
destination + duration" — a real workflow improvement.

**Free alternative:** ~10 lines in `base_shell.html.j2`:

```js
const KEY = 'fc-prefs';
const saved = JSON.parse(localStorage.getItem(KEY) || '{}');
// merge into Datastar signals via the JS API on init
addEventListener('datastar-signal-patch', e => {
  // pick the few keys we care about, write them back
  localStorage.setItem(KEY, JSON.stringify(...));
});
```

Workable but more fiddly than `data-persist:fc-prefs="{include: /^add(Dest|Dur)/}"`.

**Verdict: Defer.** If we add user preferences as a deliberate
feature, re-evaluate. Not worth a license today since we have zero
persisted signals.

---

### 1.7 `data-query-string`

Two-way syncs signals with URL query params. Optional `__history`
modifier writes to `pushState` on change and restores on `popstate`.

**Where in fieldcam:** **no filtered/sortable lists today.** The
History modal shows everything. If we ever add filters ("only failed",
"last 7 days", "by destination") this is the cleanest way to make
those filters bookmarkable/shareable.

Also: the proposed admin SPA reorganization (plan-04 §8.2) talked
about replacing the manual `pushState` pattern; if we go that route
this is the natural building block.

**Free alternative:** `URLSearchParams` + manual signal sync; ~20
lines for a feature with filters.

**Verdict: Defer.** Strong fit *if* we add list filters or formal
SPA routing. Not worth a license for a hypothetical.

---

### 1.8 `data-replace-url`

Replaces the URL via `history.replaceState` from a signal expression,
no page reload.

**Where in fieldcam:** **nowhere meaningful.** We have one small use
of `window.location.href = ...` from the login response:

```114:118:cam-app/app/main.py
            out = Response(
                content=f"window.location.href = {json.dumps(next_url)};",
                media_type="text/javascript",
            )
```

That is a real navigation, not a URL replace. `data-replace-url`
would only matter if we adopted SPA routing (see 1.7).

**Verdict: Skip.** Not currently applicable.

---

### 1.9 `data-scroll-into-view`

Scrolls the element into view, smooth or instant.

**Where in fieldcam:** **nowhere currently.** Possible future use:
when the SSE list update adds a new active stream row, scroll the
table to it. That's polish, not a needed feature, and the Streams
section is on the visible part of the page already.

**Free alternative:** `element.scrollIntoView({behavior:'smooth'})`
is one line.

**Verdict: Skip.** No use case strong enough to justify a license.

---

### 1.10 `data-view-transition`

Sets `view-transition-name` so the View Transitions API can do a
named element morph during a DOM patch.

**Where in fieldcam:** **no view transitions today**, and we
deliberately do not pass `useViewTransition` on any of our SSE
patches. Possible polish for the modal-open / list-update flow but
purely cosmetic.

**Verdict: Skip.** Pure polish, no functional need.

---

### 1.11 `data-custom-validity` summary mention

Already covered in 1.2; included here so the count matches the Pro
attribute list.

---

## 2. Pro Actions

### 2.1 `@clipboard`

Copies a string (or base64-decoded string) to the clipboard.

**Where in fieldcam:** the stream-key copy buttons in
`_list_content.html.j2` use the existing JS helper:

```56:57:cam-app/app/templates/_list_content.html.j2
                        data-on:click="copyToClipboard('{{ stream.stream_key }}', el)"
                        title="{{ stream.stream_key }}">
```

```105:107:cam-app/app/templates/_list_content.html.j2
                        data-on:click="copyToClipboard('{{ job.kwargs.key }}', el)"
                        title="{{ job.kwargs.key }}">
```

…and the helper in `base_shell.html.j2`:

```139:145:cam-app/app/templates/base_shell.html.j2
        function copyToClipboard(text, element) {
            navigator.clipboard.writeText(text).then(function () {
                var originalText = element.innerText;
                element.innerText = "Copied!";
                setTimeout(function () { element.innerText = originalText; }, 2000);
            }).catch(function (err) { console.error("Failed to copy text: ", err); });
        }
```

`@clipboard('{{ key }}')` would replace the `data-on:click` value, but
we'd lose the "Copied!" feedback unless we wrote it ourselves anyway.
The base64 mode is nice for HTML-attribute safety but stream keys are
already URL-safe.

**Free alternative:** the existing 7-line helper is fine and provides
the visual feedback Pro doesn't bundle.

**Verdict: Skip.** Pro action saves zero lines net.

---

### 2.2 `@fit`

Linear interpolation between ranges (slider→percent, °C→°F, etc.).

**Where in fieldcam:** **nowhere.** No range inputs, no scaling
needs. The bitrate formatter (`_format_bitrate_short` in routes.py)
is integer division, not interpolation.

**Verdict: Skip.** No use case.

---

### 2.3 `@intl`

Browser-side locale-aware formatting via the `Intl` namespace
(DateTimeFormat, NumberFormat, RelativeTimeFormat, etc.).

**Where in fieldcam:** the existing locale-time conversion code in
`base_shell.html.j2` lines 147–161 uses a `MutationObserver` plus
plain `toLocaleDateString()` / `toLocaleTimeString()`:

```147:161:cam-app/app/templates/base_shell.html.j2
        function convertLocalTimes(root) {
            (root || document).querySelectorAll('.local-time').forEach(function (el) {
                if (el.dataset.converted) return;
                var raw = el.textContent.trim();
                if (!raw || raw.indexOf(':') === -1) return;
                raw = raw.replace(/(\.\d{3})\d+/, '$1');
                var d = new Date(raw + (raw.endsWith('Z') ? '' : 'Z'));
                if (isNaN(d)) return;
                el.textContent = d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
                el.dataset.converted = '1';
            });
        }
        new MutationObserver(function () { convertLocalTimes(); })
            .observe(document.body, {childList: true, subtree: true});
        convertLocalTimes();
```

`@intl('datetime', new Date($iso), {hour:'2-digit', minute:'2-digit'})`
inside a `data-text` would let us drop both this function and the
`MutationObserver` — but only if we (a) bind each timestamp into a
signal, or (b) use `data-text` to render it from a per-row string. Per
row that's more attribute soup than the current code.

There is also a "relative time" possibility ("started 5 minutes ago")
using `Intl.RelativeTimeFormat`, which is more useful than the
absolute time we show today.

**Free alternative:** the existing function works. For relative
times, ~10 lines using `Intl.RelativeTimeFormat` directly is roughly
equivalent.

**Verdict: Skip** for the current absolute-time formatting.
**Defer** if we decide we want relative times — and even then, vanilla
`Intl.RelativeTimeFormat` is small enough that a license is not
required.

---

## 3. Pro Tools

### 3.1 Bundler

Generates a custom Datastar bundle including only the plugins you
need, optionally with an aliased attribute prefix
(`data-{alias}-*`) to avoid attribute-name collisions with another
framework.

**Where in fieldcam:** the current core bundle is **~31 KB minified**
(`static/datastar.js`). We use roughly 12 attributes and a few
actions; a custom-bundled subset might cut that to ~15 KB. There is
no other framework competing for `data-*` so aliasing is not needed.

**Free alternative:** none — but the value is so marginal (15 KB on
the wire, cached forever) that it does not matter.

**Verdict: Skip.** Worth nothing on its own; only useful if Pro is
already purchased for something else.

---

### 3.2 Datastar Inspector

A web-component browser tool for live inspection of signals, signal
patches, SSE events, and persisted signals.

**Where in fieldcam:** this is the **single most genuinely useful Pro
piece for development work on this app.** The current debugging path
for "why didn't the list update?" or "which signal is stale?" is
console logs and DevTools Network panel.

The license interaction is interesting: the Inspector is a
browser-side dev tool. If a single licensed developer uses it locally
(loaded as a userscript / extension / dev-only HTML inclusion that is
never committed), the public repo never contains Pro code.

**Free alternative:** the free core supports `data-json-signals`
which dumps live signal state into an element you can put on the
page. Combined with browser DevTools, this covers the 80% case.

**Verdict: Defer / personal call.** Genuinely useful for development;
license cost ($349 Solo) would have to be justified by personal
productivity across this and other Datastar projects. Not a
fieldcam-budget line item.

---

### 3.3 Rocket

JS custom-element API for typed-prop encapsulated components.
Currently in **beta**.

**Where in fieldcam:** **nowhere.** Templates are server-rendered
Jinja and behavior is sprinkled via `data-*`. There are no reusable
components that would benefit from prop-typed encapsulation. The
schedule form is the only candidate and it's not reused.

**Verdict: Skip.** Wrong tool for this codebase.

---

### 3.4 Stellar CSS

Variables-based design system (CSS custom properties), no build
step. Currently in **alpha**.

**Where in fieldcam:** would replace Bootstrap, which we use heavily
(modals, badges, table classes, the nav, btn-outline-* throughout).
Replacing Bootstrap is a multi-day rewrite of every template.

**Verdict: Skip.** Alpha-stage; cost vs benefit nowhere close to
favorable; no immediate problem with Bootstrap.

---

## 4. Summary table

Each row: how often the feature would be used today, what the free
fallback costs, and the buy/skip/defer call.

| Pro feature              | Use today | Free fallback (lines) | Verdict |
| ------------------------ | --------- | --------------------- | ------- |
| `data-animate`           | 1 toast   | existing `@keyframes` (0) | Skip    |
| `data-custom-validity`   | 0–1 form  | `setCustomValidity` (~5) | Skip    |
| `data-match-media`       | 0 layouts | CSS or `matchMedia` (~6) | Skip    |
| `data-on-raf`            | 0         | n/a                   | Skip    |
| `data-on-resize`         | 0         | `ResizeObserver` (~3) | Skip    |
| `data-persist`           | 0 today   | localStorage (~10)    | Defer   |
| `data-query-string`      | 0 today   | `URLSearchParams` (~20) | Defer   |
| `data-replace-url`       | 0         | `history.replaceState` (~1) | Skip |
| `data-scroll-into-view`  | 0         | `scrollIntoView` (~1) | Skip    |
| `data-view-transition`   | 0         | n/a (cosmetic)        | Skip    |
| `@clipboard`             | 2 buttons | existing helper (7)   | Skip    |
| `@fit`                   | 0         | n/a                   | Skip    |
| `@intl`                  | 1 helper  | existing `Intl.*` (~15) | Skip   |
| Bundler                  | 0         | accept full bundle    | Skip    |
| Datastar Inspector       | dev only  | `data-json-signals` + DevTools | Defer (personal) |
| Rocket (beta)            | 0         | server-rendered Jinja | Skip    |
| Stellar CSS (alpha)      | 0         | Bootstrap is fine     | Skip    |

Counts: **13 Skip · 3 Defer · 0 Buy.**

---

## 5. Recommendation

**Do not buy a fieldcam-funded Datastar Pro license.**

Reasoning:

1. **Zero Pro features have a use case strong enough today** to
   justify even the Solo $349 against the equivalent vanilla
   alternatives, all of which are short and well-understood.
2. **The license restriction makes it operationally awkward** even
   if we wanted to: we'd have to either restructure into a two-repo
   build (private deploy repo pulls Pro into a public-template
   project) or make `fieldcam` private. Neither is justified by the
   current feature backlog.
3. **The two genuinely interesting features for fieldcam are both
   "Defer"** rather than "Buy":
   - `data-persist` if we ever ship operator preferences (remember
     last destination/duration).
   - `data-query-string` if we ever add list filters or a real SPA
     router (plan-04 §8.2).
4. **The Datastar Inspector is a personal-productivity decision**,
   not a project-budget item. If a maintainer wants it for use across
   multiple projects, the Solo license is a reasonable personal
   purchase. It can be used locally during development without ever
   committing Pro code to the public repo.

If `data-persist` or `data-query-string` ever moves from "speculative"
to "actually building", revisit this doc and the §10 license-path
options in `PLANS-datastar-1.0-upgrade.md` (skip / private repo /
two-repo split).

For now: **stay on the free MIT core.** Nothing in the planned work
is gated on Pro.

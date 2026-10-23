# 0034. Reach Instacart through a Kiki extension in the owner's own Chrome; Kiki fills the Cart and never checks out

- Status: Accepted
- Date: 2026-10-23
- Related: FR-0.36 to FR-0.40, NFR-0.9 (v0.17). Keeps 0007 (the laptop is the host), 0008 (plain tools).

## Context
The household orders from Wegmans through Instacart. Instacart's Developer Platform API is open to organisations only, so Kiki has to use the website as the owner does. The owner wants zero friction: their own Chrome, where Instacart is already signed in, no second profile to sign in to, nothing to click each time.

What was checked on the live site: an order page holds every line's placed Product id, its name, its count and whether it was found or replaced, in the page's own data (`window.__APOLLO_CLIENT__`), so one page load reads a whole Order. A Product page's **Add to cart** adds one, and its "N in cart" menu sets an exact count; a script's clicks work. Produce is counted by the piece in the Cart ("1 ct"), even when it's billed by weight.

## Options considered
- Playwright with its own Chrome profile: well known, but a second profile to sign in to, and the owner didn't want one.
- Playwright attached to the owner's Chrome: since Chrome 136 the remote-debugging switch is ignored on the default profile. Chrome 144's built-in remote debugging works on it, but asks to Allow every connection: a click at the laptop for each order.
- A Claude-driven browser (Claude in Chrome): copes with page changes, but costs about a dollar of tokens and minutes per run, works only from the Claude app, and behaves differently each time.
- A small extension of Kiki's own, loaded once in the owner's Chrome, doing fixed steps that Kiki asks for.

## Decision
A Manifest V3 extension in `browser/instacart`, loaded unpacked once. Kiki opens a tab with `chrome.exe https://www.instacart.com/...#kiki-<job id>-<port>`; the extension's service worker sees that tab, fetches the job from Kiki's `GET /instacart/job`, runs its steps in that tab only, with `chrome.scripting.executeScript` in the page's own world, posts `POST /instacart/result` and closes the tab. Its permissions are `tabs`, `scripting`, `https://www.instacart.com/*` and `http://localhost/*`.

Kiki fills the Cart and stops. The owner reviews and checks out in the Instacart app, so nothing spends money from the kitchen (README principle 5). Kiki sets each count rather than adding to it, so a second run gives the same Cart, and it never removes what it didn't put there.

Every page step checks what it reads and stops with a short code when the page isn't what it expects (`signed_out`, `needs_human`, `page_changed`, `wrong_address`, `no_page`); Kiki says it in one sentence and writes nothing from that page. It never tries to get past a sign-in or a human check.

## Consequences
+ The owner's own Chrome and sign-in; one setup step (Load unpacked), then nothing to click.
+ No new Python dependency, no tokens for reading pages, the same steps every time.
+ Reading an Order is one page load, not a click per line.
- Instacart's page and its internal data can change without notice. The checks make that a plain "Instacart changed its page" instead of a wrong Cart, but the extension then needs fixing.
- Instacart's terms likely don't allow automation. Kiki works at a person's pace and never checks out.
- Chrome may remind the owner now and then that a Developer-mode extension is installed.
- Switching Instacart's address is left to the owner: Kiki stops with `wrong_address` rather than changing it.
- Only the first page of the order history (10 orders) is read.
- Anything running on the laptop can post to Kiki's `localhost` endpoints, as before (ADR 0027).

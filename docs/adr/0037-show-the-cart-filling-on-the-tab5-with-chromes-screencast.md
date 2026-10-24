# 0037. Show the Cart filling on the Tab5 with Chrome's screencast of Kiki's tab

- Status: Accepted
- Date: 2026-10-23
- Related: FR-0.42, NFR-0.10 (v0.19). Builds on 0034 (the extension), 0028 (JPEG frames, newest only), 0033 (the native Tab5 UI).

## Context
While Kiki fills the Instacart Cart, the Tab5 says only "Filling cart, 4 of 12". The owner wants to watch it happen on the fridge: the browser tab Kiki is working in, on the Tab5's screen.

## Options considered
- `chrome.tabs.captureVisibleTab`: no warning in Chrome, but it needs `<all_urls>` or a click on the extension, it's limited to two captures a second, and it captures whichever tab is in front, which could be another of the owner's tabs.
- Kiki capturing the Chrome window from the desktop: only works while the window is on screen and uncovered, and it captures whatever covers it.
- `chrome.debugger` and DevTools' `Page.startScreencast` on Kiki's tab: Chrome sends a JPEG on every repaint, scaled to the size asked for. It's the same screencast `kiki.screen` uses (0028). It needs the `debugger` permission, and Chrome shows "started debugging this browser" while attached.

## Decision
The screencast, for `fill_cart` jobs only, on Kiki's own tab only. Chrome scales each frame to fit 720×360, the orb's slot on the Tab5. The extension posts one frame at a time to `POST /instacart/frame`; Kiki keeps only the newest for the running job; the Tab5 fetches `GET /instacart/frame` while "Filling cart" shows, decodes it in hardware and puts it where the orb is. The Tab5 asks for the next frame only after showing the last, so a slow link skips frames instead of queueing them. View only: taps on the Tab5 don't reach the page.

The frame goes through Kiki over HTTP, not a new port, because the Tab5 already talks to Kiki's UI server, and no new dependency is needed on either side.

## Consequences
+ The owner sees products land in the Cart from the kitchen; nothing to set up beyond reloading the extension.
+ A failed attach or a lost frame never stops the fill.
- Chrome shows its debugging bar for the minute a fill takes. Clicking its Cancel only ends the live view.
- The `debugger` permission can attach to any tab. The code attaches only to the tab Kiki opened, but the permission itself is broader than 0034's.
- Instacart's desktop page shrunk to 720 px is small: it shows progress more than it can be read.
- A tab behind another one, or a minimised window, doesn't repaint, so the Tab5 keeps the last frame until the tab is in front again.
- Frames, which may show the owner's name and address, travel over the home Wi-Fi unencrypted, as the streamed UI did (0027).

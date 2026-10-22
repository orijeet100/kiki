// On-screen keyboard for the Tab5 (device spike). kiki.screen injects it into the page it
// streams, because the headless browser rendering the page for the Tab5 has no keyboard of its
// own; the UI in a laptop browser never loads it. It opens when a text box is focused and
// lifts the docked text box above it.
(() => {
  const ROWS = ["1234567890", "qwertyuiop", "asdfghjkl'", "zxcvbnm,.?"];
  const css = `
    #kiki-kb { position: fixed; left: 0; right: 0; bottom: 0; z-index: 1000; display: none;
      grid-template-columns: repeat(10, 1fr); gap: 6px; padding: 10px 8px;
      background: var(--surface-1); border-top: 1px solid var(--hairline); font: 600 22px var(--font); }
    #kiki-kb.open { display: grid; }
    #kiki-kb button { height: 62px; border: 0; border-radius: var(--rounded-md);
      background: var(--surface-2); color: var(--ink); font: inherit; }
    #kiki-kb button:active { background: var(--hairline); }
    #kiki-kb .span2 { grid-column: span 2; }
    #kiki-kb .span5 { grid-column: span 5; }
    #kiki-kb .send { background: var(--primary); color: var(--on-primary); }
    body.kiki-kb-open .dock { bottom: var(--kiki-kb-height); }`;

  addEventListener("DOMContentLoaded", () => {
    const style = document.createElement("style");
    style.textContent = css;
    document.head.append(style);
    const kb = document.createElement("div");
    kb.id = "kiki-kb";
    const key = (label, value, cls = "") => {
      const b = Object.assign(document.createElement("button"), { type: "button", textContent: label, className: cls });
      b.dataset.key = value;
      kb.append(b);
    };
    for (const row of ROWS) for (const c of row) key(c, c);
    key("Done", "done", "span2");
    key("space", " ", "span5");
    key("⌫", "back");
    key("Send", "send", "span2 send");
    document.body.append(kb);

    let input = null;
    const open = (el) => {
      input = el;
      kb.classList.add("open");
      document.body.style.setProperty("--kiki-kb-height", `${kb.offsetHeight}px`);
      document.body.classList.add("kiki-kb-open");
    };
    const close = () => {
      kb.classList.remove("open");
      document.body.classList.remove("kiki-kb-open");
      input?.blur();
      input = null;
    };
    document.addEventListener("focusin", (e) => e.target.matches("input, textarea") && open(e.target));
    // Keep the text box focused while keys are pressed.
    kb.addEventListener("mousedown", (e) => e.preventDefault());
    kb.addEventListener("pointerdown", (e) => e.preventDefault());
    kb.addEventListener("click", (e) => {
      const k = e.target.closest("button")?.dataset.key;
      if (!k || !input) return;
      if (k === "done") return close();
      if (k === "send") {
        input.form?.requestSubmit();
        return close();
      }
      const { selectionStart: s, selectionEnd: end } = input;
      if (k === "back") input.setRangeText("", s === end ? Math.max(0, s - 1) : s, end, "end");
      else if (input.value.length < (input.maxLength > 0 ? input.maxLength : Infinity)) input.setRangeText(k, s, end, "end");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
  });
})();

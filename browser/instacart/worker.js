// Kiki for Instacart (ADR 0034). Kiki opens a tab at instacart.com/...#kiki-<job id>; this
// worker asks Kiki for that job, does it in that tab only, sends the result back and closes
// the tab. Every other tab is left alone. Errors are short codes Kiki turns into a reply.

const BASE = "https://www.instacart.com";
// Stop the whole job: nothing after this can work, and Kiki says why.
const FATAL = new Set(["signed_out", "needs_human", "page_changed", "wrong_address", "no_page"]);
const running = new Set();

chrome.tabs.onCreated.addListener((tab) => start(tab.id, tab.pendingUrl || tab.url));
chrome.tabs.onUpdated.addListener((tabId, info) => start(tabId, info.url));

function start(tabId, url) {
  const m = (url || "").match(/^https:\/\/www\.instacart\.com\/[^#]*#kiki-([0-9a-f]+)-(\d+)$/);
  if (m && !running.has(m[1])) {
    running.add(m[1]);
    run(tabId, m[1], `http://localhost:${m[2]}`);
  }
}

async function run(tabId, id, kiki_url) {
  const kiki = (method, path, body) => call(kiki_url, method, path, body);
  let result;
  try {
    const job = await kiki("GET", "/instacart/job");
    if (!job || job.id !== id) throw new Error("stale_job");
    if (job.kind === "reload") {
      // After an edit to these files: answer, close the tab, then load the new code.
      await kiki("POST", "/instacart/result", { id, ok: true, data: {} });
      await chrome.tabs.remove(tabId).catch(() => {});
      return chrome.runtime.reload();
    }
    result = { id, ok: true, data: await JOBS[job.kind](tabId, job, kiki) };
  } catch (e) {
    result = { id, ok: false, error: e.message };
  }
  try {
    await kiki("POST", "/instacart/result", result);
  } finally {
    chrome.tabs.remove(tabId).catch(() => {});
  }
}

async function call(kiki_url, method, path, body) {
  const r = await fetch(kiki_url + path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body && JSON.stringify(body),
  });
  if (r.status === 204) return null;
  if (!r.ok) throw new Error(`kiki_${r.status}`);
  return r.json();
}

const JOBS = {
  // The Store's delivered orders on the first page of the order history that Kiki hasn't read.
  async read_orders(tabId, job) {
    const { orders: list } = await go(tabId, "/store/account/orders", "order_list");
    const slug = (name) => (name || "").toLowerCase().replace(/[^a-z0-9]/g, "");
    const wanted = list.filter((o) => o.delivered && slug(o.store) === slug(job.store) && !job.known.includes(o.id));
    const orders = [];
    for (const o of wanted) {
      const { order } = await go(tabId, `/store/orders/${o.id}`, "order");
      orders.push({ ...order, list_items: o.items });
    }
    return { orders };
  },

  async search(tabId, job) {
    return go(tabId, searchPath(job.store, job.query), "search");
  },

  async fill_cart(tabId, job, kiki) {
    const lines = [];
    for (const [i, line] of job.lines.entries()) {
      kiki("POST", "/instacart/progress", { id: job.id, done: i, total: job.lines.length }).catch(() => {});
      lines.push(await fillLine(tabId, job, line));
    }
    return { lines };
  },
};

// One Item: its Product, or the top search result for this Cart only; sold out falls back too.
async function fillLine(tabId, job, line) {
  let id = line.product_id;
  let reason = null;
  if (!id) {
    id = await topResult(tabId, job.store, line.query);
    reason = "no_product";
    if (!id) return { ...line, status: "failed", reason: "not_found" };
  }
  let r = await go(tabId, `/store/${job.store}/products/${id}`, "cart", { quantity: line.quantity, address: job.address });
  if (r.error === "unavailable") {
    const other = await topResult(tabId, job.store, line.query, id);
    if (!other) return { ...line, status: "failed", reason: "sold_out", product_name: r.name };
    id = other;
    reason = "sold_out";
    r = await go(tabId, `/store/${job.store}/products/${id}`, "cart", { quantity: line.quantity, address: job.address });
  }
  if (r.error) return { ...line, status: "failed", reason: r.error, product_id: String(id), product_name: r.name };
  return { ...line, status: reason ? "top_match" : "added", reason, product_id: String(id), product_name: r.name, quantity: r.quantity };
}

async function topResult(tabId, store, query, skip) {
  const { results } = await go(tabId, searchPath(store, query), "search");
  const others = results.filter((x) => x.id !== String(skip));
  const hit = others.find((x) => x.bought) || others[0];
  return hit && hit.id;
}

function searchPath(store, query) {
  return `/store/${store}/s?k=${encodeURIComponent(query)}`;
}

// Load a page in Kiki's tab, then run one step of `page` in it.
async function go(tabId, path, op, arg) {
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(done);
      reject(new Error("no_page"));
    }, 30000);
    const done = (id, info) => {
      if (id === tabId && info.status === "complete") {
        clearTimeout(timer);
        chrome.tabs.onUpdated.removeListener(done);
        resolve();
      }
    };
    chrome.tabs.onUpdated.addListener(done);
    chrome.tabs.update(tabId, { url: BASE + path }).catch(reject);
  });
  const [{ result }] = await chrome.scripting.executeScript({
    target: { tabId },
    world: "MAIN", // the page's own data (window.__APOLLO_CLIENT__) is only visible here
    func: page,
    args: [op, arg || null],
  });
  if (!result) throw new Error("page_changed");
  if (result.error && FATAL.has(result.error)) throw new Error(result.error);
  return result;
}

// Runs inside the Instacart page, so it can't use anything from this file: keep it self-contained.
async function page(op, arg) {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const until = async (test, ms = 15000) => {
    for (const end = Date.now() + ms; Date.now() < end; await sleep(250)) {
      try {
        const v = test();
        if (v) return v;
      } catch (e) {}
    }
    return null;
  };
  const text = () => (document.body ? document.body.innerText : "");

  if (/^\/(login|signup)/.test(location.pathname)) return { error: "signed_out" };
  const apollo = await until(() => window.__APOLLO_CLIENT__);
  if (!apollo) return { error: /human|robot|verify|press & hold|captcha/i.test(text()) ? "needs_human" : "page_changed" };
  const cache = () => apollo.cache.extract();

  if (op === "order_list") {
    const links = await until(() => {
      const l = [...document.querySelectorAll('a[href^="/store/orders/"]')];
      return l.length ? l : null;
    });
    if (!links) return { error: /log ?in|sign ?in/i.test(text()) ? "signed_out" : "page_changed" };
    const seen = new Set();
    const orders = [];
    for (const a of links) {
      const id = a.getAttribute("href").split("/").pop().split("?")[0];
      if (seen.has(id)) continue;
      seen.add(id);
      let card = a;
      for (let i = 0; i < 8 && card.parentElement; i++) {
        card = card.parentElement;
        if (/Items/.test(card.innerText) && /Total/.test(card.innerText)) break;
      }
      const t = card.innerText.replace(/\s+/g, " ");
      const n = t.match(/Items (\d+)/);
      // The store's name follows the card, next to "Add all items to cart".
      const around = (card.parentElement || card).innerText.replace(/\s+/g, " ");
      // "Wegmans +8": a big order shows how many more product pictures there are.
      const store = ((around.match(/View order detail (.+?)(?: Add all items| Rate order| Report a problem|$)/) || [])[1] || "").replace(/ \+\d+$/, "");
      orders.push({ id, store, delivered: /\bDelivered\b/.test(t), items: n ? Number(n[1]) : null });
    }
    return { orders };
  }

  if (op === "order") {
    const od = await until(() => {
      const c = cache();
      const k = Object.keys(c).find((k) => k.startsWith("OrderManagerOrderDelivery"));
      let found = null;
      (function find(o) {
        if (found || !o || typeof o !== "object") return;
        if (o.orderDelivery && o.orderDelivery.orderItems) return void (found = o.orderDelivery);
        Object.values(o).forEach(find);
      })(k && c[k]);
      return found;
    });
    if (!od) return { error: "page_changed" };
    const where = od.deliveryAddress && od.deliveryAddress.viewSection;
    return {
      order: {
        id: location.pathname.split("/").pop(), // the order history's id, not legacyOrderId
        retailer: od.retailer && od.retailer.slug,
        address: where && where.lineOneString,
        delivered_at: od.deliveredAt,
        state: od.workflowState,
        // `item` is what was placed; `currentItem` is what came (a substitute when replaced).
        lines: Object.values(od.orderItems).map((i) => ({
          status: i.status,
          quantity: i.selectedQuantityValue,
          quantity_type: i.selectedQuantityType,
          product_id: i.item && i.item.basketProduct && i.item.basketProduct.item && i.item.basketProduct.item.productId,
          product_name: i.item && i.item.name,
        })),
      },
    };
  }

  if (op === "search") {
    const links = await until(() => {
      const l = [...document.querySelectorAll('a[href*="/products/"]')].filter((a) => a.offsetParent);
      return l.length ? l : null;
    });
    if (!links) return { results: [] };
    const names = {};
    (function walk(o, d) {
      if (!o || typeof o !== "object" || d > 14) return;
      if (typeof o.id === "string" && /^items_\d+-\d+$/.test(o.id) && o.name) names[o.id.split("-")[1]] = o.name;
      Object.values(o).forEach((x) => walk(x, d + 1));
    })(cache(), 0);
    const seen = new Set();
    const results = [];
    for (const a of links) {
      const id = (a.getAttribute("href").match(/products\/(\d+)/) || [])[1];
      if (!id || seen.has(id)) continue;
      seen.add(id);
      // "Buy it again": the household has bought it before, so it's the better guess.
      results.push({ id, name: names[id] || null, bought: /Buy it again/.test(a.innerText) });
      if (results.length === 5) break;
    }
    return { results };
  }

  if (op === "cart") {
    // Product page: "Add to cart" puts in one, then the "N in cart" menu sets the exact count.
    // Setting a count, not adding to it, makes a second run give the same Cart.
    if (arg.address && !text().includes(arg.address)) return { error: "wrong_address" };
    const name = ((document.querySelector("h1") || {}).textContent || document.title).trim();
    const combo = () => [...document.querySelectorAll("[role=combobox]")].find((c) => c.offsetParent);
    // "2 in cart", "1 ct in cart", "1 pkg in cart": the unit depends on how the Product is sold.
    const inCart = () => {
      const m = combo() && combo().textContent.trim().match(/^(\d+)(?: [a-z]+)? in cart$/i);
      return m ? Number(m[1]) : 0;
    };
    const addButton = () => [...document.querySelectorAll("button")].find((b) => b.offsetParent && b.textContent.trim() === "Add to cart");
    if (!(await until(() => combo() || addButton()))) return { error: "unavailable", name };
    if (!inCart()) {
      const b = addButton();
      if (!b) return { error: "unavailable", name };
      b.click();
      if (!(await until(inCart, 8000))) return { error: "not_added", name };
    }
    if (inCart() !== arg.quantity) {
      if (arg.quantity > 9) return { error: "more_than_nine", name, quantity: inCart() };
      combo().click();
      const option = await until(
        // "6", "6 ct", "6 pkgs"
        () => [...document.querySelectorAll("[role=option]")].find((o) => o.offsetParent && new RegExp(`^${arg.quantity}( |$)`).test(o.textContent.trim())),
        3000,
      );
      if (!option) return { error: "page_changed", name };
      option.click();
      if (!(await until(() => inCart() === arg.quantity, 8000))) return { error: "not_added", name, quantity: inCart() };
    }
    return { name, quantity: inCart() };
  }

  return { error: "page_changed" };
}

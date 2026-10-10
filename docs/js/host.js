// Static host for the dashboard: the `dash` global the page scripts expect, plus the
// "Sources" popover. Loads datasets.json and its 12 files, runs the page's calcs once their
// inputs arrive, and redraws on data, resize and back/forward navigation between tabs.
(() => {
  const state = {}; // id -> {status, data}
  const calcs = {}; // id -> {inputs, fn, title, description}
  const listeners = [];
  let manifest = null;
  let settled = false;

  // Series colours, shared with the static figures (src/plots.py) for indices 0-3.
  const colors = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#8b5cf6', '#d1495b', '#0f9fb5', '#7a7a74'];

  const runCalcs = () => {
    for (const [id, c] of Object.entries(calcs)) {
      if (state[id] && state[id].status !== 'loading') continue;
      const ins = c.inputs.map((i) => state[i]);
      if (ins.some((s) => s && ['error', 'missing'].includes(s.status))) state[id] = { status: 'error', data: null };
      else if (ins.every((s) => s && s.status === 'ok')) {
        try {
          state[id] = { status: 'ok', data: c.fn(...ins.map((s) => s.data)) };
        } catch (e) {
          console.error(`calc ${id} failed`, e);
          state[id] = { status: 'error', data: null };
        }
      }
    }
  };

  let queued = false;
  const notify = () => {
    if (queued) return;
    queued = true;
    setTimeout(() => {
      queued = false;
      runCalcs();
      listeners.forEach((fn) => fn());
      if (settled) keepTop();
    }, 0);
  };

  const dash = {
    colors,
    data(id) {
      return state[id] || { status: settled ? 'missing' : 'loading', data: null };
    },
    calc(id, spec) {
      calcs[id] = spec;
    },
    onData(fn) {
      listeners.push(fn);
      fn();
    },
    setLink(name) {
      if (location.hash.slice(1) !== name) history.pushState(null, '', '#' + name);
    },
  };
  window.dash = dash;

  const load = async () => {
    try {
      const r = await fetch('datasets.json');
      if (!r.ok) throw new Error(r.status);
      manifest = await r.json();
    } catch (e) {
      console.error('datasets.json failed to load', e);
      manifest = {};
      settled = true;
      notify();
      return;
    }
    await Promise.all(
      Object.entries(manifest).map(async ([id, m]) => {
        state[id] = { status: 'loading', data: null };
        try {
          const r = await fetch(m.file);
          if (!r.ok) throw new Error(r.status);
          const rows = await r.json();
          state[id] = { status: 'ok', data: rows };
          m.rows = rows.length;
        } catch (e) {
          console.error(`${id} failed to load`, e);
          state[id] = { status: 'error', data: null };
        }
        notify();
      })
    );
    settled = true;
    notify();
  };

  // Charts size from clientWidth, so redraw when the width changes.
  let lastW = window.innerWidth, timer;
  window.addEventListener('resize', () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      if (window.innerWidth === lastW) return;
      lastW = window.innerWidth;
      close(false);
      listeners.forEach((fn) => fn());
    }, 150);
  });

  // A tab deep link (#causal) is also its section's id, so the browser scrolls past the header to
  // it, and again as charts lay out. Keep the header in view until the reader scrolls.
  const deepLinked = !!document.querySelector(`.bc-page#${CSS.escape(location.hash.slice(1) || '-')}`);
  let readerScrolled = false;
  ['wheel', 'touchmove', 'keydown', 'pointerdown'].forEach((t) =>
    window.addEventListener(t, () => (readerScrolled = true), { once: true, passive: true })
  );
  const keepTop = () => {
    if (deepLinked && !readerScrolled) window.scrollTo(0, 0);
  };
  window.addEventListener('load', () => setTimeout(keepTop, 0));

  // Back/forward between tabs.
  window.addEventListener('popstate', () => {
    const id = location.hash.slice(1) || 'verdict';
    const tab = document.querySelector(`.bc-tab[data-page="${CSS.escape(id)}"]`);
    if (tab && tab.getAttribute('aria-selected') !== 'true') tab.click();
  });

  // ------------------------------------------------------------------ Sources popover
  // Marked values open it on click; charts and tables get a "Source" line beneath them.
  const VALUE = '[data-source][data-field]:not(th)';
  const valueAt = (t) => (t && t.closest ? t.closest(VALUE) : null);
  const markValues = () => {
    document.querySelectorAll(VALUE).forEach((v) => {
      if (v.hasAttribute('tabindex')) return;
      v.tabIndex = 0;
      v.setAttribute('role', 'button');
      v.setAttribute('aria-haspopup', 'dialog');
    });
  };

  const describe = (id) => {
    if (calcs[id]) {
      const c = calcs[id];
      return { title: c.title, description: c.description, inputs: c.inputs, calc: true };
    }
    const m = manifest && manifest[id];
    return m ? { title: m.title, description: m.description, file: m.file, rows: m.rows } : { title: id, description: '' };
  };

  const pop = document.createElement('div');
  pop.className = 'src-pop';
  pop.setAttribute('role', 'dialog');
  pop.setAttribute('aria-label', 'Source');
  pop.hidden = true;
  let anchor = null;

  const close = (refocus) => {
    if (pop.hidden) return;
    pop.hidden = true;
    if (refocus && anchor) anchor.focus();
    anchor = null;
  };

  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  };

  const open = (target, ids, fromKey) => {
    pop.replaceChildren();
    const head = el('div', 'src-pop-head');
    head.append(el('span', 'src-pop-eyebrow', ids.length > 1 ? 'Sources' : 'Source'));
    const x = el('button', 'src-pop-x', '×');
    x.type = 'button';
    x.setAttribute('aria-label', 'Close');
    x.addEventListener('click', () => close(true));
    head.append(x);
    pop.append(head);
    ids.forEach((id) => {
      const d = describe(id);
      const sec = el('div', 'src-pop-sec');
      sec.append(el('div', 'src-pop-title', d.title));
      if (d.description) sec.append(el('p', 'src-pop-desc', d.description));
      const meta = el('div', 'src-pop-meta');
      if (d.calc) {
        meta.append('Calculated in the page from ');
        d.inputs.forEach((i, k) => {
          if (k) meta.append(', ');
          meta.append(el('b', null, describe(i).title));
        });
      } else if (d.file) {
        const a = el('a', null, d.file);
        a.href = d.file;
        a.target = '_blank';
        a.rel = 'noopener';
        meta.append(a);
        if (d.rows != null) meta.append(` · ${d.rows.toLocaleString('en')} rows`);
      }
      sec.append(meta);
      pop.append(sec);
    });
    if (target.dataset.field) {
      const f = el('div', 'src-pop-field');
      f.append('Field ', el('code', null, target.dataset.field));
      if (target.dataset.where) f.append(' where ', el('code', null, target.dataset.where.replace(/&/g, ' and ')));
      else if (target.dataset.row != null) f.append(', row ', el('code', null, target.dataset.row));
      pop.append(f);
    }
    pop.hidden = false;
    anchor = target;
    const r = target.getBoundingClientRect();
    const pw = pop.offsetWidth, ph = pop.offsetHeight;
    const vw = document.documentElement.clientWidth, vh = window.innerHeight;
    let left = Math.min(Math.max(8, r.left), vw - pw - 8);
    let top = r.bottom + 6;
    if (top + ph > vh - 8 && r.top - ph - 6 > 8) top = r.top - ph - 6;
    pop.style.left = left + window.scrollX + 'px';
    pop.style.top = top + window.scrollY + 'px';
    if (fromKey) x.focus({ preventScroll: true });
  };

  const sourcesOf = (e) => e.dataset.source.split(/\s+/).filter(Boolean);

  document.addEventListener('click', (e) => {
    if (pop.contains(e.target)) return;
    const v = valueAt(e.target) || e.target.closest('.src-line');
    if (!v || v === anchor) return close(false);
    e.preventDefault();
    open(v, sourcesOf(v._for || v));
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') return close(true);
    const v = valueAt(e.target);
    if (v && (e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault();
      open(v, sourcesOf(v), true);
    }
  });

  // A "Source: …" button closing each card that holds a chart or data table (and the chart grid).
  const addSourceLines = () => {
    document.querySelectorAll('.bc-chart[data-source], #supply-grid[data-source], table[data-source]').forEach((t) => {
      const b = el('button', 'src-line');
      b.type = 'button';
      b._for = t;
      b.setAttribute('aria-haspopup', 'dialog');
      const card = t.closest('.bc-card');
      if (card) card.append(b);
      else t.after(b);
    });
  };
  const labelSourceLines = () => {
    document.querySelectorAll('.src-line').forEach((b) => {
      b.textContent = 'Source: ' + sourcesOf(b._for).map((id) => describe(id).title).join(' · ');
    });
  };

  document.addEventListener('DOMContentLoaded', () => {
    document.body.append(pop);
    addSourceLines();
    labelSourceLines();
    markValues();
    // The page rebuilds some marked values on every draw; keep them keyboard-reachable.
    let pending = false;
    new MutationObserver(() => {
      if (pending) return;
      pending = true;
      setTimeout(() => {
        pending = false;
        markValues();
      }, 0);
    }).observe(document.querySelector('.bc'), { childList: true, subtree: true });
    load().then(labelSourceLines);
  });
})();

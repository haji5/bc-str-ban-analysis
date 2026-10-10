// Shared helpers: parsing, formatting, data access, marks, tooltips, states.
(() => {
  const BC = (window.BC = window.BC || {});
  const MINUS = '−';
  const P = (s) => new Date(String(s).slice(0, 10) + 'T00:00:00Z');
  BC.P = P;
  BC.POLICY = [
    { d: P('2023-10-01'), long: 'Announced', short: 'Ann.' },
    { d: P('2024-05-01'), long: 'Phase 1', short: 'P1' },
    { d: P('2025-05-01'), long: 'Registry', short: 'P2' },
  ];
  BC.CITY = { vancouver: 'Vancouver', victoria: 'Victoria CRD', ottawa: 'Ottawa', seattle: 'Seattle' };
  BC.cityColor = (c) => dash.colors[{ vancouver: 0, victoria: 1, ottawa: 2, seattle: 3 }[c] ?? 4];

  const ok = (v) => v !== null && v !== undefined && v !== '' && !Number.isNaN(+v);
  BC.sgn = (v, dp = 1, unit = '%') => (!ok(v) ? '—' : (+v > 0 ? '+' : +v < 0 ? MINUS : '') + Math.abs(+v).toFixed(dp) + unit);
  BC.int = (v) => (!ok(v) ? '—' : d3.format(',')(Math.round(+v)));
  BC.num = (v, dp = 2) => (!ok(v) ? '—' : (+v < 0 ? MINUS : '') + Math.abs(+v).toFixed(dp));
  BC.pv = (p) => (!ok(p) ? '—' : +p < 0.001 ? '<0.001' : (+p).toFixed(3));
  BC.share = (v, dp = 0) => (!ok(v) ? '—' : (100 * v).toFixed(dp) + '%');
  BC.compact = (v) => (!ok(v) ? '—' : new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(+v));
  BC.mon = d3.utcFormat('%b %Y');
  BC.day = d3.utcFormat('%b %-d, %Y');
  BC.pctEff = (b) => 100 * (Math.exp(+b) - 1);

  BC.rows = (id) => {
    const d = dash.data(id);
    return d.status === 'ok' && Array.isArray(d.data) ? d.data : [];
  };
  BC.ready = (...ids) => ids.every((id) => dash.data(id).status === 'ok');
  BC.failed = (...ids) => ids.some((id) => ['error', 'connect', 'declined', 'missing'].includes(dash.data(id).status));

  // A chart box: skeleton while loading, one quiet line on failure, true when drawable.
  BC.box = (el, ids) => {
    if (BC.ready(...ids)) {
      el.classList.remove('dash-skeleton');
      return true;
    }
    el.replaceChildren();
    if (BC.failed(...ids)) {
      el.classList.remove('dash-skeleton');
      const f = document.createElement('div');
      f.className = 'bc-fail';
      const dot = document.createElement('span');
      dot.className = 'bc-fail-dot';
      f.append(dot, document.createTextNode('Failed to load'));
      el.append(f);
    } else el.classList.add('dash-skeleton');
    return false;
  };

  // Marked single values: data-source + data-field + data-where/data-row, formatted by data-fmt.
  const FMT = {
    int: BC.int,
    pct: (v) => BC.sgn(v, 1),
    pct0: (v) => BC.sgn(v, 0),
    pp: (v) => BC.sgn(v, 1, ' pp'),
    share: (v) => (+v).toFixed(0) + '%',
    num: (v) => BC.num(v, 2),
    p: BC.pv,
    compact: BC.compact,
  };
  BC.lookup = (el) => {
    const rows = BC.rows(el.dataset.source);
    let r;
    if (el.dataset.row != null) r = rows[+el.dataset.row];
    else if (el.dataset.where) {
      const conds = el.dataset.where.split('&').map((kv) => kv.split('=').map(decodeURIComponent));
      r = rows.find((x) => conds.every(([k, v]) => String(x[k]) === v));
    }
    return r ? r[el.dataset.field] : undefined;
  };
  BC.fill = (root) => {
    root.querySelectorAll('[data-fmt][data-source][data-field]').forEach((el) => {
      const st = dash.data(el.dataset.source).status;
      if (st !== 'ok') {
        if (st === 'loading') el.classList.add('dash-skeleton');
        else {
          el.classList.remove('dash-skeleton');
          el.textContent = '—';
        }
        return;
      }
      el.classList.remove('dash-skeleton');
      const v = BC.lookup(el);
      el.textContent = v == null ? '—' : (FMT[el.dataset.fmt] || String)(v);
      const good = el.dataset.good;
      if (good && v != null) {
        const n = +v;
        el.classList.toggle('bc-good', (good === 'down' && n < 0) || (good === 'up' && n > 0));
        el.classList.toggle('bc-bad', (good === 'down' && n > 0) || (good === 'up' && n < 0));
      }
    });
  };

  // Width of strings as drawn in an svg with a class (for margins and labels).
  BC.measure = (svg, strs, cls) => {
    const g = svg.append('g').attr('class', cls);
    let m = 0;
    for (const s of strs) {
      const t = g.append('text').attr('class', cls).text(s);
      m = Math.max(m, t.node().getComputedTextLength());
    }
    g.remove();
    return m;
  };

  BC.svg = (el, H, label) => {
    el.replaceChildren();
    const W = Math.max(260, el.clientWidth || 600);
    const svg = d3
      .select(el)
      .append('svg')
      .attr('width', '100%')
      .attr('height', H)
      .attr('viewBox', `0 0 ${W} ${H}`)
      .attr('role', 'img')
      .attr('aria-label', label || '');
    return { svg, W, H };
  };

  // Popover tooltip inside a position:relative chart box.
  BC.tip = (el) => {
    let t = el.querySelector(':scope > .bc-tip');
    if (!t) {
      t = document.createElement('div');
      t.className = 'bc-tip';
      t.hidden = true;
      el.append(t);
    }
    return t;
  };
  BC.showTip = (el, t, x, y, title, lines) => {
    t.replaceChildren();
    const h = document.createElement('div');
    h.className = 'bc-tip-h';
    h.textContent = title;
    t.append(h);
    lines.forEach((l) => {
      const r = document.createElement('div');
      r.className = 'bc-tip-r';
      if (l.color) {
        const s = document.createElement('span');
        s.className = 'bc-sw';
        s.style.background = l.color;
        r.append(s);
      }
      const n = document.createElement('span');
      n.className = 'bc-tip-n';
      n.textContent = l.name;
      const v = document.createElement('span');
      v.className = 'bc-tip-v';
      v.textContent = l.value;
      r.append(n, v);
      t.append(r);
    });
    t.hidden = false;
    const W = el.clientWidth, H = el.clientHeight;
    const tw = t.offsetWidth, th = t.offsetHeight;
    let left = x + 14;
    if (left + tw > W) left = x - tw - 14;
    left = Math.max(0, left);
    const top = Math.max(0, Math.min(y - th / 2, H - th));
    t.style.left = left + 'px';
    t.style.top = top + 'px';
  };
  BC.hideTip = (el) => {
    const t = el.querySelector(':scope > .bc-tip');
    if (t) t.hidden = true;
  };

  // Segmented controls holding page-local state.
  BC.state = {};
  BC.seg = (id, key, def, onChange) => {
    const g = document.getElementById(id);
    BC.state[key] = def;
    const sync = () => g.querySelectorAll('button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.v === BC.state[key])));
    g.addEventListener('click', (e) => {
      const b = e.target.closest('button[data-v]');
      if (!b || b.dataset.v === BC.state[key]) return;
      BC.state[key] = b.dataset.v;
      sync();
      onChange();
    });
    sync();
  };

  // Animate a box's marks only on its first draw with data.
  BC.firstDraw = (el) => {
    const first = !el.dataset.bcDrawn;
    el.dataset.bcDrawn = '1';
    return first;
  };
})();

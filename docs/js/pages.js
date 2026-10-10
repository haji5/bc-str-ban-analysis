// Calculations, page drawers and wiring.
dash.calc('cum_effect', {
  inputs: ['estimates'],
  title: 'Total effect, covered vs exempt',
  description: 'Phase 1 and Phase 2 log-point effects from the Victoria covered-vs-exempt design (real data), as % change: 100 × (e^β − 1), rounded, with their randomization-inference p-values.',
  fn: (estimates) => {
    const g = (phase) => estimates.find((r) => r.data_source === 'live' && r.spec === 'S2a' && r.phase === phase);
    const b1 = Number(g('phase1').estimate), b2 = Number(g('phase2').estimate);
    const pct = (b) => Math.round(100 * (Math.exp(b) - 1));
    return [{ total_pct: pct(b1 + b2), phase1_pct: pct(b1), phase2_pct: pct(b2),
      phase1_ri_p: Number(g('phase1').ri_p), phase2_ri_p: Number(g('phase2').ri_p) }];
  },
});

dash.calc('supply_change', {
  inputs: ['supply'],
  title: 'Listings change since announcement',
  description: 'Per market and room type: active listings at the latest complete snapshot vs the last complete snapshot before Oct 2023.',
  fn: (supply) => {
    const out = [];
    const keys = [...new Set(supply.map((r) => r.city + '|' + r.room_type))];
    for (const k of keys) {
      const [city, room_type] = k.split('|');
      const rs = supply.filter((r) => r.city === city && r.room_type === room_type && !r.incomplete).sort((a, b) => (a.month < b.month ? -1 : 1));
      const pre = rs.filter((r) => r.month < '2023-10-01').at(-1);
      const last = rs.at(-1);
      out.push({
        city, room_type,
        base_month: pre ? pre.month : null,
        base_n: pre ? pre.n_active : null,
        latest_month: last.month,
        latest_n: last.n_active,
        change_pct: pre ? Math.round(1000 * (last.n_active / pre.n_active - 1)) / 10 : null,
      });
    }
    return out;
  },
});

dash.calc('cpi_noise', {
  inputs: ['macro'],
  title: 'CPI rent noise, Victoria',
  description: 'Standard deviation of 3-month % changes in Victoria CPI rented accommodation, Jan 2022 – Jun 2026.',
  fn: (macro) => {
    const v = macro.filter((r) => r.city === 'victoria').sort((a, b) => (a.month < b.month ? -1 : 1)).map((r) => Number(r.cpi_rent));
    const ch = v.slice(3).map((x, i) => 100 * (x / v[i] - 1));
    const m = ch.reduce((s, x) => s + x, 0) / ch.length;
    const sd = Math.sqrt(ch.reduce((s, x) => s + (x - m) ** 2, 0) / (ch.length - 1));
    return [{ sd_3m_pct: Math.round(sd * 100) / 100 }];
  },
});

dash.calc('snap_summary', {
  inputs: ['snapshots'],
  title: 'Snapshot coverage',
  description: 'Count of listing snapshots, truncated scrapes excluded, and listing records across all snapshots.',
  fn: (snapshots) => [{
    snapshots: snapshots.length,
    excluded: snapshots.filter((s) => s.incomplete).length,
    records: snapshots.reduce((s, r) => s + Number(r.n_total), 0),
  }],
});

(() => {
  const BC = window.BC;
  const P = BC.P;
  const root = document.querySelector('.bc');
  const $ = (id) => document.getElementById(id);
  const MUTED = 'var(--cds-chart-muted)';
  const PHASE = {
    anticipation: { name: 'Anticipation', color: () => MUTED },
    phase1: { name: 'Phase 1', color: () => dash.colors[0] },
    phase2: { name: 'Phase 2', color: () => dash.colors[4] },
  };

  // ---------------------------------------------------------------- shared table
  BC.table = (table, rows, cols, keyFn) => {
    const ths = [...table.querySelectorAll('thead th')];
    table._bc = { rows, cols, keyFn };
    if (!table._bcInit) {
      table._bcInit = true;
      ths.forEach((th, i) => {
        const b = th.querySelector('button');
        if (b) b.addEventListener('click', () => {
          const c = table._bc.cols[i];
          if (!c.sort) return;
          const s = table._sort;
          table._sort = { i, dir: s && s.i === i && s.dir === 'descending' ? 'ascending' : 'descending' };
          draw();
        });
      });
    }
    const draw = () => {
      const { rows: rs0, cols: cs, keyFn: kf } = table._bc;
      const s = table._sort;
      ths.forEach((th, i) => th.setAttribute('aria-sort', s && s.i === i ? s.dir : 'none'));
      const rs = rs0.slice();
      if (s) {
        const f = cs[s.i].sort;
        rs.sort((a, b) => {
          const A = f(a), B = f(b);
          if (A == null) return 1;
          if (B == null) return -1;
          const d = typeof A === 'string' ? A.localeCompare(B) : A - B;
          return s.dir === 'ascending' ? d : -d;
        });
      }
      const tb = table.tBodies[0];
      tb.replaceChildren();
      rs.forEach((r) => {
        const tr = document.createElement('tr');
        tr.dataset.key = kf(r);
        cs.forEach((c) => {
          const td = document.createElement('td');
          if (c.cls) td.className = c.cls;
          if (c.render) c.render(td, r);
          else {
            const v = r[c.field];
            td.textContent = v == null ? '—' : c.fmt ? c.fmt(v) : String(v);
          }
          tr.append(td);
        });
        tb.append(tr);
      });
    };
    draw();
  };
  const num = (v) => (v == null ? null : Number(v));

  // ---------------------------------------------------------------- 01 verdict
  const drawHero = () => {
    const el = $('hero-chart');
    if (!BC.box(el, ['victoria_split'])) return;
    const room = BC.state.heroRoom;
    const rs = BC.rows('victoria_split').filter((r) => r.room_type === room);
    const GEO = {
      covered: { name: 'Covered areas', short: 'Covered', color: dash.colors[0], width: 2.5 },
      exempt: { name: 'Never-covered areas', short: 'Never covered', color: MUTED, width: 2 },
      salt_spring: { name: 'Salt Spring Island (opted in Nov 2025)', short: 'Salt Spring', color: dash.colors[2], width: 1.5 },
    };
    const series = Object.keys(GEO).map((cov) => {
      const s = rs.filter((r) => r.coverage === cov).sort((a, b) => (a.month < b.month ? -1 : 1));
      const base = s.find((r) => r.month === '2023-08-01');
      return {
        name: GEO[cov].name,
        short: GEO[cov].short,
        color: GEO[cov].color,
        width: GEO[cov].width,
        points: base ? s.map((r) => ({ x: P(r.month), y: (100 * r.n_active) / base.n_active, n: r.n_active, hollow: r.incomplete })) : [],
      };
    });
    BC.lineChart(el, {
      series, height: 340, dots: true, refY: 100, aria: 'Victoria CRD listings, covered vs exempt areas',
      yFmt: (d) => d.toFixed(0), vFmt: (v) => v.toFixed(0),
      tipFmt: (p) => `${p.y.toFixed(0)} · ${BC.int(p.n)} listings`,
    });
  };

  const forestRows = (src, specs) => {
    const est = BC.rows('estimates').filter((r) => r.data_source === src);
    const groups = d3.groups(est, (r) => r.spec + '|' + r.label);
    const order = specs ? specs.map((s) => s[0]) : ['S2a', 'S2a-never', 'S2a-reviewed', 'S2a-ppml', 'S2b', 'S1', 'S1-ppml', 'S1-reviewed', 'S1-season', 'S1-victoria', 'S1-vancouver', 'S4b'];
    const meta = Object.fromEntries((specs || []).map((s) => [s[0], s]));
    const design = (spec) => (spec.startsWith('S2') ? 'B' : spec.startsWith('S1') ? 'A' : 'C');
    return groups
      .filter(([k]) => order.includes(k.split('|')[0]))
      .sort((a, b) => order.indexOf(a[0].split('|')[0]) - order.indexOf(b[0].split('|')[0]))
      .map(([k, rs]) => {
        const spec = k.split('|')[0];
        const m = meta[spec];
        const phases = specs ? ['phase1', 'phase2'] : ['anticipation', 'phase1', 'phase2'];
        return {
          label: m ? m[1] : `${design(spec)} · ${rs[0].label}`,
          tag: m ? m[2] : spec === 'S2a' ? 'preferred' : spec === 'S4b' && src === 'live' ? 'fails pre-trend' : '',
          muted: spec === 'S4b' && src === 'live',
          items: phases.map((ph) => {
            const r = rs.find((x) => x.phase === ph);
            if (!r) return { name: PHASE[ph].name, est: null };
            const tip = [
              { name: 'β (log points)', value: BC.num(r.estimate, 3) },
              { name: '% effect', value: BC.sgn(BC.pctEff(r.estimate), 1) },
              { name: '95% CI', value: `${BC.sgn(BC.pctEff(r.ci_low), 0)} to ${BC.sgn(BC.pctEff(r.ci_high), 0)}` },
              { name: 'p (clustered)', value: BC.pv(r.p) },
            ];
            if (r.ri_p != null) tip.push({ name: 'p (randomization)', value: BC.pv(r.ri_p) });
            if (r.wild_p != null) tip.push({ name: 'p (wild bootstrap)', value: BC.pv(r.wild_p) });
            if (r.truth != null) tip.push({ name: 'True effect', value: BC.sgn(BC.pctEff(r.truth), 1) });
            tip.push({ name: 'N · clusters', value: `${BC.int(r.nobs)} · ${r.n_clusters}` });
            return {
              name: PHASE[ph].name, color: PHASE[ph].color(),
              est: BC.pctEff(r.estimate), lo: BC.pctEff(r.ci_low), hi: BC.pctEff(r.ci_high),
              truth: r.truth != null ? BC.pctEff(r.truth) : null, tip,
            };
          }),
        };
      });
  };

  const cpiSeries = (from) => {
    const rs = BC.rows('macro');
    return ['victoria', 'vancouver', 'ottawa'].map((c) => {
      const s = rs.filter((r) => r.city === c && r.cpi_rent != null && r.month >= from).sort((a, b) => (a.month < b.month ? -1 : 1));
      const base = rs.find((r) => r.city === c && r.month === '2023-09-01');
      return {
        name: BC.CITY[c], short: BC.CITY[c].split(' ')[0], color: BC.cityColor(c),
        points: base ? s.map((r) => ({ x: P(r.month), y: (100 * r.cpi_rent) / base.cpi_rent })) : [],
      };
    });
  };

  const verdict = () => {
    drawHero();
    const f = $('mini-forest');
    BC.legend($('mini-forest-legend'), [
      { name: 'Phase 1 (May 2024)', color: PHASE.phase1.color(), kind: 'bc-dotk' },
      { name: 'Phase 2 (May 2025), incremental', color: PHASE.phase2.color(), kind: 'bc-dotk' },
    ]);
    if (BC.box(f, ['estimates'])) {
      BC.forest(f, forestRows('live', [
        ['S2a', 'B · Victoria covered vs exempt areas', 'preferred'],
        ['S1', 'A · Room type, OLS', 'lower bound'],
        ['S1-ppml', 'A · Room type, Poisson', 'lower bound'],
        ['S4b', 'C · BC vs Ottawa', 'fails pre-trend'],
      ]), { aria: 'Effect estimates by design' });
    }
    const c = $('mini-cpi');
    if (BC.box(c, ['macro'])) {
      BC.lineChart(c, { series: cpiSeries('2022-01-01'), height: 240, refY: 100, matchDays: 20, yFmt: (d) => d.toFixed(0), vFmt: (v) => v.toFixed(1), shade: false });
    }
  };

  // ---------------------------------------------------------------- 02 supply
  const supply = () => {
    const room = BC.state.supplyRoom, measure = BC.state.supplyMeasure;
    const ready = BC.ready('supply');
    const rs = BC.rows('supply').filter((r) => r.room_type === room);
    const cities = ['vancouver', 'victoria', 'ottawa', 'seattle'];
    const xDomain = [P('2022-06-01'), P('2026-06-30')];
    const build = (c) => {
      const s = rs.filter((r) => r.city === c).sort((a, b) => (a.month < b.month ? -1 : 1));
      const base = s.filter((r) => r.month < '2023-10-01' && !r.incomplete).at(-1);
      if (measure === 'index' && !base) return [];
      return s.map((r) => ({ x: P(r.month), y: measure === 'index' ? (100 * r.n_active) / base.n_active : r.n_active, n: r.n_active, hollow: r.incomplete }));
    };
    const pts = Object.fromEntries(cities.map((c) => [c, build(c)]));
    const allY = Object.values(pts).flat().map((p) => p.y);
    const dom = allY.length ? [measure === 'index' ? Math.min(...allY, 100) * 0.95 : 0, Math.max(...allY) * 1.04] : [0, 1];
    cities.forEach((c) => {
      const card = $('sm-' + c);
      const el = card.querySelector('.bc-chart');
      const note = card.querySelector('.bc-sm-note');
      note.replaceChildren();
      if (ready) {
        const mk = (field, fmt, txt) => {
          const b = document.createElement('b');
          b.dataset.source = 'supply_change';
          b.dataset.field = field;
          b.dataset.where = `city=${c}&room_type=${room}`;
          b.dataset.fmt = fmt;
          b.textContent = txt;
          return b;
        };
        const ch = BC.rows('supply_change').find((r) => r.city === c && r.room_type === room);
        if (ch) {
          note.append(mk('latest_n', 'int', BC.int(ch.latest_n)), document.createTextNode(` active, ${BC.mon(P(ch.latest_month))}`));
          if (ch.change_pct != null) note.append(document.createTextNode(' · '), mk('change_pct', 'pct', BC.sgn(ch.change_pct, 1)), document.createTextNode(` vs ${BC.mon(P(ch.base_month))}`));
          else note.append(document.createTextNode(' · archive starts 2025, no pre-period'));
        }
      }
      if (!BC.box(el, ['supply'])) return;
      if (!pts[c].length) {
        el.replaceChildren();
        const f = document.createElement('div');
        f.className = 'bc-fail';
        f.textContent = 'No pre-announcement snapshot to index against';
        el.append(f);
        return;
      }
      BC.lineChart(el, {
        series: [{ name: BC.CITY[c], color: BC.cityColor(c), width: 2.25, points: pts[c] }],
        height: 200, dots: true, endLabels: false, xDomain, yDomain: dom, yTicks: 4,
        refY: measure === 'index' ? 100 : null,
        yFmt: measure === 'index' ? (d) => d.toFixed(0) : d3.format('~s'),
        vFmt: measure === 'index' ? (v) => v.toFixed(0) : BC.int,
        tipFmt: (p) => (measure === 'index' ? `${p.y.toFixed(0)} · ${BC.int(p.n)} listings` : `${BC.int(p.n)} listings`),
      });
    });

    const shareChart = (id, cities2, field) => {
      const el = $(id);
      if (!BC.box(el, ['supply'])) return;
      const ent = BC.rows('supply').filter((r) => r.room_type === 'entire_home');
      BC.lineChart(el, {
        height: 240, dots: true, yMin: field === 'registration_share' ? 0 : null,
        series: cities2.map((c) => ({
          name: BC.CITY[c], short: BC.CITY[c].split(' ')[0], color: BC.cityColor(c),
          points: ent.filter((r) => r.city === c && r[field] != null).sort((a, b) => (a.month < b.month ? -1 : 1)).map((r) => ({ x: P(r.month), y: 100 * r[field], hollow: r.incomplete })),
        })),
        yFmt: (d) => d.toFixed(0) + '%', vFmt: (v) => v.toFixed(1) + '%',
      });
    };
    shareChart('multihost-chart', ['victoria', 'vancouver', 'ottawa', 'seattle'], 'multi_host_share');
    shareChart('registry-chart', ['victoria', 'vancouver'], 'registration_share');
  };

  // ---------------------------------------------------------------- 03 neighbourhoods
  const neighbourhoods = () => {
    const city = BC.state.nbhdCity;
    $('diverge-title').textContent = `${BC.CITY[city]}: change by neighbourhood`;
    const el = $('diverge-chart');
    const all = BC.rows('nbhd_change').filter((r) => r.city === city);
    if (BC.box(el, ['nbhd_change'])) {
      const rows = all.filter((r) => r.change_pct != null).sort((a, b) => a.change_pct - b.change_pct);
      const rowH = 24;
      const { svg, W, H } = BC.svg(el, rows.length * rowH + 30, 'Change in listings by neighbourhood');
      const ml = Math.min(W * 0.42, BC.measure(svg, rows.map((r) => r.neighbourhood), 'bc-lab') + 14);
      const ext = d3.extent(rows, (r) => r.change_pct);
      const span = Math.max(ext[1], 0) - Math.min(ext[0], 0);
      const x = d3.scaleLinear([Math.min(ext[0], 0) - span * 0.14, Math.max(ext[1], 0) + span * 0.14], [ml, W - 8]);
      const ticks = x.ticks(Math.max(3, Math.floor((W - ml) / 80)));
      svg.append('g').selectAll('line').data(ticks).join('line').attr('class', 'bc-gl').attr('x1', x).attr('x2', x).attr('y1', 0).attr('y2', H - 24);
      svg.append('g').selectAll('text').data(ticks).join('text').attr('class', 'bc-tick').attr('x', x).attr('y', H - 6).attr('text-anchor', 'middle').text((d) => BC.sgn(d, 0));
      const anim = BC.firstDraw(el);
      const tip = BC.tip(el);
      const g = svg.append('g').selectAll('g').data(rows).join('g').attr('transform', (d, i) => `translate(0,${i * rowH})`);
      g.append('text').attr('class', 'bc-lab').attr('x', ml - 10).attr('y', rowH / 2).attr('dy', '0.32em').attr('text-anchor', 'end').text((d) => d.neighbourhood);
      g.append('rect')
        .attr('class', anim ? 'bc-pop' : null)
        .attr('x', (d) => Math.min(x(0), x(d.change_pct))).attr('y', 5).attr('height', rowH - 10)
        .attr('width', (d) => Math.max(1, Math.abs(x(d.change_pct) - x(0)))).attr('rx', 3)
        .style('fill', (d) => (d.coverage === 'covered' ? dash.colors[0] : MUTED))
        .style('opacity', (d) => (d.n_pre < 30 ? 0.4 : 1));
      g.append('text').attr('class', 'bc-lab-m')
        .attr('x', (d) => (d.change_pct < 0 ? x(d.change_pct) - 5 : x(d.change_pct) + 5)).attr('y', rowH / 2).attr('dy', '0.32em')
        .attr('text-anchor', (d) => (d.change_pct < 0 ? 'end' : 'start')).text((d) => BC.sgn(d.change_pct, 0));
      svg.append('line').attr('class', 'bc-axis').attr('x1', x(0)).attr('x2', x(0)).attr('y1', 0).attr('y2', H - 24);
      g.append('rect').attr('x', 0).attr('y', 0).attr('width', W).attr('height', rowH).attr('fill', 'transparent')
        .on('pointermove', (ev, d) => {
          const [, my] = d3.pointer(ev, el);
          BC.showTip(el, tip, x(d.change_pct), my, `${d.neighbourhood} · ${d.coverage}`, [
            { name: `Active, ${BC.mon(P(d.pre_month))}`, value: BC.int(d.n_pre) },
            { name: 'Active, Jun 2026', value: BC.int(d.n_post) },
            { name: 'Change', value: BC.sgn(d.change_pct, 1) },
            { name: 'Multi-listing hosts', value: `${BC.share(d.multi_host_pre)} → ${BC.share(d.multi_host_post)}` },
          ]);
        })
        .on('pointerleave', () => (tip.hidden = true));
    }

    const table = $('nbhd-table');
    if (!BC.ready('nbhd_change', 'nbhd_series')) {
      table.tBodies[0].replaceChildren();
      return;
    }
    const q = $('nbhd-search').value.trim().toLowerCase();
    const series = d3.group(BC.rows('nbhd_series').filter((r) => r.city === city), (r) => r.neighbourhood);
    const xDom = [P('2022-06-01'), P('2026-06-01')];
    const rows = all.filter((r) => !q || r.neighbourhood.toLowerCase().includes(q));
    BC.table(table, rows, [
      { field: 'neighbourhood', sort: (r) => r.neighbourhood },
      { field: 'coverage', cls: 'bc-hide-sm', sort: (r) => r.coverage, render: (td, r) => { const s = document.createElement('span'); s.className = 'bc-tag'; s.textContent = r.coverage; td.append(s); } },
      {
        cls: 'bc-hide-sm',
        render: (td, r) => {
          const pts = (series.get(r.neighbourhood) || []).map((p) => ({ x: P(p.month), n: Number(p.n_active) }));
          if (pts.length < 2) return;
          const w = 96, h = 24;
          const sv = d3.select(td).append('svg').attr('width', w).attr('height', h).attr('viewBox', `0 0 ${w} ${h}`).attr('aria-hidden', 'true');
          const x = d3.scaleUtc(xDom, [2, w - 3]);
          const y = d3.scaleLinear([0, d3.max(pts, (p) => p.n) || 1], [h - 3, 3]);
          sv.append('line').attr('class', 'bc-pol').attr('x1', x(BC.POLICY[1].d)).attr('x2', x(BC.POLICY[1].d)).attr('y1', 0).attr('y2', h);
          const color = r.coverage === 'covered' ? dash.colors[0] : MUTED;
          sv.append('path').attr('class', 'bc-line').attr('d', d3.line().x((p) => x(p.x)).y((p) => y(p.n))(pts)).style('stroke', color).style('stroke-width', 1.5);
          const l = pts.at(-1);
          sv.append('circle').attr('cx', x(l.x)).attr('cy', y(l.n)).attr('r', 2).style('fill', color);
        },
      },
      { field: 'n_pre', cls: 'bc-n', fmt: BC.int, sort: (r) => num(r.n_pre) },
      { field: 'n_post', cls: 'bc-n', fmt: BC.int, sort: (r) => num(r.n_post) },
      { field: 'change_pct', cls: 'bc-n', fmt: (v) => BC.sgn(v, 1), sort: (r) => num(r.change_pct) },
      { field: 'multi_host_post', cls: 'bc-n bc-hide-sm', fmt: (v) => BC.share(v), sort: (r) => num(r.multi_host_post) },
      { field: 'licensed_post', cls: 'bc-n bc-hide-sm', fmt: (v) => BC.share(v), sort: (r) => num(r.licensed_post) },
    ], (r) => encodeURIComponent(r.city) + ',' + encodeURIComponent(r.neighbourhood));
    if (!table._sort) {
      table._sort = { i: 5, dir: 'ascending' };
      BC.table(table, rows, table._bc.cols, table._bc.keyFn);
    }
  };

  // ---------------------------------------------------------------- 04 causal
  const causal = () => {
    const src = BC.state.src, design = BC.state.design;
    $('synth-banner').hidden = src !== 'synthetic';
    const el = $('es-chart');
    const pt = BC.rows('pretrend').find((r) => r.id === `${src}|${design}`);
    ['pt-f', 'pt-p', 'pt-ri'].forEach((id) => ($(id).dataset.where = `id=${src}|${design}`));
    BC.fill($('pt-pill'));
    const pill = $('pt-pill');
    // With three control areas the Wald test over-rejects, so the randomization test decides.
    const ptP = pt ? (pt.ri_p != null ? Number(pt.ri_p) : Number(pt.p)) : null;
    $('pt-ri-wrap').hidden = !pt || pt.ri_p == null;
    pill.classList.toggle('bc-pass', !!pt && ptP >= 0.05);
    pill.classList.toggle('bc-fails', !!pt && ptP < 0.05);
    $('pt-verdict').textContent = pt ? (ptP >= 0.05 ? '· passes' : '· fails') + ` (${pt.df} leads)` : '';
    $('slope-pill').hidden = src !== 'live' || design !== 'S3';
    if (pt) $('es-title').textContent = pt.label.replace('ottawa+seattle', 'Ottawa and Seattle').replace('ottawa', 'Ottawa');
    const bins = pt && pt.freq === 'quarterly' ? 'one bin per snapshot quarter, leads not pooled' : 'monthly bins, endpoints binned';
    $('es-note').textContent = `Effect relative to the last pre-announcement snapshot (Aug-Sep 2023), log points with 95% CI; ${bins}.${src === 'synthetic' ? ' Dotted line: true simulated effect.' : ''}`;
    if (BC.box(el, ['event_study'])) {
      const pts = BC.rows('event_study').filter((r) => r.data_source === src && r.spec === design).map((r) => ({ ...r, event_time: Number(r.event_time) }));
      BC.eventStudy(el, pts, { height: 340 });
    }
    const leg = [
      { name: 'Anticipation (Oct 2023 – Apr 2024)', color: PHASE.anticipation.color(), kind: 'bc-dotk' },
      { name: 'Phase 1', color: PHASE.phase1.color(), kind: 'bc-dotk' },
      { name: 'Phase 2, incremental', color: PHASE.phase2.color(), kind: 'bc-dotk' },
    ];
    if (src === 'synthetic') leg.push({ name: 'True effect', color: 'var(--color-fg)' });
    BC.legend($('forest-legend'), leg);
    const f = $('forest-chart');
    if (BC.box(f, ['estimates'])) BC.forest(f, forestRows(src), { aria: 'All specifications' });

    const table = $('coef-table');
    if (!BC.ready('estimates')) return table.tBodies[0].replaceChildren();
    const ph = { anticipation: 'Anticipation', phase1: 'Phase 1', phase2: 'Phase 2' };
    BC.table(table, BC.rows('estimates').filter((r) => r.data_source === src), [
      { field: 'label', sort: (r) => r.label },
      { field: 'phase', fmt: (v) => ph[v] || v, sort: (r) => r.phase },
      { field: 'estimate', cls: 'bc-n', fmt: (v) => BC.num(v, 3), sort: (r) => num(r.estimate) },
      { field: 'se', cls: 'bc-n bc-hide-sm', fmt: (v) => BC.num(v, 3), sort: (r) => num(r.se) },
      { field: 'p', cls: 'bc-n', fmt: BC.pv, sort: (r) => num(r.p) },
      { field: 'ri_p', cls: 'bc-n bc-hide-sm', fmt: BC.pv, sort: (r) => num(r.ri_p) },
      { field: 'wild_p', cls: 'bc-n bc-hide-sm', fmt: BC.pv, sort: (r) => num(r.wild_p) },
      { field: 'truth', cls: 'bc-n bc-hide-sm', fmt: (v) => BC.num(v, 3), sort: (r) => num(r.truth) },
      { field: 'nobs', cls: 'bc-n bc-hide-sm', fmt: BC.int, sort: (r) => num(r.nobs) },
    ], (r) => r.id);
  };

  // ---------------------------------------------------------------- 05 rents
  const rents = () => {
    const c = $('cpi-chart');
    if (BC.box(c, ['macro'])) BC.lineChart(c, { series: cpiSeries('2022-01-01'), height: 340, refY: 100, matchDays: 20, yFmt: (d) => d.toFixed(0), vFmt: (v) => v.toFixed(1), aria: 'CPI rent index by city' });

    const b = $('bound-chart');
    if (BC.box(b, ['rent_bound', 'headline', 'cpi_noise'])) {
      const rb = BC.rows('rent_bound').find((r) => r.city === 'victoria');
      const actual = BC.rows('headline').find((r) => r.key === 'cpi_victoria');
      const sd = Number(BC.rows('cpi_noise')[0].sd_3m_pct);
      const { svg, W, H } = BC.svg(b, 200, 'Rent effect bound versus observed change');
      const lo = Math.min(rb.rent_effect_high, -sd), hi = Math.max(actual.change, sd);
      const x = d3.scaleLinear([lo - 1.5, hi + 2], [10, W - 60]).nice();
      const ticks = x.ticks(Math.max(3, Math.floor(W / 90)));
      svg.append('g').selectAll('line').data(ticks).join('line').attr('class', 'bc-gl').attr('x1', x).attr('x2', x).attr('y1', 0).attr('y2', H - 24);
      svg.append('g').selectAll('text').data(ticks).join('text').attr('class', 'bc-tick').attr('x', x).attr('y', H - 6).attr('text-anchor', 'middle').text((d) => BC.sgn(d, 0));
      const anim = BC.firstDraw(b);
      const rows = [
        { label: 'Most the lost listings could lower rents', a: rb.rent_effect_high, z: rb.rent_effect_low, color: dash.colors[0], txt: `${BC.sgn(rb.rent_effect_high, 1)} to ${BC.sgn(rb.rent_effect_low, 1)}` },
        { label: 'Typical 3-month swing in CPI rent', a: -sd, z: sd, color: MUTED, txt: `±${sd.toFixed(1)} pts` },
        { label: 'What Victoria rents actually did', a: 0, z: actual.change, color: dash.colors[1], txt: BC.sgn(actual.change, 1) },
      ];
      rows.forEach((r, i) => {
        const y0 = 8 + i * 56;
        svg.append('text').attr('class', 'bc-lab').attr('x', 10).attr('y', y0 + 10).text(r.label);
        svg.append('rect').attr('class', anim ? 'bc-pop' : null).attr('x', x(Math.min(r.a, r.z))).attr('y', y0 + 20).attr('width', Math.max(2, Math.abs(x(r.z) - x(r.a)))).attr('height', 14).attr('rx', 4).style('fill', r.color);
        svg.append('text').attr('class', 'bc-lab-m').attr('x', x(Math.max(r.a, r.z)) + 6).attr('y', y0 + 27).attr('dy', '0.32em').text(r.txt);
      });
      svg.append('line').attr('class', 'bc-axis').attr('x1', x(0)).attr('x2', x(0)).attr('y1', 20).attr('y2', H - 24);
    }

    const r = $('rate-chart');
    if (BC.box(r, ['macro'])) {
      const s = BC.rows('macro').filter((x) => x.city === 'victoria' && x.policy_rate != null).sort((a, b) => (a.month < b.month ? -1 : 1));
      BC.lineChart(r, {
        series: [{ name: 'Policy rate', color: dash.colors[5], points: s.map((x) => ({ x: P(x.month), y: Number(x.policy_rate) })) }],
        height: 200, step: true, yMin: 0, yTicks: 4, matchDays: 20, shade: false,
        yFmt: (d) => d.toFixed(1) + '%', vFmt: (v) => v.toFixed(2) + '%',
      });
    }
    const v = $('vacancy-chart');
    if (BC.box(v, ['macro'])) {
      const rs = BC.rows('macro');
      BC.lineChart(v, {
        height: 200, step: true, yMin: 0, yTicks: 4, matchDays: 20, shade: false,
        series: ['victoria', 'vancouver', 'ottawa'].map((c) => ({
          name: BC.CITY[c], short: BC.CITY[c].split(' ')[0], color: BC.cityColor(c),
          points: rs.filter((x) => x.city === c && x.vacancy_rate != null).sort((a, b) => (a.month < b.month ? -1 : 1)).map((x) => ({ x: P(x.month), y: Number(x.vacancy_rate) })),
        })),
        yFmt: (d) => d.toFixed(1) + '%', vFmt: (x) => x.toFixed(1) + '%',
      });
    }
    const t = $('rent-table');
    if (!BC.ready('rent_models')) return t.tBodies[0].replaceChildren();
    BC.table(t, BC.rows('rent_models'), [
      { field: 'label', sort: (x) => x.label },
      { field: 'term', sort: (x) => x.term },
      { field: 'estimate', cls: 'bc-n', fmt: (x) => BC.num(x, 3), sort: (x) => num(x.estimate) },
      { field: 'se', cls: 'bc-n bc-hide-sm', fmt: (x) => BC.num(x, 3), sort: (x) => num(x.se) },
      { field: 'p', cls: 'bc-n', fmt: BC.pv, sort: (x) => num(x.p) },
      { field: 'nobs', cls: 'bc-n bc-hide-sm', fmt: BC.int, sort: (x) => num(x.nobs) },
      { field: 'r2', cls: 'bc-n bc-hide-sm', fmt: (x) => BC.num(x, 3), sort: (x) => num(x.r2) },
    ], (x) => x.id);
  };

  // ---------------------------------------------------------------- 06 method
  const method = () => {
    const el = $('snap-chart');
    if (!BC.box(el, ['snapshots'])) return;
    const rs = BC.rows('snapshots').map((r) => ({ ...r, d: P(r.snapshot_date) }));
    const cities = ['vancouver', 'victoria', 'ottawa', 'seattle'];
    const { svg, W, H } = BC.svg(el, 240, 'Snapshot coverage by market');
    const ml = BC.measure(svg, cities.map((c) => BC.CITY[c]), 'bc-lab') + 16;
    const mt = 26, mb = 24;
    const x = d3.scaleUtc([P('2022-05-01'), P('2026-08-01')], [ml, W - 14]);
    const y = d3.scalePoint(cities, [mt + 14, H - mb - 14]);
    const r = d3.scaleSqrt([0, d3.max(rs, (d) => Number(d.n_total))], [0, W < 520 ? 8 : 11]);
    BC.policy(svg, x, mt, H - mb, W, false);
    svg.append('g').selectAll('line').data(cities).join('line').attr('class', 'bc-gl').attr('x1', ml).attr('x2', W - 14).attr('y1', y).attr('y2', y);
    svg.append('g').selectAll('text').data(cities).join('text').attr('class', 'bc-lab').attr('x', ml - 12).attr('y', (c) => y(c)).attr('dy', '0.32em').attr('text-anchor', 'end').text((c) => BC.CITY[c]);
    const xt = x.ticks(d3.utcYear.every(1));
    svg.append('g').selectAll('text').data(xt).join('text').attr('class', 'bc-tick').attr('x', x).attr('y', H - 6).attr('text-anchor', 'middle').text(d3.utcFormat('%Y'));
    const anim = BC.firstDraw(el);
    const tip = BC.tip(el);
    svg.append('g').selectAll('circle').data(rs).join('circle')
      .attr('class', anim ? 'bc-pop' : null)
      .attr('cx', (d) => x(d.d)).attr('cy', (d) => y(d.city)).attr('r', (d) => r(Number(d.n_total)))
      .style('fill', (d) => (d.incomplete ? 'none' : BC.cityColor(d.city)))
      .style('fill-opacity', 0.85)
      .style('stroke', (d) => (d.incomplete ? 'var(--cds-chart-status-critical)' : 'var(--color-panel)'))
      .style('stroke-width', (d) => (d.incomplete ? 2 : 1))
      .on('pointermove', (ev, d) => {
        const [, my] = d3.pointer(ev, el);
        BC.showTip(el, tip, x(d.d), my, `${BC.CITY[d.city]} · ${BC.day(d.d)}`, [
          { name: 'Listings', value: BC.int(d.n_total) },
          { name: 'Completeness vs neighbours', value: BC.share(d.completeness) },
          { name: 'Status', value: d.incomplete ? 'Excluded (truncated)' : 'Used' },
        ]);
      })
      .on('pointerleave', () => (tip.hidden = true));
  };

  // ---------------------------------------------------------------- wiring
  const PAGES = { verdict, supply, neighbourhoods, causal, rents, method };
  let active = 'verdict';
  const drawActive = () => {
    try {
      PAGES[active]();
    } catch (e) {
      console.error(e);
      throw e;
    }
  };
  const show = (id, link = true) => {
    if (!PAGES[id]) return;
    active = id;
    document.querySelectorAll('.bc-tab').forEach((t) => t.setAttribute('aria-selected', String(t.dataset.page === id)));
    document.querySelectorAll('.bc-page').forEach((p) => (p.hidden = p.id !== id));
    if (link) dash.setLink(id);
    drawActive();
  };
  document.querySelector('.bc-tabs').addEventListener('click', (e) => {
    const t = e.target.closest('.bc-tab');
    if (t) show(t.dataset.page);
  });

  BC.seg('hero-room', 'heroRoom', 'entire_home', drawHero);
  BC.seg('supply-room', 'supplyRoom', 'entire_home', supply);
  BC.seg('supply-measure', 'supplyMeasure', 'index', supply);
  BC.seg('nbhd-city', 'nbhdCity', 'victoria', neighbourhoods);
  BC.seg('causal-src', 'src', 'live', causal);
  BC.seg('es-design', 'design', 'S2-ES', causal);
  $('nbhd-search').addEventListener('input', neighbourhoods);

  const start = location.hash.slice(1);
  if (PAGES[start]) show(start, false);

  dash.onData(() => {
    root.style.setProperty('--bc-c0', dash.colors[0]);
    BC.fill(root);
    drawActive();
    BC.fill(root);
  });
})();

// Reusable chart drawers: time-series lines, forest plots, event studies.
(() => {
  const BC = window.BC;
  const yearFmt = (d) => (d.getUTCMonth() === 0 ? d3.utcFormat('%Y')(d) : d3.utcFormat('%b')(d));

  BC.policy = (svg, x, top, bottom, W, shade = true) => {
    const [x0, x1] = x.domain();
    const short = W < 640;
    const p1 = BC.POLICY[1].d;
    if (shade && p1 < x1) {
      svg.append('rect').attr('class', 'bc-band').attr('x', x(p1)).attr('y', top).attr('width', Math.max(0, x(x1) - x(p1))).attr('height', bottom - top);
    }
    BC.POLICY.forEach((p) => {
      if (p.d < x0 || p.d > x1) return;
      const px = x(p.d);
      svg.append('line').attr('class', 'bc-pol').attr('x1', px).attr('x2', px).attr('y1', top - 4).attr('y2', bottom);
      svg.append('text').attr('class', 'bc-pol-t').attr('x', px + 3).attr('y', top - 8).text(short ? p.short : p.long);
    });
  };

  // series: [{name, short, color, width, dash, points:[{x: Date, y, hollow}]}]
  BC.lineChart = (el, o) => {
    const { svg, W, H } = BC.svg(el, o.height || 300, o.aria);
    const series = o.series.filter((s) => s.points.length);
    const all = series.flatMap((s) => s.points);
    if (!all.length) return;
    const xDom = o.xDomain || d3.extent(all, (p) => p.x);
    let dom = o.yDomain;
    if (!dom) {
      const vals = all.map((p) => p.y).concat(o.refY != null ? [o.refY] : []);
      const [a, b] = d3.extent(vals);
      const pad = (b - a) * 0.08 || 1;
      dom = [o.yMin != null ? o.yMin : a - pad, b + pad];
    }
    const yS = d3.scaleLinear(dom, [0, 1]).nice(o.yTicks || 5);
    const ticks = yS.ticks(o.yTicks || 5);
    const yF = o.yFmt || d3.format(',');
    const vF = o.vFmt || yF;
    const ml = BC.measure(svg, ticks.map(yF), 'bc-tick') + 10;
    const lastOf = (s) => s.points.filter((p) => !p.hollow).at(-1);
    let mr = 14;
    let names = series.map((s) => s.name);
    if (o.endLabels !== false) {
      const widthFor = (nm) => BC.measure(svg, series.map((s, i) => `${nm[i]}  ${lastOf(s) ? vF(lastOf(s).y) : ''}`), 'bc-endlab') + 18;
      mr = widthFor(names);
      if (mr > W * 0.36) {
        names = series.map((s) => s.short || s.name);
        mr = Math.min(W * 0.36, widthFor(names));
      }
    }
    const mt = o.policy === false ? 10 : 26;
    const mb = 24;
    const x = d3.scaleUtc(xDom, [ml, W - mr]);
    const y = d3.scaleLinear(yS.domain(), [H - mb, mt]);

    svg.append('g').selectAll('line').data(ticks).join('line').attr('class', 'bc-gl').attr('x1', ml).attr('x2', W - mr).attr('y1', y).attr('y2', y);
    svg.append('g').selectAll('text').data(ticks).join('text').attr('class', 'bc-tick').attr('x', ml - 8).attr('y', (d) => y(d)).attr('dy', '0.32em').attr('text-anchor', 'end').text(yF);
    const nX = Math.max(2, Math.floor((W - ml - mr) / 70));
    const xt = x.ticks(nX).filter((d) => d.getUTCMonth() === 0 || x.ticks(nX).length < 4);
    svg.append('g').selectAll('text').data(xt).join('text').attr('class', 'bc-tick').attr('x', x).attr('y', H - 6).attr('text-anchor', 'middle').text(yearFmt);
    svg.append('line').attr('class', 'bc-axis').attr('x1', ml).attr('x2', W - mr).attr('y1', H - mb).attr('y2', H - mb);
    if (o.policy !== false) BC.policy(svg, x, mt, H - mb, W, o.shade !== false);
    if (o.refY != null) svg.append('line').attr('class', 'bc-ref').attr('x1', ml).attr('x2', W - mr).attr('y1', y(o.refY)).attr('y2', y(o.refY));

    const anim = BC.firstDraw(el);
    const line = d3.line().x((p) => x(p.x)).y((p) => y(p.y)).curve(o.step ? d3.curveStepAfter : d3.curveLinear);
    series.forEach((s) => {
      const pts = s.points.filter((p) => !p.hollow);
      svg.append('path')
        .attr('class', 'bc-line' + (anim && !s.dash ? ' bc-draw' : ''))
        .attr('pathLength', 1)
        .attr('d', line(pts))
        .style('stroke', s.color)
        .style('stroke-width', s.width || 2)
        .style('stroke-dasharray', s.dash || null);
      if (o.dots) {
        svg.append('g').selectAll('circle').data(s.points).join('circle')
          .attr('class', anim ? 'bc-pop' : null)
          .attr('cx', (p) => x(p.x)).attr('cy', (p) => y(p.y))
          .attr('r', (p) => (p.hollow ? 3.5 : 2.75))
          .style('fill', (p) => (p.hollow ? 'var(--color-panel)' : s.color))
          .style('stroke', s.color)
          .style('stroke-width', 1.5);
      }
    });

    if (o.endLabels !== false) {
      const items = series
        .map((s, i) => {
          const l = lastOf(s);
          return l && { s, name: names[i], v: vF(l.y), y: y(l.y) };
        })
        .filter(Boolean)
        .sort((a, b) => a.y - b.y);
      for (let i = 1; i < items.length; i++) if (items[i].y - items[i - 1].y < 15) items[i].y = items[i - 1].y + 15;
      const over = items.length ? items.at(-1).y - (H - mb) : 0;
      if (over > 0) items.forEach((it) => (it.y -= over));
      items.forEach((it) => {
        const t = svg.append('text').attr('class', 'bc-endlab').attr('x', W - mr + 8).attr('y', it.y).attr('dy', '0.32em');
        t.append('tspan').style('fill', it.s.color).text(it.name + '  ');
        t.append('tspan').attr('class', 'bc-endlab-v').text(it.v);
      });
    }

    // Hover: nearest date, one line per series.
    const xs = Array.from(new Set(all.map((p) => +p.x))).sort((a, b) => a - b);
    const rule = svg.append('line').attr('class', 'bc-rule').attr('y1', mt).attr('y2', H - mb).style('opacity', 0);
    const hl = svg.append('g').style('pointer-events', 'none');
    const tip = BC.tip(el);
    const win = (o.matchDays || 45) * 864e5;
    svg.append('rect').attr('x', ml).attr('y', mt).attr('width', Math.max(0, W - mr - ml)).attr('height', H - mb - mt).attr('fill', 'transparent')
      .on('pointermove', (ev) => {
        const [mx, my] = d3.pointer(ev);
        const xv = +x.invert(mx);
        const near = xs[d3.minIndex(xs, (d) => Math.abs(d - xv))];
        const px = x(new Date(near));
        rule.attr('x1', px).attr('x2', px).style('opacity', 1);
        hl.selectAll('*').remove();
        const lines = [];
        series.forEach((s) => {
          const p = d3.least(s.points.filter((q) => Math.abs(+q.x - near) <= win), (q) => Math.abs(+q.x - near));
          if (!p) return;
          hl.append('circle').attr('cx', x(p.x)).attr('cy', y(p.y)).attr('r', 4.5).style('fill', s.color).style('stroke', 'var(--color-panel)').style('stroke-width', 2);
          lines.push({ color: series.length > 1 ? s.color : null, name: s.name + (p.hollow ? ' (excluded)' : ''), value: o.tipFmt ? o.tipFmt(p, s) : vF(p.y) });
        });
        BC.showTip(el, tip, px, my, (o.tipDate || BC.mon)(new Date(near)), lines);
      })
      .on('pointerleave', () => {
        rule.style('opacity', 0);
        hl.selectAll('*').remove();
        tip.hidden = true;
      });
  };

  // Forest plot with labels above each row (reads at any width).
  // rows: [{label, tag, muted, items:[{name, est, lo, hi, truth, color, tip:[{name,value}]}]}]
  BC.forest = (el, rows, o = {}) => {
    const lineH = 13;
    const rowH = (r) => 22 + r.items.length * lineH + 8;
    const H = d3.sum(rows, rowH) + 30;
    const { svg, W } = BC.svg(el, H, o.aria);
    const vals = rows.flatMap((r) => r.items.flatMap((i) => [i.lo, i.hi, i.truth].filter((v) => v != null && !Number.isNaN(v)))).concat([0]);
    const x = d3.scaleLinear(d3.extent(vals), [8, W - 14]).nice(6);
    const ticks = x.ticks(Math.max(3, Math.floor(W / 90)));
    const bottom = H - 24;
    svg.append('g').selectAll('line').data(ticks).join('line').attr('class', 'bc-gl').attr('x1', x).attr('x2', x).attr('y1', 0).attr('y2', bottom);
    svg.append('g').selectAll('text').data(ticks).join('text').attr('class', 'bc-tick').attr('x', x).attr('y', H - 6).attr('text-anchor', 'middle').text((d) => BC.sgn(d, 0));
    svg.append('line').attr('class', 'bc-axis').attr('x1', x(0)).attr('x2', x(0)).attr('y1', 0).attr('y2', bottom);
    const anim = BC.firstDraw(el);
    const tip = BC.tip(el);
    let y0 = 0;
    rows.forEach((r) => {
      const g = svg.append('g').attr('transform', `translate(0,${y0})`).style('opacity', r.muted ? 0.55 : 1);
      const t = g.append('text').attr('class', 'bc-lab').attr('x', 8).attr('y', 14);
      t.append('tspan').text(r.label);
      if (r.tag) t.append('tspan').attr('class', 'bc-lab-m').text('  ' + r.tag);
      r.items.forEach((it, i) => {
        const cy = 22 + i * lineH + 4;
        if (it.est == null || Number.isNaN(it.est)) return;
        const lo = Math.max(x.domain()[0], it.lo), hi = Math.min(x.domain()[1], it.hi);
        g.append('line').attr('class', 'bc-line' + (anim ? ' bc-pop' : '')).attr('x1', x(lo)).attr('x2', x(hi)).attr('y1', cy).attr('y2', cy).style('stroke', it.color).style('stroke-width', 2).style('opacity', 0.55);
        if (it.truth != null && !Number.isNaN(it.truth)) {
          g.append('line').attr('x1', x(it.truth)).attr('x2', x(it.truth)).attr('y1', cy - 6).attr('y2', cy + 6).style('stroke', 'var(--color-fg)').style('stroke-width', 2);
        }
        g.append('circle').attr('class', anim ? 'bc-pop' : null).attr('cx', x(it.est)).attr('cy', cy).attr('r', 4.5).style('fill', it.color).style('stroke', 'var(--color-panel)').style('stroke-width', 1.5);
        g.append('rect').attr('x', 0).attr('y', cy - lineH / 2).attr('width', W).attr('height', lineH).attr('fill', 'transparent')
          .on('pointermove', (ev) => {
            const [, my] = d3.pointer(ev, el);
            BC.showTip(el, tip, x(it.est), my, `${r.label} · ${it.name}`, it.tip || []);
          })
          .on('pointerleave', () => (tip.hidden = true));
      });
      y0 += rowH(r);
    });
  };

  BC.legend = (el, items) => {
    el.replaceChildren();
    items.forEach((it) => {
      const s = document.createElement('span');
      const i = document.createElement('i');
      if (it.kind) i.className = it.kind;
      i.style.background = it.color;
      s.append(i, document.createTextNode(it.name));
      el.append(s);
    });
  };

  // Event study: x = months relative to May 2024, CI band, optional truth.
  BC.eventStudy = (el, pts, o = {}) => {
    const { svg, W, H } = BC.svg(el, o.height || 340, 'Event study');
    const est = pts.filter((p) => p.term !== 'reference');
    const ref = pts.find((p) => p.term === 'reference');
    const vals = pts.flatMap((p) => [p.ci_low, p.ci_high, p.truth].filter((v) => v != null)).concat([0]);
    const yS = d3.scaleLinear(d3.extent(vals), [0, 1]).nice(6);
    const ticks = yS.ticks(6);
    const yF = (d) => BC.num(d, 2);
    const ml = BC.measure(svg, ticks.map(yF), 'bc-tick') + 12;
    const mr = 14, mt = 26, mb = 40;
    const xe = d3.extent(pts, (p) => p.event_time);
    const x = d3.scaleLinear([Math.min(xe[0], -9) - 1, xe[1] + 1], [ml, W - mr]);
    const y = d3.scaleLinear(yS.domain(), [H - mb, mt]);
    svg.append('rect').attr('class', 'bc-band').attr('x', x(0)).attr('y', mt).attr('width', x.range()[1] - x(0)).attr('height', H - mb - mt);
    svg.append('g').selectAll('line').data(ticks).join('line').attr('class', 'bc-gl').attr('x1', ml).attr('x2', W - mr).attr('y1', y).attr('y2', y);
    svg.append('g').selectAll('text').data(ticks).join('text').attr('class', 'bc-tick').attr('x', ml - 8).attr('y', (d) => y(d)).attr('dy', '0.32em').attr('text-anchor', 'end').text(yF);
    const xt = d3.range(Math.ceil(x.domain()[0] / 6) * 6, x.domain()[1] + 1, W < 520 ? 12 : 6);
    svg.append('g').selectAll('text').data(xt).join('text').attr('class', 'bc-tick').attr('x', x).attr('y', H - mb + 16).attr('text-anchor', 'middle').text((d) => (d > 0 ? '+' + d : d < 0 ? '−' + -d : '0'));
    svg.append('text').attr('class', 'bc-tick').attr('x', (ml + W - mr) / 2).attr('y', H - 4).attr('text-anchor', 'middle').text('Months relative to Phase 1 (May 2024)');
    svg.append('line').attr('class', 'bc-ref').attr('x1', ml).attr('x2', W - mr).attr('y1', y(0)).attr('y2', y(0));
    const short = W < 640;
    [[-7, 'Announced', 'Ann.'], [0, 'Phase 1', 'P1'], [12, 'Registry', 'P2']].forEach(([t, l, s]) => {
      if (t < x.domain()[0] || t > x.domain()[1]) return;
      svg.append('line').attr('class', 'bc-pol').attr('x1', x(t)).attr('x2', x(t)).attr('y1', mt - 4).attr('y2', H - mb);
      svg.append('text').attr('class', 'bc-pol-t').attr('x', x(t) + 3).attr('y', mt - 8).text(short ? s : l);
    });
    const c = dash.colors[0];
    const all = pts.slice().sort((a, b) => a.event_time - b.event_time);
    const area = d3.area().x((p) => x(p.event_time)).y0((p) => y(p.ci_low)).y1((p) => y(p.ci_high));
    svg.append('path').attr('d', area(all)).style('fill', c).style('opacity', 0.14);
    const anim = BC.firstDraw(el);
    const line = d3.line().x((p) => x(p.event_time)).y((p) => y(p.estimate));
    svg.append('path').attr('class', 'bc-line' + (anim ? ' bc-draw' : '')).attr('pathLength', 1).attr('d', line(all)).style('stroke', c).style('stroke-width', 2);
    const tr = all.filter((p) => p.truth != null);
    if (tr.length) {
      svg.append('path').attr('class', 'bc-line').attr('d', d3.line().x((p) => x(p.event_time)).y((p) => y(p.truth))(tr)).style('stroke', 'var(--color-fg)').style('stroke-width', 1.5).style('stroke-dasharray', '2 4');
    }
    svg.append('g').selectAll('circle').data(est).join('circle').attr('class', anim ? 'bc-pop' : null)
      .attr('cx', (p) => x(p.event_time)).attr('cy', (p) => y(p.estimate)).attr('r', 3.5).style('fill', c).style('stroke', 'var(--color-panel)').style('stroke-width', 1.5);
    if (ref) {
      svg.append('circle').attr('cx', x(ref.event_time)).attr('cy', y(0)).attr('r', 5).style('fill', 'var(--color-panel)').style('stroke', 'var(--color-fg)').style('stroke-width', 1.5);
      svg.append('text').attr('class', 'bc-lab-m').attr('x', x(ref.event_time)).attr('y', y(0) + 18).attr('text-anchor', 'middle').text('Sep 2023 = 0');
    }
    const tip = BC.tip(el);
    const hl = svg.append('g').style('pointer-events', 'none');
    svg.append('rect').attr('x', ml).attr('y', mt).attr('width', W - mr - ml).attr('height', H - mb - mt).attr('fill', 'transparent')
      .on('pointermove', (ev) => {
        const [mx, my] = d3.pointer(ev);
        const p = all[d3.minIndex(all, (q) => Math.abs(x(q.event_time) - mx))];
        hl.selectAll('*').remove();
        hl.append('circle').attr('cx', x(p.event_time)).attr('cy', y(p.estimate)).attr('r', 6).style('fill', 'none').style('stroke', c).style('stroke-width', 2);
        const lines = p.term === 'reference'
          ? [{ name: 'Reference period', value: 'normalised to 0' }]
          : [
              { name: 'Estimate (log pts)', value: BC.num(p.estimate, 3) },
              { name: 'As % change', value: BC.sgn(BC.pctEff(p.estimate), 1) },
              { name: '95% CI', value: `${BC.num(p.ci_low, 2)} to ${BC.num(p.ci_high, 2)}` },
            ];
        if (p.truth != null && p.term !== 'reference') lines.push({ name: 'True effect', value: BC.num(p.truth, 3) });
        const t = p.event_time;
        BC.showTip(el, tip, x(t), my, `Month ${t > 0 ? '+' + t : t < 0 ? '−' + -t : '0'} · ${BC.mon(d3.utcMonth.offset(BC.P('2024-05-01'), t))}`, lines);
      })
      .on('pointerleave', () => {
        hl.selectAll('*').remove();
        tip.hidden = true;
      });
  };
})();

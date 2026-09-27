/*
 * premarket-ai: a small engine for the animated data-flow pages in
 * docs/animation. Each page calls PremarketAnim.run(config) with its nodes,
 * edges and narrated steps; the engine draws the SVG diagram and moves data
 * tokens along the edges, one step at a time.
 *
 * Config:
 *   inc (or kicker + name for a topic page), title, intro, width, height
 *   notes?: {title, items: [[term, text], ...]}  (a list under the diagram)
 *   nodes:  {id, x, y, kind, lines, shape?, w?}  (x, y = centre)
 *           kind: new | old | retired | cloud | actor
 *           shape: rect (default) | db | pill | doc | diamond
 *   groups: {id, label, x, y, w, h}  (top-left corner)
 *   edges:  [from, to, label?, {dashed?, bidir?, via?: [x, y]}?]
 *   steps:  {title, text, clock?, tag?, focus?: [ids] | 'new', flows?: [...]}
 *           tag: a badge in the top-left corner (the increment of a step).
 *           a flow is 'A>B' or 'A>B:token'; an inner array runs in parallel.
 *           'A>B' may also run backwards along an edge drawn B -> A.
 */
(function () {
  'use strict';

  var NS = 'http://www.w3.org/2000/svg';
  var INCS = [
    ['inc-0.html', 'Legacy baseline'],
    ['inc-1.html', 'Web instead of PDF'],
    ['inc-2.html', 'Rule-based checks'],
    ['inc-3.html', 'First AI'],
    ['inc-4.html', 'AI verification'],
    ['inc-5.html', 'Agents and skills'],
    ['inc-6.html', 'Production'],
    ['inc-7.html', 'Enterprise cloud (theory)']
  ];
  // Topic pages that follow one concept across the increments.
  var TOPICS = [
    ['rag.html', 'RAG', 'How RAG works, increments 3 to 6'],
    ['llm.html', 'LLM', 'How the models work inside']
  ];
  var REDUCED = window.matchMedia &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function svg(tag, attrs, parent) {
    var e = document.createElementNS(NS, tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }

  function html(tag, cls, parent, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    if (parent) parent.appendChild(e);
    return e;
  }

  // Rough text width, good enough to size the boxes.
  function textWidth(lines) {
    var w = 0;
    lines.forEach(function (l, i) {
      w = Math.max(w, l.length * (i === 0 ? 8 : 6.6));
    });
    return Math.max(110, Math.round(w + 28));
  }

  function borderPoint(n, tx, ty) {
    var dx = tx - n.x, dy = ty - n.y;
    if (!dx && !dy) return [n.x, n.y];
    var hw = n.w / 2 + 3, hh = n.h / 2 + 3, s;
    if (n.shape === 'diamond') {
      s = 1 / (Math.abs(dx) / hw + Math.abs(dy) / hh);
    } else {
      s = Math.min(hw / Math.abs(dx || 1e-9), hh / Math.abs(dy || 1e-9));
    }
    return [n.x + dx * s, n.y + dy * s];
  }

  function drawShape(n, g) {
    var x0 = n.x - n.w / 2, y0 = n.y - n.h / 2;
    var x1 = n.x + n.w / 2, y1 = n.y + n.h / 2;
    if (n.shape === 'db') {
      var e = 8, rx = n.w / 2;
      svg('path', {class: 'shape', d:
          'M' + x0 + ',' + (y0 + e) + ' A' + rx + ',' + e + ' 0 0 1 ' + x1 +
          ',' + (y0 + e) + ' V' + (y1 - e) + ' A' + rx + ',' + e + ' 0 0 1 ' +
          x0 + ',' + (y1 - e) + ' Z'}, g);
      svg('path', {class: 'shape', fill: 'none', d:
          'M' + x0 + ',' + (y0 + e) + ' A' + rx + ',' + e + ' 0 0 0 ' + x1 +
          ',' + (y0 + e)}, g).style.fill = 'none';
    } else if (n.shape === 'diamond') {
      svg('polygon', {class: 'shape', points: [n.x, y0, x1, n.y, n.x, y1, x0,
          n.y].join(' ')}, g);
    } else if (n.shape === 'doc') {
      svg('polygon', {class: 'shape', points: [x0 + 12, y0, x1, y0, x1 - 12, y1,
          x0, y1].join(' ')}, g);
    } else {
      svg('rect', {class: 'shape', x: x0, y: y0, width: n.w, height: n.h,
          rx: n.shape === 'pill' ? n.h / 2 : 9}, g);
    }
  }

  function drawText(n, g) {
    var shift = n.shape === 'db' ? 4 : 0;
    var t = svg('text', {x: n.x, y: n.y + shift}, g);
    var first = n.y + shift - (n.lines.length - 1) * 8 + 4;
    n.lines.forEach(function (line, i) {
      var s = svg('tspan', {x: n.x, y: first + i * 16}, t);
      if (i === 0) s.setAttribute('class', 't');
      s.textContent = line;
    });
  }

  function run(cfg) {
    window.PremarketAnim.config = cfg;
    var app = document.getElementById('app');
    var page = html('div', 'page', app);

    // Header.
    var top = html('div', 'top', page);
    var head = html('div', '', top);
    var isInc = typeof cfg.inc === 'number';
    html('div', 'kicker', head, isInc ?
        'premarket-ai · delivery increment ' + cfg.inc :
        'premarket-ai · ' + cfg.kicker);
    html('h1', '', head, cfg.title);
    var nav = html('nav', 'incnav', top);
    var home = html('a', '', nav, 'All');
    home.href = 'index.html';
    INCS.forEach(function (inc, i) {
      var a = html('a', i === cfg.inc ? 'here' : '', nav, String(i));
      a.href = inc[0];
      a.title = 'Increment ' + i + ': ' + inc[1];
    });
    TOPICS.forEach(function (t) {
      var a = html('a', location.pathname.endsWith('/' + t[0]) ? 'here' : '',
          nav, t[1]);
      a.href = t[0];
      a.title = t[2];
    });
    html('p', 'intro', page, cfg.intro);

    // Stage.
    var stage = html('div', 'stage', page);
    var clock = html('div', 'clock', stage);
    var tag = html('div', 'clock tag', stage);
    var root = svg('svg', {viewBox: '0 0 ' + cfg.width + ' ' + cfg.height,
        role: 'img', 'aria-label': cfg.title}, stage);
    var defs = svg('defs', {}, root);
    ['arrow', 'arrow-active'].forEach(function (id) {
      var m = svg('marker', {id: id, viewBox: '0 0 10 10', refX: 9, refY: 5,
          markerWidth: 7, markerHeight: 7, orient: 'auto-start-reverse'}, defs);
      svg('path', {d: 'M0,0 L10,5 L0,10 z', class: id}, m);
    });
    var groupLayer = svg('g', {}, root);
    var edgeLayer = svg('g', {}, root);
    var nodeLayer = svg('g', {}, root);
    var tokenLayer = svg('g', {}, root);

    // Groups (also usable as edge endpoints).
    var byId = {};
    (cfg.groups || []).forEach(function (gr) {
      var g = svg('g', {class: 'group'}, groupLayer);
      svg('rect', {x: gr.x, y: gr.y, width: gr.w, height: gr.h, rx: 12}, g);
      svg('text', {x: gr.x + 12, y: gr.y + 20}, g).textContent = gr.label;
      byId[gr.id] = {id: gr.id, x: gr.x + gr.w / 2, y: gr.y + gr.h / 2,
          w: gr.w, h: gr.h, el: g, isGroup: true};
    });

    // Nodes.
    cfg.nodes.forEach(function (n, i) {
      n.shape = n.shape || (n.kind === 'actor' ? 'pill' : 'rect');
      n.w = n.w || textWidth(n.lines);
      n.h = n.h || (n.shape === 'diamond' ? 76 :
          20 + n.lines.length * 16 + (n.shape === 'db' ? 14 : 0));
      var g = svg('g', {class: 'node k-' + n.kind, 'data-id': n.id},
          nodeLayer);
      g.style.animationDelay = (REDUCED ? 0 : i * 60) + 'ms';
      drawShape(n, g);
      drawText(n, g);
      n.el = g;
      byId[n.id] = n;
    });

    // Edges.
    var edges = cfg.edges.map(function (spec) {
      var opt = spec[3] || {};
      var a = byId[spec[0]], b = byId[spec[1]];
      if (!a || !b) throw new Error('unknown edge end: ' + spec.join(' '));
      var via = opt.via;
      var p1 = via ? borderPoint(a, via[0], via[1]) : borderPoint(a, b.x, b.y);
      var p2 = via ? borderPoint(b, via[0], via[1]) : borderPoint(b, a.x, a.y);
      var d = 'M' + p1.join(',') +
          (via ? ' Q' + via.join(',') + ' ' : ' L') + p2.join(',');
      var g = svg('g', {class: 'edge' + (opt.dashed ? ' dashed' : ''),
          'data-from': spec[0], 'data-to': spec[1]}, edgeLayer);
      var path = svg('path', {d: d, 'marker-end': 'url(#arrow)'}, g);
      if (opt.bidir) path.setAttribute('marker-start', 'url(#arrow)');
      var e = {from: spec[0], to: spec[1], el: g, path: path, bidir: opt.bidir};
      if (spec[2]) {
        var len = path.getTotalLength();
        var mid = path.getPointAtLength(len / 2);
        var t = svg('text', {x: mid.x, y: mid.y - 5}, g);
        t.textContent = spec[2];
      }
      return e;
    });

    function setActive(e, on) {
      e.el.classList.toggle('active', on);
      var m = on ? 'url(#arrow-active)' : 'url(#arrow)';
      e.path.setAttribute('marker-end', m);
      if (e.bidir) e.path.setAttribute('marker-start', m);
    }

    function findEdge(a, b) {
      for (var i = 0; i < edges.length; i++) {
        if (edges[i].from === a && edges[i].to === b) {
          return {edge: edges[i], reverse: false};
        }
      }
      for (var j = 0; j < edges.length; j++) {
        if (edges[j].from === b && edges[j].to === a) {
          return {edge: edges[j], reverse: true};
        }
      }
      console.warn('no edge ' + a + ' -> ' + b);
      return null;
    }

    function parseFlow(f) {
      var label = null, k = f.indexOf(':');
      if (k >= 0) { label = f.slice(k + 1); f = f.slice(0, k); }
      var ends = f.split('>');
      var hit = findEdge(ends[0], ends[1]);
      if (!hit) return null;
      hit.label = label;
      hit.target = ends[1];
      return hit;
    }

    // Legend.
    var kinds = {};
    cfg.nodes.forEach(function (n) { kinds[n.kind] = true; });
    var legend = html('div', 'legend', page);
    var names = cfg.legend || {new: 'new in this increment',
        old: 'already there', retired: 'retired', cloud: 'managed cloud service',
        actor: 'people'};
    ['new', 'old', 'retired', 'cloud', 'actor'].forEach(function (k) {
      if (!kinds[k]) return;
      var s = html('span', '', legend);
      html('i', 'k-' + k, s);
      s.appendChild(document.createTextNode(names[k]));
    });
    var fl = html('span', '', legend);
    html('i', 'k-flow', fl);
    fl.appendChild(document.createTextNode('data moving in this step'));

    // Optional notes (a topic page's frameworks, for example).
    function notes() {
      if (!cfg.notes) return;
      var box = html('div', 'panel notes', page);
      html('h2', 'step-title', box, cfg.notes.title);
      var dl = html('dl', '', box);
      cfg.notes.items.forEach(function (item) {
        html('dt', '', dl, item[0]);
        html('dd', '', dl, item[1]);
      });
    }

    // Narration panel and controls.
    var panel = html('div', 'panel', page);
    var sh = html('div', 'step-head', panel);
    var num = html('span', 'step-num', sh);
    var stitle = html('h2', 'step-title', sh);
    var stext = html('p', 'step-text', panel);
    var ctr = html('div', 'controls', panel);
    var bRestart = html('button', '', ctr, '⏮ Restart');
    var bPrev = html('button', '', ctr, '◀ Back');
    var bPlay = html('button', 'primary', ctr, '▶ Play');
    var bNext = html('button', '', ctr, 'Next ▶');
    var bReplay = html('button', '', ctr, '↻ Replay step');
    var speedSel = html('select', '', ctr);
    speedSel.setAttribute('aria-label', 'Speed');
    [['0.5', '0.5×'], ['1', '1×'], ['1.5', '1.5×'], ['2', '2×']].forEach(
        function (o) {
          var op = html('option', '', speedSel, o[1]);
          op.value = o[0];
          if (o[0] === '1') op.selected = true;
        });
    var dots = html('div', 'dots', ctr);
    var dotBtns = cfg.steps.map(function (s, i) {
      var b = html('button', '', dots, String(i + 1));
      b.title = s.title;
      b.addEventListener('click', function () { stop(); go(i); });
      return b;
    });
    html('div', 'hint', panel,
        'Keys: Space play/pause · ← → step · R replay. ' +
        'Nodes and flows follow the Architecture diagram in README.md.');

    var current = 0, playing = false, epoch = 0;
    var speed = 1;

    function wait(ms, my) {
      return new Promise(function (res) {
        setTimeout(function () { res(my === epoch); }, ms);
      });
    }

    function pulse(id) {
      var n = byId[id];
      if (!n || REDUCED) return;
      n.el.classList.remove('hit');
      void n.el.getBoundingClientRect();
      n.el.classList.add('hit');
    }

    function travel(hit, my) {
      return new Promise(function (resolve) {
        var path = hit.edge.path, len = path.getTotalLength();
        setActive(hit.edge, true);
        var g = svg('g', {}, tokenLayer);
        svg('circle', {r: 7, class: 'token-dot'}, g);
        if (hit.label) {
          var bg = svg('rect', {class: 'token-bg', rx: 8, height: 17, y: -27},
              g);
          var t = svg('text', {class: 'token-label', x: 14, y: -14}, g);
          t.textContent = hit.label;
          var w = t.getComputedTextLength();
          bg.setAttribute('x', 8);
          bg.setAttribute('width', w + 12);
        }
        var dur = REDUCED ? 1 : Math.max(650, len / (0.3 * speed));
        var start = null;
        function frame(ts) {
          if (my !== epoch) { g.remove(); resolve(); return; }
          if (start === null) start = ts;
          var t = Math.min(1, (ts - start) / dur);
          var e = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
          var p = path.getPointAtLength((hit.reverse ? 1 - e : e) * len);
          g.setAttribute('transform', 'translate(' + p.x + ',' + p.y + ')');
          if (t < 1) {
            requestAnimationFrame(frame);
          } else {
            pulse(hit.target);
            setTimeout(function () { g.remove(); resolve(); }, 150);
          }
        }
        requestAnimationFrame(frame);
      });
    }

    function show(i) {
      var s = cfg.steps[i];
      edges.forEach(function (e) { setActive(e, false); });
      cfg.nodes.forEach(function (n) { n.el.classList.remove('focus'); });
      (cfg.groups || []).forEach(function (gr) {
        byId[gr.id].el.classList.remove('focus');
      });
      var focus = s.focus === 'new' ?
          cfg.nodes.filter(function (n) { return n.kind === 'new'; })
              .map(function (n) { return n.id; }) : (s.focus || []).slice();
      (s.flows || []).forEach(function (st) {
        [].concat(st).forEach(function (f) {
          var ends = f.split(':')[0].split('>');
          focus.push(ends[0], ends[1]);
        });
      });
      focus.forEach(function (id) {
        if (byId[id]) byId[id].el.classList.add('focus');
      });
      root.classList.toggle('has-focus', focus.length > 0);
      num.textContent = 'Step ' + (i + 1) + ' of ' + cfg.steps.length;
      stitle.textContent = s.title;
      stext.textContent = s.text;
      clock.textContent = s.clock || '';
      clock.classList.toggle('on', !!s.clock);
      tag.textContent = s.tag || '';
      tag.classList.toggle('on', !!s.tag);
      dotBtns.forEach(function (b, k) {
        b.className = k === i ? 'here' : (k < i ? 'done' : '');
      });
      bPrev.disabled = i === 0;
      bNext.disabled = i === cfg.steps.length - 1;
    }

    async function go(i) {
      var my = ++epoch;
      tokenLayer.innerHTML = '';
      current = i;
      show(i);
      var s = cfg.steps[i];
      if (!(await wait(REDUCED ? 0 : 350, my))) return;
      var stages = s.flows || [];
      for (var k = 0; k < stages.length; k++) {
        var hits = [].concat(stages[k]).map(parseFlow).filter(Boolean);
        await Promise.all(hits.map(function (h) { return travel(h, my); }));
        if (my !== epoch) return;
      }
      var pause = 1400 + s.text.length * 18;
      if (!(await wait(pause / speed, my))) return;
      if (playing) {
        if (i < cfg.steps.length - 1) {
          go(i + 1);
        } else {
          stop();
        }
      }
    }

    function stop() {
      playing = false;
      bPlay.textContent = '▶ Play';
    }

    function togglePlay() {
      if (playing) {
        stop();
        return;
      }
      playing = true;
      bPlay.textContent = '⏸ Pause';
      go(current === cfg.steps.length - 1 ? 0 : current);
    }

    bPlay.addEventListener('click', togglePlay);
    bRestart.addEventListener('click', function () {
      playing = true;
      bPlay.textContent = '⏸ Pause';
      go(0);
    });
    bPrev.addEventListener('click', function () {
      stop();
      if (current > 0) go(current - 1);
    });
    bNext.addEventListener('click', function () {
      stop();
      if (current < cfg.steps.length - 1) go(current + 1);
    });
    bReplay.addEventListener('click', function () { go(current); });
    speedSel.addEventListener('change', function () {
      speed = parseFloat(speedSel.value);
    });
    document.addEventListener('keydown', function (ev) {
      if (ev.target.tagName === 'SELECT') return;
      if (ev.key === ' ') { ev.preventDefault(); togglePlay(); }
      else if (ev.key === 'ArrowRight') bNext.click();
      else if (ev.key === 'ArrowLeft') bPrev.click();
      else if (ev.key === 'r' || ev.key === 'R') bReplay.click();
    });

    notes();
    document.title = (isInc ? 'Increment ' + cfg.inc + ' · ' +
        INCS[cfg.inc][1] : cfg.name) + ' · premarket-ai';
    show(0);
    if (!REDUCED) {
      setTimeout(function () { if (!playing && current === 0) togglePlay(); },
          900);
    }
  }

  window.PremarketAnim = {run: run, increments: INCS, topics: TOPICS};
})();

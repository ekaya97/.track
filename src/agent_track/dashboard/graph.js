/**
 * .track — The Score: Interactive d3 Force-Directed Code Graph
 *
 * Renders file nodes, import/call edges, and overlays for agent activity,
 * duplicates, test coverage gaps, and security findings.
 */

(function () {
  "use strict";

  const container = document.getElementById("graph-container");
  if (!container) return;

  const width = container.clientWidth;
  const height = container.clientHeight;

  // ── State ────────────────────────────────────────────────────────────────
  let graphData = null;
  let analysisData = { duplicates: null, coverage: null, security: null };
  let agentActivity = {};  // {relative_file: {agent, last_active, tool}}
  let selectedNode = null;

  // ── SVG setup ────────────────────────────────────────────────────────────
  const svg = d3
    .select(container)
    .append("svg")
    .attr("width", width)
    .attr("height", height);

  const defs = svg.append("defs");
  // Glow filter for agent halos
  const glow = defs.append("filter").attr("id", "glow");
  glow.append("feGaussianBlur").attr("stdDeviation", "3").attr("result", "blur");
  const feMerge = glow.append("feMerge");
  feMerge.append("feMergeNode").attr("in", "blur");
  feMerge.append("feMergeNode").attr("in", "SourceGraphic");

  const g = svg.append("g");

  // Zoom
  const zoom = d3
    .zoom()
    .scaleExtent([0.1, 8])
    .on("zoom", (event) => g.attr("transform", event.transform));
  svg.call(zoom);

  // Tooltip
  const tooltip = d3
    .select(container)
    .append("div")
    .attr("class", "tooltip")
    .style("display", "none");

  // Language color scale
  const langColors = {
    python: "#4B8BBE",
    javascript: "#F7DF1E",
    typescript: "#3178C6",
    unknown: "#888",
  };

  // ── Load data ────────────────────────────────────────────────────────────
  Promise.all([
    fetch("/api/graph/symbol").then((r) => r.json()),
    fetch("/api/analysis/duplicates").then((r) => r.json()).catch(() => null),
    fetch("/api/analysis/coverage").then((r) => r.json()).catch(() => null),
    fetch("/api/analysis/security").then((r) => r.json()).catch(() => null),
    fetch("/api/agents/activity").then((r) => r.json()).catch(() => ({})),
  ]).then(([graph, dupes, coverage, security, activity]) => {
    if (graph.error) {
      container.innerHTML =
        '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#666;font-family:monospace">' +
        "<div>No graph data yet. Run <code>track analyze</code> first.</div></div>";
      return;
    }
    graphData = graph;
    analysisData = { duplicates: dupes, coverage, security };
    agentActivity = activity || {};
    render();
    populateFilters();
  });

  // ── Render graph ─────────────────────────────────────────────────────────
  function render() {
    if (!graphData) return;
    g.selectAll("*").remove();

    const nodes = graphData.nodes.map((n) => ({ ...n }));
    const nodeIndex = new Map(nodes.map((n) => [n.id, n]));

    // Build edges — only include edges where both source and target are file nodes
    const edges = [];
    const edgeSet = new Set();
    for (const e of graphData.edges) {
      let sourceId, targetId;
      if (e.type === "import") {
        sourceId = e.source;
        targetId = e.target;
        if (!targetId || !nodeIndex.has(sourceId) || !nodeIndex.has(targetId)) continue;
      } else if (e.type === "call") {
        sourceId = e.source.split("::")[0];
        targetId = e.target.split("::")[0];
        if (sourceId === targetId) continue; // skip self-calls
        if (!nodeIndex.has(sourceId) || !nodeIndex.has(targetId)) continue;
      } else {
        continue;
      }
      const key = `${sourceId}->${targetId}:${e.type}`;
      if (edgeSet.has(key)) continue;
      edgeSet.add(key);
      edges.push({ source: sourceId, target: targetId, type: e.type });
    }

    // Compute overlay sets
    const duplicateFiles = new Set();
    if (analysisData.duplicates && analysisData.duplicates.clusters) {
      for (const c of analysisData.duplicates.clusters) {
        for (const f of c.functions) duplicateFiles.add(f.file);
      }
    }

    const untestedFiles = new Set();
    if (analysisData.coverage && analysisData.coverage.untested_files) {
      for (const u of analysisData.coverage.untested_files) untestedFiles.add(u.file);
    }

    const securityFiles = new Set();
    if (analysisData.security && analysisData.security.findings) {
      for (const f of analysisData.security.findings) securityFiles.add(f.file);
    }

    // ── Force simulation ─────────────────────────────────────────────────
    const simulation = d3
      .forceSimulation(nodes)
      .force(
        "link",
        d3
          .forceLink(edges)
          .id((d) => d.id)
          .distance(80)
      )
      .force("charge", d3.forceManyBody().strength(-200))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collision", d3.forceCollide().radius((d) => nodeRadius(d) + 4));

    // ── Edges ────────────────────────────────────────────────────────────
    const link = g
      .append("g")
      .selectAll("line")
      .data(edges)
      .join("line")
      .attr("class", (d) => `link ${d.type}`)
      .attr("stroke", (d) => (d.type === "call" ? "#555" : "#444"));

    // ── Nodes ────────────────────────────────────────────────────────────
    const node = g
      .append("g")
      .selectAll("g")
      .data(nodes)
      .join("g")
      .attr("class", "node")
      .call(drag(simulation));

    // Agent halo — active if agent touched this file recently
    node
      .append("circle")
      .attr("class", (d) => {
        const info = agentActivity[d.id];
        if (!info) return "agent-halo";
        // Check if active within last 60 seconds
        const isRecent = _isRecentActivity(info.last_active, 60);
        return isRecent ? "agent-halo active" : "agent-halo fading";
      })
      .attr("r", (d) => nodeRadius(d) + 6)
      .attr("stroke", (d) => {
        const info = agentActivity[d.id];
        return info ? _agentColor(info.agent) : "#00ff88";
      });

    // Main circle
    node
      .append("circle")
      .attr("r", (d) => nodeRadius(d))
      .attr("fill", (d) => langColors[d.language] || langColors.unknown)
      .attr("opacity", 0.85);

    // Label
    node
      .append("text")
      .attr("dy", (d) => nodeRadius(d) + 12)
      .attr("text-anchor", "middle")
      .text((d) => d.id.split("/").pop());

    // ── Interactions ─────────────────────────────────────────────────────
    node
      .on("mouseover", function (event, d) {
        tooltip
          .style("display", "block")
          .html(`<strong>${d.id}</strong><br>${d.language} · ${d.lines} lines · ${d.symbols.length} symbols`)
          .style("left", event.offsetX + 12 + "px")
          .style("top", event.offsetY - 10 + "px");

        // Highlight connected edges
        link.classed("highlighted", (l) => l.source.id === d.id || l.target.id === d.id);
      })
      .on("mouseout", function () {
        tooltip.style("display", "none");
        link.classed("highlighted", false);
      })
      .on("click", function (event, d) {
        selectedNode = d;
        node.classed("selected", (n) => n.id === d.id);
        updateInspector(d);
      });

    // ── Simulation tick ──────────────────────────────────────────────────
    simulation.on("tick", () => {
      link
        .attr("x1", (d) => d.source.x)
        .attr("y1", (d) => d.source.y)
        .attr("x2", (d) => d.target.x)
        .attr("y2", (d) => d.target.y);
      node.attr("transform", (d) => `translate(${d.x},${d.y})`);
    });

    // Fit view after simulation settles
    simulation.on("end", () => {
      const bounds = g.node().getBBox();
      const pad = 40;
      const scale = Math.min(
        width / (bounds.width + pad * 2),
        height / (bounds.height + pad * 2),
        1.5
      );
      const tx = width / 2 - (bounds.x + bounds.width / 2) * scale;
      const ty = height / 2 - (bounds.y + bounds.height / 2) * scale;
      svg
        .transition()
        .duration(500)
        .call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
    });

    // Store for overlay toggling
    window._graphNodes = node;
    window._graphLinks = link;
    window._duplicateFiles = duplicateFiles;
    window._untestedFiles = untestedFiles;
    window._securityFiles = securityFiles;
  }

  // ── Helpers ──────────────────────────────────────────────────────────────
  function nodeRadius(d) {
    return Math.max(4, Math.sqrt(d.lines || 1) * 1.5);
  }

  // Agent color palette — consistent per agent name
  const _agentColors = [
    "#00ff88", "#ff6b6b", "#4ecdc4", "#ffe66d", "#a78bfa",
    "#f97316", "#06b6d4", "#ec4899", "#84cc16", "#8b5cf6",
  ];
  function _agentColor(agentId) {
    let hash = 0;
    for (let i = 0; i < agentId.length; i++) hash = (hash * 31 + agentId.charCodeAt(i)) | 0;
    return _agentColors[Math.abs(hash) % _agentColors.length];
  }

  function _isRecentActivity(isoStr, withinSeconds) {
    if (!isoStr) return false;
    try {
      const then = new Date(isoStr.replace("Z", "+00:00")).getTime();
      const now = Date.now();
      return (now - then) / 1000 < withinSeconds;
    } catch { return false; }
  }

  function drag(simulation) {
    return d3
      .drag()
      .on("start", (event, d) => {
        if (!event.active) simulation.alphaTarget(0.3).restart();
        d.fx = d.x;
        d.fy = d.y;
      })
      .on("drag", (event, d) => {
        d.fx = event.x;
        d.fy = event.y;
      })
      .on("end", (event, d) => {
        if (!event.active) simulation.alphaTarget(0);
        d.fx = null;
        d.fy = null;
      });
  }

  function updateInspector(d) {
    const el = document.querySelector("#inspector .inspector-content");
    if (!el) return;

    // Open the right panel
    if (typeof openPanel === "function") openPanel();
    document.querySelector(".dash-layout").classList.add("panel-open");

    const symbols = d.symbols || [];
    const funcs = symbols.filter((s) => s.type === "function" || s.type === "async_function");
    const classes = symbols.filter((s) => s.type === "class");

    // Agent & ticket info
    let ownershipHtml = "";
    const activity = agentActivity[d.id];
    if (activity) {
      const color = _agentColor(activity.agent);
      ownershipHtml = `<div class="inspector-section">
        <div class="inspector-section-title">Ownership</div>
        <div class="detail-row"><span class="detail-label">Agent</span><span class="detail-value" style="color:${color};font-weight:600">${activity.agent}</span></div>
        <div class="detail-row"><span class="detail-label">Last touch</span><span class="detail-value">${activity.tool} @ ${activity.last_active.slice(11, 19)}</span></div>
      </div>`;
    }

    // Analysis findings
    // Analysis findings
    let analysisHtml = "";
    let analysisItems = [];

    // Duplicates — show actual function pairs
    if (analysisData.duplicates && analysisData.duplicates.clusters) {
      const dupes = analysisData.duplicates.clusters.filter((c) =>
        c.functions.some((f) => f.file === d.id)
      );
      if (dupes.length) {
        let dupeDetail = "";
        for (const cluster of dupes) {
          const thisFile = cluster.functions.filter((f) => f.file === d.id);
          const otherFiles = cluster.functions.filter((f) => f.file !== d.id);
          const simLabel = cluster.type === "exact" ? "exact" :
            cluster.similarity ? Math.round(cluster.similarity * 100) + "%" : "near";
          for (const fn of thisFile) {
            const others = otherFiles.map((o) =>
              `<div style="font-size:10px;color:var(--text-muted);padding-left:12px;margin:1px 0">&#8627; ${o.file.split("/").pop()}:<b>${o.name}</b> L${o.line_start}</div>`
            ).join("");
            dupeDetail += `<div style="margin:4px 0">` +
              `<div style="font-size:11px"><span style="color:var(--warning)">fn:</span> <b>${fn.name}</b> <span class="sidebar-count">${simLabel}</span> L${fn.line_start}-${fn.line_end}</div>` +
              others + `</div>`;
          }
        }
        analysisItems.push(
          `<div style="margin-bottom:6px"><div class="detail-row"><span class="detail-label" style="color:var(--warning)">&#9888; Duplicates</span><span class="detail-value">${dupes.length} cluster(s)</span></div>` +
          dupeDetail + `</div>`
        );
      }
    }

    // Security findings — show details
    if (analysisData.security && analysisData.security.findings) {
      const secFindings = analysisData.security.findings.filter((f) => f.file === d.id);
      if (secFindings.length) {
        let secDetail = secFindings.map((f) =>
          `<div style="font-size:10px;color:var(--text-muted);margin:2px 0">L${f.line}: ${f.pattern || f.type}</div>`
        ).join("");
        analysisItems.push(
          `<div style="margin-bottom:6px"><div class="detail-row"><span class="detail-label" style="color:var(--danger)">&#9888; Security</span><span class="detail-value">${secFindings.length} finding(s)</span></div>` +
          secDetail + `</div>`
        );
      }
    }

    // Coverage
    if (analysisData.coverage && analysisData.coverage.untested_files) {
      const uf = analysisData.coverage.untested_files.find((f) => f.file === d.id);
      if (uf) {
        const fns = (uf.functions || []).map((n) =>
          `<div style="font-size:10px;color:var(--text-muted);margin:1px 0">&#9675; ${n}</div>`
        ).join("");
        analysisItems.push(
          `<div style="margin-bottom:6px"><div class="detail-row"><span class="detail-label" style="color:var(--danger)">&#9675; Untested</span><span class="detail-value">no coverage</span></div>` +
          fns + `</div>`
        );
      }
    }

    if (analysisItems.length) {
      analysisHtml = `<div class="inspector-section"><div class="inspector-section-title">Analysis</div>${analysisItems.join("")}</div>`;
    }

    // Connections
    let connectionsHtml = "";
    if (graphData && graphData.edges) {
      const imports = graphData.edges.filter((e) => {
        const src = typeof e.source === "object" ? e.source.id : e.source;
        return src === d.id && e.type === "import";
      }).length;
      const importedBy = graphData.edges.filter((e) => {
        const tgt = typeof e.target === "object" ? e.target.id : e.target;
        return tgt === d.id && e.type === "import";
      }).length;
      if (imports || importedBy) {
        connectionsHtml = `<div class="inspector-section"><div class="inspector-section-title">Connections</div>
          <div class="detail-row"><span class="detail-label">Imports</span><span class="detail-value">${imports} files</span></div>
          <div class="detail-row"><span class="detail-label">Imported by</span><span class="detail-value">${importedBy} files</span></div>
        </div>`;
      }
    }

    // Symbols (collapsed)
    let symbolsHtml = "";
    if (funcs.length || classes.length) {
      const items = [
        ...classes.map((s) => `<div style="font-size:11px;padding:1px 0;color:var(--text-secondary)">cls: ${s.name}</div>`),
        ...funcs.map((s) => `<div style="font-size:11px;padding:1px 0;color:var(--text-secondary)">fn: ${s.name}</div>`),
      ];
      symbolsHtml = `<div class="inspector-section">
        <div class="inspector-section-title">Symbols (${funcs.length + classes.length})</div>
        <div style="max-height:120px;overflow-y:auto">${items.join("")}</div>
      </div>`;
    }

    el.innerHTML =
      `<div class="file-name">${d.id}</div>` +
      `<div style="display:flex;gap:8px;margin-bottom:8px">` +
      `<span class="sidebar-count">${d.language}</span>` +
      `<span class="sidebar-count">${d.lines} lines</span>` +
      `<span class="sidebar-count">${funcs.length} fn</span>` +
      `<span class="sidebar-count">${classes.length} cls</span>` +
      `</div>` +
      ownershipHtml +
      analysisHtml +
      connectionsHtml +
      symbolsHtml;

    // Update board panel to show messages relevant to this node's ticket
    _updateBoardForNode(d);
  }

  function _updateBoardForNode(d) {
    const boardEl = document.querySelector("#panel-board");
    if (!boardEl) return;

    // Find the ticket associated with this file via agent activity
    const activity = agentActivity[d.id];
    const ticketId = activity ? activity.ticket : null;

    fetch("/api/board?limit=50")
      .then((r) => r.json())
      .then((entries) => {
        // Filter: show entries for this ticket, or if no ticket, show all
        let filtered = entries;
        if (ticketId) {
          filtered = entries.filter((e) => e.ticket === ticketId);
          if (filtered.length === 0) filtered = entries.slice(0, 5);
        } else {
          filtered = entries.slice(0, 5);
        }

        const titleEl = boardEl.querySelector(".sidebar-title");
        if (titleEl) {
          const countEl = titleEl.querySelector(".sidebar-count");
          const label = ticketId ? `Board · ${ticketId}` : "Board";
          if (countEl) {
            titleEl.childNodes[0].textContent = label + " ";
            countEl.textContent = filtered.length;
          }
        }

        // Render entries
        const container = boardEl.querySelector(".sidebar-title");
        if (!container) return;
        let html = "";
        for (const e of filtered) {
          const ts = (e.timestamp || "?").slice(11, 16);
          const who = e.agent || "?";
          const tRef = e.ticket && e.ticket !== "system" ? ` · ${e.ticket}` : "";
          const msg = e.message || "";
          html += `<div class="board-item"><div class="board-item-header">` +
            `<span class="board-item-who">${who}${tRef}</span>` +
            `<span class="board-item-when">${ts}</span></div>` +
            `<div class="board-item-msg">${msg}</div></div>`;
        }
        if (!filtered.length) html = '<div class="text-muted" style="font-size:12px;padding:8px">No messages</div>';

        // Replace content after the title
        const existing = boardEl.querySelectorAll(".board-item, .text-muted");
        existing.forEach((el) => el.remove());
        container.insertAdjacentHTML("afterend", html);
      })
      .catch(() => {});
  }

  function populateFilters() {
    if (!graphData) return;

    const dirs = [...new Set(graphData.nodes.map((n) => n.directory))].sort();
    const langs = [...new Set(graphData.nodes.map((n) => n.language))].sort();

    const dirSelect = document.getElementById("filter-dir");
    const langSelect = document.getElementById("filter-lang");

    if (dirSelect) {
      for (const d of dirs) {
        const opt = document.createElement("option");
        opt.value = d;
        opt.textContent = d;
        dirSelect.appendChild(opt);
      }
      dirSelect.addEventListener("change", applyFilters);
    }

    if (langSelect) {
      for (const l of langs) {
        const opt = document.createElement("option");
        opt.value = l;
        opt.textContent = l;
        langSelect.appendChild(opt);
      }
      langSelect.addEventListener("change", applyFilters);
    }
  }

  function applyFilters() {
    if (!window._graphNodes) return;
    const dir = document.getElementById("filter-dir").value;
    const lang = document.getElementById("filter-lang").value;

    window._graphNodes.style("opacity", (d) => {
      if (dir && d.directory !== dir) return 0.1;
      if (lang && d.language !== lang) return 0.1;
      return 1;
    });
  }

  // ── Overlay toggles ────────────────────────────────────────────────────
  document.getElementById("overlay-dupes")?.addEventListener("change", function () {
    if (!window._graphNodes) return;
    window._graphNodes.classed("duplicate", (d) =>
      this.checked && window._duplicateFiles.has(d.id)
    );
  });

  document.getElementById("overlay-tests")?.addEventListener("change", function () {
    if (!window._graphNodes) return;
    window._graphNodes.classed("untested", (d) =>
      this.checked && window._untestedFiles.has(d.id)
    );
  });

  document.getElementById("overlay-security")?.addEventListener("change", function () {
    if (!window._graphNodes) return;
    window._graphNodes.classed("security-finding", (d) =>
      this.checked && window._securityFiles.has(d.id)
    );
  });

  // ── Agents overlay toggle ───────────────────────────────────────────────
  document.getElementById("overlay-agents")?.addEventListener("change", function () {
    if (!window._graphNodes) return;
    window._graphNodes.selectAll(".agent-halo")
      .classed("active", (d) => this.checked && !!agentActivity[d.id] && _isRecentActivity(agentActivity[d.id].last_active, 300))
      .classed("fading", (d) => this.checked && !!agentActivity[d.id] && !_isRecentActivity(agentActivity[d.id].last_active, 300));
  });

  // ── Polling for agent activity updates ─────────────────────────────────
  // Poll every 5 seconds for fresh agent activity data and update halos
  setInterval(function () {
    fetch("/api/agents/activity")
      .then((r) => r.json())
      .then((activity) => {
        agentActivity = activity || {};
        if (!window._graphNodes) return;
        const agentsChecked = document.getElementById("overlay-agents")?.checked;
        if (!agentsChecked) return;
        // Update halo classes
        window._graphNodes.selectAll(".agent-halo")
          .classed("active", (d) => !!agentActivity[d.id] && _isRecentActivity(agentActivity[d.id].last_active, 300))
          .classed("fading", (d) => !!agentActivity[d.id] && !_isRecentActivity(agentActivity[d.id].last_active, 300));
      })
      .catch(() => {});
  }, 5000);

  // ── SSE for live updates ───────────────────────────────────────────────
  if (typeof EventSource !== "undefined") {
    const source = new EventSource("/api/events");
    source.addEventListener("graph-update", function (e) {
      fetch("/api/graph/symbol")
        .then((r) => r.json())
        .then((graph) => {
          if (!graph.error) {
            graphData = graph;
            render();
          }
        });
    });
    source.onerror = function () {
      // Silently reconnect
    };
  }

  // ── Agent pill interactions ─────────────────────────────────────────────
  let activeAgentFilter = null;

  document.querySelectorAll(".agent-pill").forEach(function (pill) {
    const agentId = pill.dataset.agent;

    pill.addEventListener("mouseenter", function () {
      if (activeAgentFilter) return; // don't override click filter
      if (!window._graphNodes) return;
      window._graphNodes.classed("dimmed", function (d) {
        const act = agentActivity[d.id];
        return !act || act.agent !== agentId;
      });
    });

    pill.addEventListener("mouseleave", function () {
      if (activeAgentFilter) return;
      if (!window._graphNodes) return;
      window._graphNodes.classed("dimmed", false);
    });

    pill.addEventListener("click", function () {
      if (!window._graphNodes) return;
      if (activeAgentFilter === agentId) {
        // Toggle off
        activeAgentFilter = null;
        window._graphNodes.classed("dimmed", false);
        document.querySelectorAll(".agent-pill").forEach(function (p) {
          p.style.opacity = "";
        });
      } else {
        activeAgentFilter = agentId;
        window._graphNodes.classed("dimmed", function (d) {
          const act = agentActivity[d.id];
          return !act || act.agent !== agentId;
        });
        document.querySelectorAll(".agent-pill").forEach(function (p) {
          p.style.opacity = p.dataset.agent === agentId ? "1" : "0.4";
        });
      }
    });
  });

  // ── Keyboard shortcuts ──────────────────────────────────────────────────
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      // Deselect node and close panel
      if (window._graphNodes) window._graphNodes.classed("selected", false);
      selectedNode = null;
      document.querySelector(".dash-layout").classList.remove("panel-open");
      // Clear agent filter
      if (activeAgentFilter) {
        activeAgentFilter = null;
        window._graphNodes.classed("dimmed", false);
        document.querySelectorAll(".agent-pill").forEach(function (p) {
          p.style.opacity = "";
        });
      }
    }
  });
})();

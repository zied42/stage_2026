import React, { useState } from 'react';

export default function DependencyGraph({ graphData }) {
  if (!graphData) return null;

  const { nodes = [], edges = [], blueprint_name = '', project = '' } = graphData;
  const [zoomLevel, setZoomLevel] = useState(1);

  if (nodes.length === 0) {
    return (
      <div className="card dependencyGraphCard">
        <div className="sectionHeader">
          <div>
            <div className="sectionTitle">Dependency Structure</div>
            <div className="sectionSubtitle">Visualization of change dependencies within this blueprint</div>
          </div>
        </div>
        <div className="graphEmptyState">
          <div className="emptyIcon">🔗</div>
          <div className="emptyTitle">No Change Dependencies Found</div>
          <div className="emptyDesc">
            This blueprint currently has no interconnected Git ancestor or depends-on change relationships.
          </div>
        </div>
      </div>
    );
  }

  const getNodeKey = (n) => n.hash || n.change_id || n.id;
  const getEdgeSource = (e) => e.from || e.source;
  const getEdgeTarget = (e) => e.to || e.target;

  const nodeWidth = 190;
  const nodeHeight = 76;
  const hSpacing = 240;
  const vSpacing = 130;

  // 1. Calculate in-degrees
  const inDegree = {};
  nodes.forEach(n => {
    inDegree[getNodeKey(n)] = 0;
  });

  edges.forEach(e => {
    const target = getEdgeTarget(e);
    if (inDegree[target] !== undefined) {
      inDegree[target]++;
    }
  });

  // 2. Stratify nodes into layers (roots at layer 0)
  const layers = [];
  let currentLayer = nodes.filter(n => inDegree[getNodeKey(n)] === 0);
  if (currentLayer.length === 0 && nodes.length > 0) {
    currentLayer = [nodes[0]];
  }

  const placed = new Set(currentLayer.map(n => getNodeKey(n)));
  
  while (currentLayer.length > 0) {
    layers.push(currentLayer);
    const nextLayer = [];
    
    edges.forEach(e => {
      const src = getEdgeSource(e);
      const tgt = getEdgeTarget(e);
      if (placed.has(src) && !placed.has(tgt)) {
        const targetNode = nodes.find(n => getNodeKey(n) === tgt);
        if (targetNode && !nextLayer.some(n => getNodeKey(n) === tgt)) {
          nextLayer.push(targetNode);
          placed.add(tgt);
        }
      }
    });

    // Handle any remaining disconnected nodes
    if (nextLayer.length === 0 && placed.size < nodes.length) {
      const remaining = nodes.filter(n => !placed.has(getNodeKey(n)));
      if (remaining.length > 0) {
        const chunk = remaining.slice(0, Math.min(4, remaining.length));
        chunk.forEach(n => placed.add(getNodeKey(n)));
        nextLayer.push(...chunk);
      }
    }

    currentLayer = nextLayer;
  }

  // 3. Find max layer width to center all layers
  let maxNodesInLayer = 1;
  layers.forEach(l => {
    if (l.length > maxNodesInLayer) maxNodesInLayer = l.length;
  });

  const canvasWidth = Math.max(maxNodesInLayer * hSpacing + 120, 800);
  const canvasHeight = Math.max(layers.length * vSpacing + 80, 420);

  // 4. Compute centered layout positions
  const positions = {};
  layers.forEach((layer, yIdx) => {
    const y = yIdx * vSpacing + 40;
    const layerTotalWidth = (layer.length - 1) * hSpacing;
    const startX = (canvasWidth - layerTotalWidth) / 2 - (nodeWidth / 2);

    layer.forEach((node, xIdx) => {
      const x = startX + xIdx * hSpacing;
      positions[getNodeKey(node)] = { x, y };
    });
  });

  return (
    <div className="card dependencyGraphCard">
      <div className="graphCardHeader">
        <div>
          <div className="sectionTitle">Dependency Structure</div>
          <div className="sectionSubtitle">
            Visualization of change dependencies within this blueprint ({nodes.length} nodes, {edges.length} edges)
          </div>
        </div>

        {/* Zoom Controls & Legend */}
        <div className="graphHeaderActions">
          <div className="graphLegend">
            <span className="legendItem"><span className="legendDot merged"></span> Merged</span>
            <span className="legendItem"><span className="legendDot open"></span> Open / Active</span>
            <span className="legendItem"><span className="legendLine"></span> Dependency</span>
          </div>
          <div className="zoomControls">
            <button className="zoomBtn" onClick={() => setZoomLevel(z => Math.max(0.6, z - 0.1))} title="Zoom Out">−</button>
            <span className="zoomLabel">{Math.round(zoomLevel * 100)}%</span>
            <button className="zoomBtn" onClick={() => setZoomLevel(z => Math.min(1.5, z + 0.1))} title="Zoom In">+</button>
            <button className="zoomBtn reset" onClick={() => setZoomLevel(1)} title="Reset Zoom">Reset</button>
          </div>
        </div>
      </div>

      <div className="graphViewport">
        <div 
          className="graphCanvasContainer"
          style={{ transform: `scale(${zoomLevel})`, transformOrigin: 'top center', transition: 'transform 0.2s ease' }}
        >
          <svg 
            viewBox={`0 0 ${canvasWidth} ${canvasHeight}`} 
            style={{ width: `${canvasWidth}px`, height: `${canvasHeight}px`, display: 'block', margin: '0 auto' }}
          >
            <defs>
              <linearGradient id="edgeGrad" x1="0%" y1="0%" x2="0%" y2="100%">
                <stop offset="0%" stopColor="#3b82f6" stopOpacity="0.8" />
                <stop offset="100%" stopColor="#8b5cf6" stopOpacity="0.8" />
              </linearGradient>
              <marker 
                id="arrowhead" 
                viewBox="0 0 12 12" 
                refX="10" 
                refY="6" 
                markerWidth="8" 
                markerHeight="8" 
                orient="auto-start-reverse"
              >
                <path d="M 1 1 L 11 6 L 1 11 Z" fill="#6366f1" />
              </marker>
              <filter id="nodeShadow" x="-10%" y="-10%" width="125%" height="125%">
                <feDropShadow dx="0" dy="4" stdDeviation="6" floodOpacity="0.08" />
              </filter>
            </defs>
            
            {/* Draw Dependency Edges */}
            {edges.map((e, i) => {
              const p1 = positions[getEdgeSource(e)];
              const p2 = positions[getEdgeTarget(e)];
              if (!p1 || !p2) return null;

              const x1 = p1.x + nodeWidth / 2;
              const y1 = p1.y + nodeHeight;
              const x2 = p2.x + nodeWidth / 2;
              const y2 = p2.y;

              // Smooth curved bezier path
              const midY = (y1 + y2) / 2;
              const pathD = `M ${x1} ${y1} C ${x1} ${midY}, ${x2} ${midY}, ${x2} ${y2}`;

              return (
                <g key={i} className="graphEdgeGroup">
                  <path 
                    d={pathD}
                    fill="none"
                    stroke="#6366f1"
                    strokeWidth="2.2"
                    strokeDasharray={e.kind === 'git_ancestor' ? 'none' : '5,4'}
                    markerEnd="url(#arrowhead)"
                  />
                  {e.kind && (
                    <text 
                      x={(x1 + x2) / 2} 
                      y={midY - 6} 
                      fontSize="9" 
                      fill="var(--muted)" 
                      textAnchor="middle"
                      className="edgeKindLabel"
                    >
                      {e.kind}
                    </text>
                  )}
                </g>
              );
            })}

            {/* Draw Change Nodes */}
            {nodes.map(n => {
              const key = getNodeKey(n);
              const pos = positions[key];
              if (!pos) return null;

              const isMerged = !!n.merged_date || (n.status && n.status.toUpperCase() === 'MERGED');
              const displayHash = (n.hash || n.change_id || '').substring(0, 8);
              const author = n.author || 'Unknown';
              const date = n.authored_date || n.merged_date || '';
              const subject = n.subject || '';

              return (
                <g 
                  key={key} 
                  className={`graphNodeGroup ${isMerged ? 'nodeMerged' : 'nodeOpen'}`} 
                  transform={`translate(${pos.x}, ${pos.y})`}
                  filter="url(#nodeShadow)"
                >
                  <rect 
                    width={nodeWidth} 
                    height={nodeHeight} 
                    fill="var(--card)"
                    stroke={isMerged ? "#22c55e" : "#f59e0b"}
                    strokeWidth="2"
                    rx="10"
                    ry="10"
                    className="nodeRect"
                  />
                  
                  {/* Status header inside node */}
                  <rect 
                    x="1" 
                    y="1" 
                    width={nodeWidth - 2} 
                    height="24" 
                    fill={isMerged ? "rgba(34, 197, 94, 0.08)" : "rgba(245, 158, 11, 0.08)"}
                    rx="9"
                    ry="9"
                  />
                  
                  {/* Status badge */}
                  <circle 
                    cx="14" 
                    cy="13" 
                    r="4.5" 
                    fill={isMerged ? "#22c55e" : "#f59e0b"} 
                  />
                  <text 
                    x="24" 
                    y="16" 
                    fontWeight="700" 
                    fontSize="11" 
                    fontFamily="monospace"
                    fill="var(--text)"
                  >
                    {displayHash}
                  </text>
                  
                  <text 
                    x={nodeWidth - 10} 
                    y="16" 
                    fontSize="9.5" 
                    fontWeight="600"
                    textAnchor="end"
                    fill={isMerged ? "#16a34a" : "#d97706"}
                  >
                    {isMerged ? 'MERGED' : 'OPEN'}
                  </text>

                  {/* Author */}
                  <text 
                    x="12" 
                    y="42" 
                    fill="var(--text)" 
                    fontSize="11.5"
                    fontWeight="500"
                  >
                    {author.length > 20 ? author.substring(0, 18) + '...' : author}
                  </text>

                  {/* Subject or Date */}
                  <text 
                    x="12" 
                    y="60" 
                    fill="var(--muted)" 
                    fontSize="9.5"
                  >
                    {subject ? (subject.length > 24 ? subject.substring(0, 22) + '...' : subject) : date}
                  </text>
                </g>
              );
            })}
          </svg>
        </div>
      </div>
    </div>
  );
}

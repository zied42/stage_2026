import React from 'react';

export default function GraphMetrics({ graphData }) {
  if (!graphData) return null;

  const { nodes = [], edges = [], total_changes = 0, isolated_changes = 0 } = graphData;
  const n = nodes.length;
  const e = edges.length;
  
  const getNodeKey = (node) => node.hash || node.change_id || node.id;
  const getEdgeSource = (edge) => edge.from || edge.source;
  const getEdgeTarget = (edge) => edge.to || edge.target;

  const inDegree = {};
  const outDegree = {};
  nodes.forEach(node => {
    const key = getNodeKey(node);
    inDegree[key] = 0;
    outDegree[key] = 0;
  });
  
  edges.forEach(edge => {
    const src = getEdgeSource(edge);
    const tgt = getEdgeTarget(edge);
    if (inDegree[tgt] !== undefined) inDegree[tgt]++;
    if (outDegree[src] !== undefined) outDegree[src]++;
  });

  const rootNodes = nodes.filter(node => (inDegree[getNodeKey(node)] || 0) === 0).length;
  const leafNodes = nodes.filter(node => (outDegree[getNodeKey(node)] || 0) === 0).length;
  const density = n > 1 ? (e / (n * (n - 1))).toFixed(3) : "0.000";

  const metrics = [
    { label: 'Total Changes', value: total_changes || n, icon: '🔄', desc: 'All changes in blueprint' },
    { label: 'Dependencies', value: e, icon: '🔗', desc: 'Active graph edges' },
    { label: 'Isolated', value: isolated_changes, icon: '📦', desc: 'Changes without dependencies' },
    { label: 'Root Nodes', value: rootNodes, icon: '🌱', desc: 'Independent starting changes' },
    { label: 'Leaf Nodes', value: leafNodes, icon: '🍃', desc: 'Terminal downstream changes' },
    { label: 'Density', value: density, icon: '📈', desc: 'Graph connection ratio' }
  ];

  return (
    <div className="card graphMetricsCard">
      <div className="sectionHeader">
        <div>
          <div className="sectionTitle">Graph Metrics</div>
          <div className="sectionSubtitle">Structural complexity indicators computed from dependency relations</div>
        </div>
      </div>
      
      <div className="metricsGrid3Col">
        {metrics.map((m, idx) => (
          <div className="metricCardItem" key={idx}>
            <div className="metricTopRow">
              <div className="metricLabelText">{m.label}</div>
              <div className="metricIconBadge">{m.icon}</div>
            </div>
            <div className="metricNumberValue">{m.value}</div>
            <div className="metricDescText">{m.desc}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

import React, { useState, useEffect } from 'react';
import BlueprintSelector from './BlueprintSelector';
import DependencyGraph from './DependencyGraph';
import GraphMetrics from './GraphMetrics';

function StatCard({ label, value, icon }) {
  return (
    <div className="statCard">
      <div className="statText">
        <div className="statLabel">{label}</div>
        <div className="statValue">{value}</div>
      </div>
      <div className="statIcon">{icon}</div>
    </div>
  );
}

function BottleneckPredictionCard({ bottleneck }) {
  if (!bottleneck) return null;
  const probPercent = Math.round((bottleneck.probability || 0) * 100);
  const statusLower = (bottleneck.status || '').toLowerCase();
  const statusClass = statusLower.includes('high') ? 'high' : statusLower.includes('medium') ? 'medium' : 'low';
  const breakdown = bottleneck.change_breakdown || {};
  
  return (
    <div className="card bottleneckHeroCard">
      <div className="bottleneckHeroHeader">
        <div className="heroBadge">Coordination Analysis</div>
        <div className="heroModelTag">Model: {bottleneck.model_name || 'Random Forest'}</div>
      </div>
      
      <div className="bottleneckHeroBody">
        <div className={`bottleneckHeroCircle ${statusClass}`}>
          <div className="heroProbNumber">{probPercent}%</div>
          <div className="heroProbLabel">Risk Score</div>
        </div>

        <div className="bottleneckHeroInfo">
          <div className="bottleneckHeroTitle">Coordination Bottleneck Risk</div>
          <div className="bottleneckHeroDesc">
            Evaluates the likelihood of cross-change review blocking, excessive in-degree dependencies, and queuing delays across all changes in this blueprint.
          </div>
          
          <div className="bottleneckHeroStatusRow">
            <span className={`bottleneckPill ${statusClass}`}>
              <span className="pillDot"></span>
              {bottleneck.status || 'Analysis Ready'}
            </span>
            {bottleneck.prediction !== undefined && (
              <span className="bottleneckFlag">
                {bottleneck.prediction ? '⚠️ Elevated Coordination Risk Detected' : '✓ Standard Coordination Flow'}
              </span>
            )}
          </div>

          {breakdown.total_changes !== undefined && (
            <div className="bottleneckBreakdownRow">
              <div className="breakdownItem">
                <span className="breakdownLabel">Changes Tracked:</span>
                <span className="breakdownVal">{breakdown.total_changes}</span>
              </div>
              <div className="breakdownItem">
                <span className="breakdownLabel">High In-Degree Changes:</span>
                <span className="breakdownVal risky">{breakdown.risky_changes || 0}</span>
              </div>
              <div className="breakdownItem">
                <span className="breakdownLabel">Max Change Probability:</span>
                <span className="breakdownVal">{Math.round((breakdown.max_probability || 0) * 100)}%</span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function BottleneckDashboard() {
  const [blueprintId, setBlueprintId] = useState("");
  const [blueprint, setBlueprint] = useState(null);
  const [bottleneck, setBottleneck] = useState(null);
  const [graphData, setGraphData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!blueprintId) return;

    setLoading(true);
    setError("");
    setBlueprint(null);
    setBottleneck(null);
    setGraphData(null);

    const parts = blueprintId.split('::');
    if (parts.length < 2) {
      setError("Invalid blueprint identifier");
      setLoading(false);
      return;
    }
    const [project, name] = parts;
    const encodedProject = encodeURIComponent(project);
    const encodedName = encodeURIComponent(name);
    
    Promise.all([
      fetch(`http://localhost:3001/api/blueprints/${encodedProject}/${encodedName}/bottleneck`).then(async r => {
        if (!r.ok) {
          const body = await r.json().catch(() => ({}));
          throw new Error(body.error || `Failed to load bottleneck data (${r.status})`);
        }
        return r.json();
      }),
      fetch(`http://localhost:3001/api/blueprints/${encodedProject}/${encodedName}/graph`).then(async r => {
        if (!r.ok) {
          const body = await r.json().catch(() => ({}));
          throw new Error(body.error || `Failed to load graph data (${r.status})`);
        }
        return r.json();
      })
    ]).then(([bottleneckRes, graphRes]) => {
      setBlueprint(bottleneckRes.blueprint);
      setBottleneck(bottleneckRes.bottleneck);
      setGraphData(graphRes);
      setLoading(false);
    }).catch(err => {
      console.error(err);
      setError(err.message);
      setLoading(false);
    });
  }, [blueprintId]);

  return (
    <div className="bottleneckDashboardContainer">
      {/* 1. Select Blueprint */}
      <BlueprintSelector onSelect={setBlueprintId} selectedId={blueprintId} />
      
      {loading && (
        <div className="loadingStateCard">
          <div className="loadingSpinner"></div>
          <div>Analyzing coordination bottlenecks and dependency structures...</div>
        </div>
      )}
      {error && <div className="errorBanner">{error}</div>}

      {blueprint && bottleneck && graphData && !loading && (
        <div className="bottleneckStackLayout">
          {/* 2. Summary Cards */}
          <div className="statsRow">
            <StatCard label="Total Changes" value={graphData.total_changes || (graphData.nodes || []).length} icon="🔄" />
            <StatCard label="Dependencies" value={(graphData.edges || []).length} icon="🔗" />
            <StatCard label="Isolated Changes" value={graphData.isolated_changes || 0} icon="📦" />
            <StatCard label="Risk Level" value={bottleneck.status || 'Low Risk'} icon="⚠️" />
          </div>
          
          {/* 3. Coordination Bottleneck Risk (Hero Centerpiece) */}
          <BottleneckPredictionCard bottleneck={bottleneck} />

          {/* 4. Dependency Structure (Full-Width Large Graph Card) */}
          <DependencyGraph graphData={graphData} />

          {/* 5. Graph Metrics (3-Column Grid) */}
          <GraphMetrics graphData={graphData} />
        </div>
      )}
    </div>
  );
}

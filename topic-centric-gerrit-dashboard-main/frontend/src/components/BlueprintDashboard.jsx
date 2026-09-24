import { useEffect, useState } from "react";
import BlueprintSelector from "./BlueprintSelector";
import BlueprintInfoCard from "./BlueprintInfoCard";
import PredictionCard from "./PredictionCard";
import PredictionDetail from "./PredictionDetail";
import OverallRiskSummary from "./OverallRiskSummary";
import BlueprintChatbot from "./BlueprintChatbot";

const PREDICTION_KEYS = [
  { key: 'review_delay', title: 'Review Delay' },
  { key: 'stall_abandonment', title: 'Stall & Abandonment' },
  { key: 'excessive_rework', title: 'Excessive Rework' },
  { key: 'high_review_effort', title: 'High Review Effort' }
];

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

export default function BlueprintDashboard() {
  const [blueprintId, setBlueprintId] = useState("");
  const [blueprint, setBlueprint] = useState(null);
  const [predictions, setPredictions] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selectedPrediction, setSelectedPrediction] = useState(null);

  useEffect(() => {
    if (!blueprintId) return;

    setLoading(true);
    setError("");
    setBlueprint(null);
    setPredictions(null);
    setSelectedPrediction(null);

    const parts = blueprintId.split('::');
    if (parts.length < 2) return;
    const [project, name] = parts;

    fetch(`http://localhost:3001/api/blueprints/${encodeURIComponent(project)}/${encodeURIComponent(name)}/predictions`)
      .then((res) => {
        if (!res.ok) throw new Error("Failed to load blueprint predictions");
        return res.json();
      })
      .then((data) => {
        setBlueprint(data.blueprint);
        setPredictions(data.predictions);
        setLoading(false);
      })
      .catch((err) => {
        console.error(err);
        setError(err.message);
        setLoading(false);
      });
  }, [blueprintId]);

  return (
    <div className="blueprintDashboardContainer">
      <BlueprintSelector onSelect={setBlueprintId} selectedId={blueprintId} />
      
      {loading && (
        <div className="loadingStateCard">
          <div className="loadingSpinner"></div>
          <div>Loading blueprint predictions and specifications...</div>
        </div>
      )}
      {error && <div className="errorBanner">{error}</div>}

      {blueprint && predictions && !loading && (
        <>
          {/* Summary KPI Cards Row */}
          <div className="statsRow" style={{ marginTop: "20px" }}>
            <StatCard label="Topics" value={blueprint.n_topics} icon="📁" />
            <StatCard label="Changes" value={blueprint.n_changes} icon="🔄" />
            <StatCard label="Priority" value={blueprint.priority} icon="⭐" />
            <StatCard label="Spec Words" value={blueprint.spec_word_count} icon="📝" />
          </div>
          
          {/* Main Content: Left Column (Overview, Risks, Details) + Right Column (AI Assistant) */}
          <div className="blueprintSplitLayout">
            <div className="blueprintMainColumn">
              <BlueprintInfoCard blueprint={blueprint} />
              <OverallRiskSummary predictions={predictions} />
              
              <div className="sectionTitle" style={{ marginTop: "24px", marginBottom: "14px" }}>
                Hardness Risk Predictions
              </div>
              <div className="predictionsGrid">
                {PREDICTION_KEYS.map(({ key, title }) => {
                  const p = predictions[key];
                  if (!p) return null;
                  const isSelected = selectedPrediction && selectedPrediction.key === key;
                  return (
                    <PredictionCard
                      key={key}
                      title={title}
                      prediction={p.prediction}
                      probability={p.probability}
                      status={p.status}
                      modelName={p.model_name}
                      isSelected={isSelected}
                      onClick={() => {
                        if (isSelected) {
                          setSelectedPrediction(null);
                        } else {
                          setSelectedPrediction({ title, key, ...p });
                        }
                      }}
                    />
                  );
                })}
              </div>

              {/* Selected Prediction Detail Panel in Main Column */}
              {selectedPrediction && (
                <div style={{ marginTop: "20px" }}>
                  <PredictionDetail
                    title={selectedPrediction.title}
                    prediction={selectedPrediction.prediction}
                    probability={selectedPrediction.probability}
                    status={selectedPrediction.status}
                    modelName={selectedPrediction.model_name}
                    topFeatures={selectedPrediction.top_features}
                    onClose={() => setSelectedPrediction(null)}
                  />
                </div>
              )}
            </div>
            
            {/* Right Column: AI Assistant (ChatGPT Layout) */}
            <div className="blueprintChatColumn">
              <div className="stickyChatWrapper">
                <BlueprintChatbot 
                  blueprintId={blueprintId} 
                  blueprintData={blueprint} 
                  predictions={predictions} 
                />
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

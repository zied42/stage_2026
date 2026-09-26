export default function PredictionCard({ title, prediction, probability, status, modelName, onClick, isSelected }) {
  const riskClass = status === 'High Risk' ? 'riskHigh' : status === 'Medium Risk' ? 'riskMedium' : 'riskLow';
  const probPercent = Math.round(probability * 100);

  return (
    <div className={`card predictionCard ${riskClass} ${isSelected ? 'predictionCardSelected' : ''}`} onClick={onClick}>
      <div className="sectionHeader" style={{ marginBottom: "0" }}>
        <div className="sectionTitle" style={{ fontSize: "15px" }}>{title}</div>
      </div>
      <div style={{ marginTop: "12px" }}>
        <div className="riskBadge">{status}</div>
      </div>
      <div className="probValue">{probPercent}%</div>
      <div className="muted" style={{ fontSize: "11px" }}>Model: {modelName}</div>
      <div className="riskBar" style={{ width: `${probPercent}%` }}></div>
      {isSelected && (
        <div className="selectedIndicator">Active Detail ▲</div>
      )}
    </div>
  );
}

export default function PredictionDetail({ title, prediction, probability, status, modelName, topFeatures, onClose }) {
  const probPercent = Math.round(probability * 100);
  const riskClass = status === 'High Risk' ? 'riskHigh' : status === 'Medium Risk' ? 'riskMedium' : 'riskLow';

  return (
    <div className={`card predictionDetail ${riskClass}`}>
      <button className="closeBtn" onClick={onClose}>×</button>
      <div className="sectionHeader">
        <div>
          <div className="sectionTitle">{title} Detail</div>
          <div className="sectionSubtitle">Model: {modelName}</div>
        </div>
      </div>

      <div className="detailGrid">
        <div className="miniStat">
          <div className="miniLabel">Risk Status</div>
          <div className="miniValue" style={{fontSize: "18px"}}>{status}</div>
        </div>
        <div className="miniStat">
          <div className="miniLabel">Probability</div>
          <div className="miniValue" style={{fontSize: "18px"}}>{probPercent}%</div>
        </div>
      </div>

      {topFeatures && topFeatures.length > 0 && (
        <div style={{marginTop: "16px"}}>
          <div className="sectionSubtitle bold">Top Contributing Features</div>
          <ul className="featureList">
            {topFeatures.map((f, i) => (
              <li className="featureItem" key={i}>
                <div style={{width: "100%"}}>
                  <div style={{display: "flex", justifyContent: "space-between"}}>
                    <span className="mono">{f.name}</span>
                    <span>{f.importance.toFixed(3)}</span>
                  </div>
                  <div className="featureBar" style={{width: `${Math.min(100, f.importance * 1000)}%`}}></div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

import React from 'react';

export default function OverallRiskSummary({ predictions }) {
  if (!predictions) return null;

  const validPredictions = Object.values(predictions).filter(p => p && p.prediction !== undefined);
  const totalTasks = validPredictions.length || 4;
  const activeRisks = validPredictions.filter(p => p.prediction === true).length;
  
  let riskLevel = 'LOW';
  let circleClass = 'low';
  
  if (activeRisks >= 3) {
    riskLevel = 'HIGH';
    circleClass = 'high';
  } else if (activeRisks >= 1) {
    riskLevel = 'MEDIUM';
    circleClass = 'medium';
  }

  return (
    <div className="card overallRisk">
      <div className={`riskCircle ${circleClass}`}>
        {activeRisks}/{totalTasks}
      </div>
      <div className="riskLabel">Overall Blueprint Risk: <span className={`riskText-${circleClass}`}>{riskLevel}</span></div>
      <div className="riskDesc">{activeRisks} of {totalTasks} development hardness tasks indicate elevated risk</div>
    </div>
  );
}

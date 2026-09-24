export default function VelocityCard({ metrics }) {
  const dash = "—";

  const reviewMetrics = [
    { label: "Median Review Duration", value: dash },
    { label: "Median Time to First Review", value: dash },
    { label: "Merges Per Day", value: dash },
    { label: "Open Changes", value: metrics?.openChanges ?? 0 },
  ];

  const buildTotal = metrics?.buildTotal ?? 0;
  const buildSuccess = metrics?.buildSuccess ?? 0;
  const buildFailure = metrics?.buildFailure ?? 0;
  const avgJobTime = metrics?.avgJobTime ?? null;

  // If later you store avgJobTime in seconds, you can format it here.
  const avgJobTimeDisplay = avgJobTime == null ? dash : String(avgJobTime);

  return (
    <>
      {/* Velocity card */}
      <div className="card">
        <div className="sectionHeader">
          <div>
            <div className="sectionTitle">Velocity</div>
            <div className="sectionSubtitle">Review activity and throughput</div>
          </div>
        </div>

        <div className="velocitySection">
          <div className="velocitySectionTitle">Review Metrics</div>

          <div className="velocity-list">
            {reviewMetrics.map((row) => (
              <div className="velocity-row" key={row.label}>
                <div className="velocity-label">{row.label}</div>
                <div className="velocity-value">{row.value}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Builds card (separate card under Velocity) */}
      <div className="card">
        <div className="sectionHeader">
          <div>
            <div className="sectionTitle">Builds</div>
            <div className="sectionSubtitle">CI outcomes for this topic</div>
          </div>

          <div className="muted">Total: {buildTotal}</div>
        </div>

        <div className="buildGrid">
          <div className="buildBox">
            <div className="buildLabel">Success</div>
            <div className="buildValue">{buildSuccess}</div>
          </div>

          <div className="buildBox">
            <div className="buildLabel">Failures</div>
            <div className="buildValue">{buildFailure}</div>
          </div>

          <div className="buildBox">
            <div className="buildLabel">Avg Job Time</div>
            <div className="buildValue">{avgJobTimeDisplay}</div>
          </div>
        </div>
      </div>
    </>
  );
}
export default function BuildsCard({ builds }) {
  const total = builds?.total ?? 0;
  const success = builds?.success ?? 0;
  const failures = builds?.failures ?? 0;
  const avgJobTime = builds?.avgJobTime ?? "—";

  return (
    <div className="card">
      <div className="sectionHeader">
        <div>
          <div className="sectionTitle">Builds</div>
          <div className="sectionSubtitle">CI outcomes for this topic</div>
        </div>
        <div className="muted">Total: {total}</div>
      </div>

      <div className="buildGrid">
        <div className="buildBox">
          <div className="buildLabel">Success</div>
          <div className="buildValue">{success}</div>
        </div>

        <div className="buildBox">
          <div className="buildLabel">Failures</div>
          <div className="buildValue">{failures}</div>
        </div>

        <div className="buildBox">
          <div className="buildLabel">Avg Job Time</div>
          <div className="buildValue">{avgJobTime}</div>
        </div>
      </div>
    </div>
  );
}
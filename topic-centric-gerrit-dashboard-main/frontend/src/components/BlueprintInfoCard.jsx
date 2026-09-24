export default function BlueprintInfoCard({ blueprint }) {
  if (!blueprint) return null;

  return (
    <div className="card">
      <div className="sectionHeader">
        <div>
          <div className="sectionTitle">Blueprint Overview</div>
          <div className="sectionSubtitle">{blueprint.title}</div>
        </div>
      </div>

      <div className="overviewGrid">
        <div className="miniStat">
          <div className="miniLabel">Project</div>
          <div className="miniValue mono" style={{fontSize: "14px"}}>{blueprint.project}</div>
        </div>
        <div className="miniStat">
          <div className="miniLabel">Priority</div>
          <div className="miniValue">{blueprint.priority}</div>
        </div>
        <div className="miniStat">
          <div className="miniLabel">Definition</div>
          <div className="miniValue">{blueprint.definition_status}</div>
        </div>
        <div className="miniStat">
          <div className="miniLabel">Implementation</div>
          <div className="miniValue">{blueprint.implementation_status}</div>
        </div>
        <div className="miniStat">
          <div className="miniLabel">Topics</div>
          <div className="miniValue">{blueprint.n_topics}</div>
        </div>
        <div className="miniStat">
          <div className="miniLabel">Changes</div>
          <div className="miniValue">{blueprint.n_changes}</div>
        </div>
      </div>
    </div>
  );
}

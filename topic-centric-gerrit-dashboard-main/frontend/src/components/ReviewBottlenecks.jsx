export default function ReviewBottlenecks({ changes }) {
  const now = new Date();

  const openChanges = changes.filter((c) => c.status === "NEW");

  const ages = openChanges.map((c) => {
    const created = new Date(c.created);
    const diffDays = Math.floor((now - created) / (1000 * 60 * 60 * 24));
    return diffDays;
  });

  const oldestOpen = ages.length ? Math.max(...ages) : 0;
  const staleChanges = ages.filter((d) => d > 14).length;

  const highCommentChanges = changes.filter(
    (c) => (c.total_comment_count || 0) > 5
  ).length;

  const unresolvedComments = changes.reduce(
    (sum, c) => sum + (c.unresolved_comment_count || 0),
    0
  );

  return (
    <div className="card">
      <div className="sectionHeader">
        <div>
          <div className="sectionTitle">Review Bottlenecks</div>
          <div className="sectionSubtitle">
            Identify delays in the review process
          </div>
        </div>
      </div>

      <div className="overviewGrid">

        <div className="miniStat">
          <div className="miniLabel">Oldest Open</div>
          <div className="miniValue">{oldestOpen}d</div>
        </div>

        <div className="miniStat">
          <div className="miniLabel">Stale Changes</div>
          <div className="miniValue">{staleChanges}</div>
        </div>

        <div className="miniStat">
          <div className="miniLabel">High Comment</div>
          <div className="miniValue">{highCommentChanges}</div>
        </div>

        <div className="miniStat">
          <div className="miniLabel">Unresolved</div>
          <div className="miniValue">{unresolvedComments}</div>
        </div>

      </div>
    </div>
  );
}
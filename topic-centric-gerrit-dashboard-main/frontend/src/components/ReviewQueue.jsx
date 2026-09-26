import { useMemo } from "react";

export default function ReviewQueue({ changes = [] }) {
  const items = useMemo(() => {
    const now = Date.now();

    return changes
      .filter((c) => c.status === "NEW")
      .map((c) => {
        const createdMs = c.created ? new Date(c.created).getTime() : now;
        const ageDays = Math.max(
          0,
          Math.floor((now - createdMs) / (1000 * 60 * 60 * 24))
        );

        return {
          id: c._number ? `#${c._number}` : `#${c.id}`,
          subject: c.subject || "—",
          repo: c.project || "—",
          ageDays,
        };
      })
      .sort((a, b) => b.ageDays - a.ageDays)
      .slice(0, 6);
  }, [changes]);

  return (
    <div className="card">
      <div className="sectionHeader">
        <div>
          <div className="sectionTitle">Review Queue</div>
          <div className="sectionSubtitle">Oldest open changes first</div>
        </div>
        <div className="muted">{items.length} items</div>
      </div>

      {items.length === 0 ? (
        <div className="muted">No open changes 🎉</div>
      ) : (
        <div className="queueList">
          {items.map((it, idx) => (
            <div className="queueRow" key={idx}>
              <div className="queueTop">
                <span className="link">{it.id}</span>
                <span className="queueAge">{it.ageDays}d</span>
              </div>
              <div className="queueSubject">{it.subject}</div>
              <div className="muted mono">{it.repo}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
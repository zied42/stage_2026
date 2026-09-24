const changes = [
  {
    id: "#54312",
    subject: "Add core authentication library with OAuth2 support",
    repo: "auth-core",
    status: "Merged",
    revisions: 5,
    ci: "ok",
    start: "2026-01-09",
    end: "2026-01-12",
  },
  {
    id: "#54315",
    subject: "Implement Google and GitHub OAuth2 providers",
    repo: "auth-providers",
    status: "Merged",
    revisions: 3,
    ci: "ok",
    start: "2026-01-11",
    end: "2026-01-14",
  },
  {
    id: "#54318",
    subject: "Create session management service with Redis",
    repo: "session-service",
    status: "Review",
    revisions: 7,
    ci: "pending",
    start: "2026-01-13",
    end: null,
  },
];

function StatusBadge({ status }) {
  const map = {
    Merged: { bg: "#DCFCE7", fg: "#166534" },
    Review: { bg: "#FEF3C7", fg: "#92400E" },
    Open: { bg: "#E0E7FF", fg: "#3730A3" },
    Abandoned: { bg: "#FEE2E2", fg: "#991B1B" },
  };
  const s = map[status] ?? { bg: "#E5E7EB", fg: "#374151" };

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        padding: "4px 10px",
        borderRadius: 999,
        fontSize: 12,
        fontWeight: 700,
        background: s.bg,
        color: s.fg,
      }}
    >
      {status}
    </span>
  );
}

function CiIcon({ ci }) {
  if (ci === "ok") return <span title="CI passed">✅</span>;
  if (ci === "fail") return <span title="CI failed">❌</span>;
  return <span title="CI pending">⏳</span>;
}

export default function ChangesTable() {
  return (
    <section style={styles.section}>
      <div style={styles.card}>
        <div style={styles.header}>
          <h2 style={styles.title}>Changes & Timeline</h2>
          <div style={styles.count}>{changes.length} changes</div>
        </div>

        <div style={styles.tableWrap}>
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>Change ID</th>
                <th style={styles.th}>Subject</th>
                <th style={styles.th}>Repository</th>
                <th style={styles.th}>Status</th>
                <th style={styles.thRight}>Revisions</th>
                <th style={styles.thCenter}>CI</th>
                <th style={styles.th}>Timeline</th>
              </tr>
            </thead>

            <tbody>
              {changes.map((c) => (
                <tr key={c.id} style={styles.tr}>
                  <td style={styles.td}>
                    <span style={styles.link}>{c.id}</span>
                  </td>
                  <td style={styles.td}>{c.subject}</td>
                  <td style={styles.tdMono}>{c.repo}</td>
                  <td style={styles.td}>
                    <StatusBadge status={c.status} />
                  </td>
                  <td style={styles.tdRight}>{c.revisions}</td>
                  <td style={styles.tdCenter}>
                    <CiIcon ci={c.ci} />
                  </td>
                  <td style={styles.tdSmall}>
                    {c.start} → {c.end ?? "In progress"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

const styles = {
  section: {
    maxWidth: 1200,
    margin: "18px auto 28px",
    padding: "0 24px",
  },
  card: {
    background: "#fff",
    border: "1px solid #E5E7EB",
    borderRadius: 14,
    boxShadow: "0 1px 2px rgba(0,0,0,0.05)",
    overflow: "hidden",
  },
  header: {
    display: "flex",
    alignItems: "baseline",
    justifyContent: "space-between",
    padding: "16px 18px",
    borderBottom: "1px solid #E5E7EB",
    background: "#fff",
  },
  title: { margin: 0, fontSize: 18, fontWeight: 800, color: "#111827" },
  count: { fontSize: 12, color: "#6B7280", fontWeight: 600 },

  tableWrap: { width: "100%", overflowX: "auto" },
  table: { width: "100%", borderCollapse: "separate", borderSpacing: 0, fontSize: 13 },

  th: {
    textAlign: "left",
    padding: "12px 18px",
    fontSize: 12,
    color: "#6B7280",
    fontWeight: 800,
    background: "#F9FAFB",
    borderBottom: "1px solid #E5E7EB",
    whiteSpace: "nowrap",
  },
  thRight: {
    textAlign: "right",
    padding: "12px 18px",
    fontSize: 12,
    color: "#6B7280",
    fontWeight: 800,
    background: "#F9FAFB",
    borderBottom: "1px solid #E5E7EB",
    whiteSpace: "nowrap",
  },
  thCenter: {
    textAlign: "center",
    padding: "12px 18px",
    fontSize: 12,
    color: "#6B7280",
    fontWeight: 800,
    background: "#F9FAFB",
    borderBottom: "1px solid #E5E7EB",
    whiteSpace: "nowrap",
  },

  tr: {},
  td: {
    padding: "14px 18px",
    borderBottom: "1px solid #F1F5F9",
    verticalAlign: "middle",
  },
  tdRight: {
    padding: "14px 18px",
    borderBottom: "1px solid #F1F5F9",
    textAlign: "right",
    fontWeight: 700,
  },
  tdCenter: {
    padding: "14px 18px",
    borderBottom: "1px solid #F1F5F9",
    textAlign: "center",
  },
  tdSmall: {
    padding: "14px 18px",
    borderBottom: "1px solid #F1F5F9",
    fontSize: 12,
    color: "#374151",
    whiteSpace: "nowrap",
  },
  tdMono: {
    padding: "14px 18px",
    borderBottom: "1px solid #F1F5F9",
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
    fontSize: 12,
    color: "#374151",
  },

  link: { color: "#2563EB", fontWeight: 800, cursor: "pointer" },
};
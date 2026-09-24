function Stat({ label, value }) {
  return (
    <div style={styles.stat}>
      <div style={styles.statLabel}>{label}</div>
      <div style={styles.statValue}>{value}</div>
    </div>
  );
}

export default function TopicOverviewCard() {
  return (
    <div style={styles.card}>
      <div style={styles.header}>
        <h2 style={styles.title}>Topic Overview</h2>
      </div>

      <div style={styles.topicRow}>
        <div style={styles.topicLabel}>Topic Name</div>
        <div style={styles.topicName}>feature/user-authentication-v2</div>
      </div>

      <div style={styles.grid}>
        <Stat label="Changes" value="12" />
        <Stat label="Repositories" value="3" />
        <Stat label="Branches" value="2" />
        <Stat label="Time Span" value="14 days" />
        <Stat label="Total Revisions" value="48" />
        <Stat label="Discussion Comments" value="156" />
        <Stat label="CI Jobs" value="384" />
      </div>

      <div style={styles.divider} />

      <div style={styles.aiHeader}>
        <h3 style={styles.aiTitle}>Topic Summary (AI)</h3>
        <button style={styles.btn}>Generate</button>
      </div>

      <div style={styles.aiBox}>
        <div style={styles.aiSection}>
          <div style={styles.aiSectionTitle}>GOAL</div>
          <div style={styles.aiText}>
            Implements authentication v2 with OAuth2, MFA, and improved session management.
          </div>
        </div>

        <div style={styles.aiRow}>
          <div style={styles.aiCol}>
            <div style={styles.aiSectionTitle}>KEY CHANGES</div>
            <ul style={styles.list}>
              <li>OAuth2 (Google, GitHub)</li>
              <li>Multi-factor auth (TOTP/SMS)</li>
              <li>Redis session service</li>
              <li>Security preferences schema</li>
              <li>v2 API migration</li>
            </ul>
          </div>

          <div style={styles.aiCol}>
            <div style={styles.aiSectionTitle}>BLOCKERS</div>
            <ul style={styles.list}>
              <li>#54321: Redis cluster approval pending</li>
              <li>Security audit required</li>
              <li>DBA review needed</li>
            </ul>
          </div>

          <div style={styles.aiCol}>
            <div style={styles.aiSectionTitle}>READ ORDER</div>
            <div style={styles.aiText}>
              #54312 → #54315 → #54318 → API changes
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

const styles = {
  card: {
    background: "#fff",
    border: "1px solid #E5E7EB",
    borderRadius: 14,
    padding: 18,
    boxShadow: "0 1px 2px rgba(0,0,0,0.05)",
  },
  header: { marginBottom: 10 },
  title: { margin: 0, fontSize: 18, fontWeight: 700, color: "#111827" },

  topicRow: { marginBottom: 14 },
  topicLabel: { fontSize: 12, color: "#6B7280", marginBottom: 4 },
  topicName: { fontSize: 14, fontWeight: 600, color: "#2563EB" },

  grid: {
    display: "grid",
    gridTemplateColumns: "repeat(2, 1fr)",
    gap: 12,
  },
  stat: {
    border: "1px solid #F1F5F9",
    background: "#FBFDFF",
    borderRadius: 12,
    padding: 12,
  },
  statLabel: { fontSize: 12, color: "#6B7280" },
  statValue: { fontSize: 18, fontWeight: 700, marginTop: 4 },

  divider: {
    height: 1,
    background: "#E5E7EB",
    margin: "16px 0",
  },

  aiHeader: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
    marginBottom: 10,
  },
  aiTitle: { margin: 0, fontSize: 14, fontWeight: 700 },
  btn: {
    border: "1px solid #E5E7EB",
    background: "#2563EB",
    color: "#fff",
    borderRadius: 10,
    padding: "8px 12px",
    fontWeight: 600,
    cursor: "pointer",
  },

  aiBox: {
    border: "1px solid #F1F5F9",
    borderRadius: 12,
    padding: 14,
    background: "#FBFDFF",
  },
  aiSection: { marginBottom: 10 },
  aiSectionTitle: { fontSize: 11, fontWeight: 700, color: "#6B7280", letterSpacing: "0.04em" },
  aiText: { fontSize: 13, color: "#111827", marginTop: 6 },

  aiRow: {
    display: "grid",
    gridTemplateColumns: "repeat(3, 1fr)",
    gap: 14,
    marginTop: 8,
  },
  aiCol: { fontSize: 13 },
  list: { margin: "8px 0 0 16px", padding: 0, color: "#111827", fontSize: 13 },
};
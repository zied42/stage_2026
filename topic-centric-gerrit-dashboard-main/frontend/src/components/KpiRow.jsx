function KpiCard({ label, value }) {
  return (
    <div style={styles.card}>
      <div style={styles.label}>{label}</div>
      <div style={styles.value}>{value}</div>
    </div>
  );
}

export default function KpiRow() {
  return (
    <div style={styles.row}>
      <KpiCard label="Review Velocity" value="+23%" />
      <KpiCard label="Active Reviewers" value="8" />
      <KpiCard label="Avg CI Time" value="4.2m" />
      <KpiCard label="Merge Rate" value="75%" />
    </div>
  );
}

const styles = {
  row: {
    maxWidth: 1200,
    margin: "18px auto 0",
    padding: "0 24px",
    display: "grid",
    gridTemplateColumns: "repeat(4, 1fr)",
    gap: 16,
  },
  card: {
    background: "#fff",
    border: "1px solid #E5E7EB",
    borderRadius: 14,
    padding: 16,
    boxShadow: "0 1px 2px rgba(0,0,0,0.05)",
  },
  label: {
    fontSize: 14,
    color: "#6B7280",
    marginBottom: 8,
  },
  value: {
    fontSize: 28,
    fontWeight: 700,
    color: "#111827",
  },
};
const contributors = [
  { initials: "SC", name: "Sarah Chen", stats: "24 reviews • 8 merges", total: 32 },
  { initials: "JD", name: "John Doe", stats: "18 reviews • 12 merges", total: 30 },
  { initials: "MW", name: "Mike Wilson", stats: "15 reviews • 5 merges", total: 20 },
  { initials: "ED", name: "Emily Davis", stats: "12 reviews • 7 merges", total: 19 },
  { initials: "AK", name: "Alex Kumar", stats: "9 reviews • 3 merges", total: 12 },
];

function Avatar({ initials }) {
  return <div style={styles.avatar}>{initials}</div>;
}

export default function TopContributorsCard() {
  return (
    <div style={styles.card}>
      <h2 style={styles.title}>Top Contributors</h2>

      <div style={styles.list}>
        {contributors.map((c) => (
          <div key={c.name} style={styles.row}>
            <Avatar initials={c.initials} />

            <div style={styles.mid}>
              <div style={styles.name}>{c.name}</div>
              <div style={styles.stats}>{c.stats}</div>
            </div>

            <div style={styles.total}>
              <div style={styles.totalNum}>{c.total}</div>
              <div style={styles.totalLbl}>total</div>
            </div>
          </div>
        ))}
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
  title: {
    margin: 0,
    fontSize: 16,
    fontWeight: 800,
    color: "#111827",
    marginBottom: 12,
  },
  list: { display: "flex", flexDirection: "column", gap: 12 },
  row: {
    display: "flex",
    alignItems: "center",
    gap: 12,
    padding: 12,
    borderRadius: 12,
    border: "1px solid #EEF2F7",
    background: "#fff",
  },
  avatar: {
    width: 36,
    height: 36,
    borderRadius: 999,
    background: "#E0E7FF",
    color: "#3730A3",
    fontWeight: 900,
    display: "grid",
    placeItems: "center",
    fontSize: 12,
  },
  mid: { flex: 1 },
  name: { fontSize: 13, fontWeight: 800, color: "#111827" },
  stats: { marginTop: 2, fontSize: 12, color: "#6B7280" },
  total: { textAlign: "right" },
  totalNum: { fontSize: 14, fontWeight: 900, color: "#111827" },
  totalLbl: { fontSize: 11, color: "#6B7280" },
};
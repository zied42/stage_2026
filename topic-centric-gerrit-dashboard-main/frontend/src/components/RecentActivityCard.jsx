const activity = [
  { who: "Sarah Chen", action: "commented on", id: "#54323", time: "5m ago", icon: "💬" },
  { who: "John Doe", action: "merged", id: "#54330", time: "12m ago", icon: "✅" },
  { who: "Mike Wilson", action: "reviewed", id: "#54318", time: "18m ago", icon: "🧑‍⚖️" },
  { who: "CI Bot", action: "CI failed on", id: "#54325", time: "25m ago", icon: "❌" },
  { who: "Emily Davis", action: "commented on", id: "#54321", time: "32m ago", icon: "💬" },
  
  // duplicate some for testing
  { who: "Alex Kumar", action: "reviewed", id: "#54350", time: "40m ago", icon: "🧑‍⚖️" },
  { who: "Sara Lee", action: "merged", id: "#54355", time: "1h ago", icon: "✅" },
  { who: "David Kim", action: "commented on", id: "#54360", time: "2h ago", icon: "💬" },
  { who: "Backend Bot", action: "CI passed on", id: "#54365", time: "3h ago", icon: "✅" },
  { who: "Frontend Bot", action: "CI failed on", id: "#54370", time: "4h ago", icon: "❌" },
  { who: "Negin", action: "merged", id: "#54375", time: "5h ago" },
];

export default function RecentActivityCard() {
  return (
    <div style={styles.card}>
      <h2 style={styles.title}>Recent Activity</h2>

      <div style={styles.list}>
        {activity.map((a, idx) => (
          <div key={idx} style={styles.item}>
            <div style={styles.icon}>{a.icon}</div>

            <div style={styles.text}>
              <div style={styles.line}>
                <span style={styles.name}>{a.who}</span>{" "}
                <span style={styles.muted}>{a.action}</span>{" "}
                <span style={styles.link}>{a.id}</span>
              </div>
              <div style={styles.time}>{a.time}</div>
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
  list: {
    display: "flex",
    flexDirection: "column",
    gap: 12,
  },
  item: {
    display: "flex",
    gap: 12,
    padding: 12,
    borderRadius: 12,
    border: "1px solid #EEF2F7",
    background: "#fff",
  },
  icon: {
    width: 32,
    height: 32,
    borderRadius: 10,
    display: "grid",
    placeItems: "center",
    background: "#F3F4F6",
    fontSize: 16,
  },
  text: { flex: 1 },
  line: { fontSize: 13, color: "#111827" },
  name: { fontWeight: 800 },
  muted: { color: "#6B7280" },
  link: { color: "#2563EB", fontWeight: 800, cursor: "pointer" },
  time: { marginTop: 4, fontSize: 12, color: "#6B7280" },
};
export default function TopBar() {
  return (
    <header style={styles.header}>
      <div style={styles.inner}>
        <h1 style={styles.title}>Topic-Centric Gerrit Dashboard</h1>

        <div style={styles.searchBox}>
          <span style={styles.icon}>🔍</span>
          <input
            type="text"
            placeholder="Enter Gerrit topic name..."
            style={styles.searchInput}
          />
        </div>
      </div>
    </header>
  );
}

const styles = {
  header: {
    background: "#fff",
    borderBottom: "1px solid #E5E7EB",
  },
  inner: {
    maxWidth: 1200,
    margin: "0 auto",
    padding: "28px 24px",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 16,
  },
  title: {
    margin: 0,
    fontSize: 28,
    fontWeight: 700,
    color: "#111827",
  },
  searchBox: {
    width: 520,
    maxWidth: "55vw",
    display: "flex",
    alignItems: "center",
    gap: 10,
    padding: "12px 14px",
    borderRadius: 14,
    border: "1px solid #E5E7EB",
    background: "#fff",
    boxShadow: "0 1px 2px rgba(0,0,0,0.05)",
  },
  icon: {
    opacity: 0.6,
  },
  searchInput: {
    width: "100%",
    border: "none",
    outline: "none",
    fontSize: 16,
    background: "transparent",
    color: "#111827",
  },
};
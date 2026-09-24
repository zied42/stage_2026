import RecentActivityCard from "./RecentActivityCard";
import TopContributorsCard from "./TopContributorsCard";

export default function RightSidebar() {
  return (
    <div style={styles.stack}>
      <RecentActivityCard />
      <TopContributorsCard />
    </div>
  );
}

const styles = {
  stack: {
    display: "flex",
    flexDirection: "column",
    gap: 16,
  },
};
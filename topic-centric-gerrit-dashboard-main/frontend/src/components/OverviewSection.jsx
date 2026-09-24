import TopicOverviewCard from "./TopicOverviewCard";
import VelocityCard from "./VelocityCard";
import RightSidebar from "./RightSidebar";

export default function OverviewSection() {
  return (
    <div style={styles.wrapper}>
      <TopicOverviewCard />

      <div style={styles.rightCol}>
        <VelocityCard />
        <RightSidebar />
      </div>
    </div>
  );
}

const styles = {
  wrapper: {
    maxWidth: 1200,
    margin: "18px auto 0",
    padding: "0 24px",
    display: "grid",
    gridTemplateColumns: "2fr 1fr",
    gap: 16,
    alignItems: "start",
  },
  rightCol: {
    display: "flex",
    flexDirection: "column",
    gap: 16,
  },
};
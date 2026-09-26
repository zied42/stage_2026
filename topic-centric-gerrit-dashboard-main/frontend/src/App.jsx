import { useEffect, useState } from "react";
import "./App.css";
import ChartsGrid from "./components/ChartsGrid";
import ReviewQueue from "./components/ReviewQueue";
import ReviewBottlenecks from "./components/ReviewBottlenecks";
import BuildsCard from "./components/BuildsCard";
import TopicSummaryCard from "./components/TopicSummaryCard";
import BlueprintDashboard from "./components/BlueprintDashboard";
import BottleneckDashboard from "./components/BottleneckDashboard";

function StatCard({ label, value, icon }) {
  return (
    <div className="statCard">
      <div className="statText">
        <div className="statLabel">{label}</div>
        <div className="statValue">{value}</div>
      </div>
      <div className="statIcon">{icon}</div>
    </div>
  );
}

function TopicOverviewCard({ topic, metrics }) {
  return (
    <div className="card">
      <div className="sectionHeader">
        <div>
          <div className="sectionTitle">Topic Overview</div>
          <div className="sectionSubtitle">Summary and repository metrics</div>
        </div>
      </div>

      <div className="topicName">
        <div className="topicNameLabel">TOPIC</div>
        <div className="topicNameValue">{topic || "—"}</div>
      </div>

      <div className="overviewGrid">
        <div className="miniStat">
          <div className="miniLabel">Changes</div>
          <div className="miniValue">{metrics.totalChanges}</div>
        </div>

        <div className="miniStat">
          <div className="miniLabel">Repositories</div>
          <div className="miniValue">{metrics.repositories}</div>
        </div>

        <div className="miniStat">
          <div className="miniLabel">Branches</div>
          <div className="miniValue">{metrics.branches}</div>
        </div>

        <div className="miniStat">
          <div className="miniLabel">Open Changes</div>
          <div className="miniValue">{metrics.openChanges}</div>
        </div>

        <div className="miniStat">
          <div className="miniLabel">Merged</div>
          <div className="miniValue">{metrics.mergedChanges}</div>
        </div>

        <div className="miniStat">
          <div className="miniLabel">Abandoned</div>
          <div className="miniValue">{metrics.abandonedChanges}</div>
        </div>

        <div className="miniStat span2">
          <div className="miniLabel">Merge Rate</div>
          <div className="miniValue">{metrics.mergeRate}%</div>
        </div>
      </div>
    </div>
  );
}

function RecentActivity({ activity = [] }) {
  return (
    <div className="card">
      <div className="sectionHeader">
        <div>
          <div className="sectionTitle">Recent Activity</div>
          <div className="sectionSubtitle">Latest events and updates</div>
        </div>
      </div>

      <div className="activityScroll">
        {activity.length === 0 ? (
          <div className="muted">No activity yet.</div>
        ) : (
          activity.map((it, idx) => (
            <div className="activityItem" key={idx}>
              <div className="activityMain">
                <span className="bold">{it.who}</span> {it.action}{" "}
                <span className="link">{it.id}</span>
              </div>
              <div className="muted">{it.time}</div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function TopContributors({ contributors = [] }) {
  return (
    <div className="card">
      <div className="sectionHeader">
        <div>
          <div className="sectionTitle">Top Contributors</div>
          <div className="sectionSubtitle">
            Based on number of changes in this topic
          </div>
        </div>
      </div>

      <div className="contributorsList">
        {contributors.length === 0 ? (
          <div className="muted">No contributors found.</div>
        ) : (
          contributors.map((p, idx) => (
            <div className="contribRow" key={idx}>
              <div className="avatar">{p.initials}</div>
              <div className="contribInfo">
                <div className="bold">{p.name}</div>
                <div className="muted">{p.meta}</div>
              </div>
              <div className="contribTotal">
                <div className="bold">{p.total}</div>
                <div className="muted">total</div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function ChangesTable({ changes }) {
  const rows = changes.slice(0, 10).map((c) => ({
    key: c.id,
    number: c._number ? `#${c._number}` : c.id,
    subject: c.subject || "—",
    repo: c.project || "—",
    status: c.status || "—",
    revisions: "—",
    ci: "—",
    timeline:
      c.created && c.updated
        ? `${c.created.slice(0, 10)} → ${c.updated.slice(0, 10)}`
        : "—",
  }));

  return (
    <div className="card">
      <div className="cardHeaderRow">
        <div className="sectionTitle">Changes &amp; Timeline</div>
        <div className="muted">{changes.length} changes</div>
      </div>

      <div className="tableWrap">
        <table className="table">
          <thead>
            <tr>
              <th>Change ID</th>
              <th>Subject</th>
              <th>Repository</th>
              <th>Status</th>
              <th>Revisions</th>
              <th>CI</th>
              <th>Timeline</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key}>
                <td className="link">{r.number}</td>
                <td>{r.subject}</td>
                <td className="mono">{r.repo}</td>
                <td>
                  <span
                    className={`pill ${
                      r.status === "MERGED" ? "pillGreen" : "pillAmber"
                    }`}
                  >
                    {r.status}
                  </span>
                </td>
                <td className="bold">{r.revisions}</td>
                <td>{r.ci}</td>
                <td className="mono">{r.timeline}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function App() {
  const [topicInput, setTopicInput] = useState("test");
  const [topic, setTopic] = useState("test");
  const [changes, setChanges] = useState([]);
  const [metrics, setMetrics] = useState({
    totalChanges: 0,
    openChanges: 0,
    mergedChanges: 0,
    abandonedChanges: 0,
    repositories: 0,
    branches: 0,
    mergeRate: 0,
  });
  const [activity, setActivity] = useState([]);
  const [contributors, setContributors] = useState([]);
  const [reviewQueue, setReviewQueue] = useState([]);
  const [builds, setBuilds] = useState({
    total: 0,
    success: 0,
    failures: 0,
    avgJobTime: null,
  });
  const [loading, setLoading] = useState(false);
  const [activeView, setActiveView] = useState("topics");

  const [aiSummary, setAiSummary] = useState("");
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState("");

  const [theme, setTheme] = useState(() => {
    return localStorage.getItem("theme") || "light";
  });

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
  }, [theme]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    fetch(
      `http://localhost:3001/api/dashboard?topic=${encodeURIComponent(topic)}`
    )
      .then(async (res) => {
        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.error || "Failed to load dashboard");
        }
        return data;
      })
      .then((data) => {
        if (cancelled) return;

        setChanges(data.changes || []);
        setMetrics(
          data.metrics || {
            totalChanges: 0,
            openChanges: 0,
            mergedChanges: 0,
            abandonedChanges: 0,
            repositories: 0,
            branches: 0,
            mergeRate: 0,
          }
        );
        setActivity(data.activity || []);
        setContributors(data.contributors || []);
        setReviewQueue(data.reviewQueue || []);
        setBuilds(
          data.builds || {
            total: 0,
            success: 0,
            failures: 0,
            avgJobTime: null,
          }
        );

        setSummaryError("");
        setAiSummary("");
      })
      .catch((err) => {
        console.error("Dashboard load error:", err);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [topic]);

  const handleSearchSubmit = (e) => {
    e.preventDefault();
    setSummaryError("");
    setAiSummary("");
    setTopic(topicInput.trim() || "test");
  };

  const handleGenerateSummary = async () => {
    if (!topic?.trim()) return;

    try {
      setSummaryLoading(true);
      setSummaryError("");
      setAiSummary("");

      const res = await fetch("http://localhost:3001/api/generate-summary", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ topic: topic.trim() }),
      });

      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.error || "Failed to generate summary");
      }

      if (!data.summary) {
        throw new Error("No summary returned from backend");
      }

      setAiSummary(
        typeof data.summary === "string"
          ? data.summary
          : JSON.stringify(data.summary, null, 2)
      );
    } catch (err) {
      console.error("Summary generation error:", err);
      setSummaryError(err.message || "Something went wrong");
    } finally {
      setSummaryLoading(false);
    }
  };

  return (
    <div className="page">
      <div className="topbar">
        <h1 className="title">Topic-Centric Gerrit Dashboard</h1>

        <div className="navTabs">
          <button className={`navTab ${activeView === 'topics' ? 'navTabActive' : ''}`} onClick={() => setActiveView('topics')}>Topic Dashboard</button>
          <button className={`navTab ${activeView === 'blueprints' ? 'navTabActive' : ''}`} onClick={() => setActiveView('blueprints')}>Blueprint Predictions</button>
          <button className={`navTab ${activeView === 'bottleneck' ? 'navTabActive' : ''}`} onClick={() => setActiveView('bottleneck')}>Coordination Bottleneck</button>
        </div>

        <div className="topbarRight">
          <form className="searchBox" onSubmit={handleSearchSubmit}>
            <span className="searchIcon">🔍</span>
            <input
              className="searchInput"
              value={topicInput}
              onChange={(e) => setTopicInput(e.target.value)}
              placeholder="Enter Gerrit topic name..."
            />
          </form>

          <button
            type="button"
            className="themeBtn"
            onClick={() => setTheme(theme === "light" ? "dark" : "light")}
          >
            {theme === "light" ? "🌙 Dark" : "☀️ Light"}
          </button>
        </div>
      </div>

      {activeView === "topics" ? (
        <>
          <div className="statsRow">
            <StatCard
              label="Completion Rate"
              value={
                loading ? "…" : `${metrics.mergedChanges}/${metrics.totalChanges}`
              }
              icon="📈"
            />
        <StatCard
          label="Open Changes"
          value={loading ? "…" : metrics.openChanges}
          icon="👥"
        />
        <StatCard
          label="Merged"
          value={loading ? "…" : metrics.mergedChanges}
          icon="⚡"
        />
        <StatCard
          label="Merge Rate"
          value={loading ? "…" : `${metrics.mergeRate}%`}
          icon="📈"
        />
      </div>

      <div className="content">
        <div className="leftCol">
          <TopicOverviewCard topic={topic} metrics={metrics} />
          <TopicSummaryCard
            onGenerate={handleGenerateSummary}
            summaryLoading={summaryLoading}
            summaryError={summaryError}
            aiSummary={aiSummary}
          />
          <ChartsGrid changes={changes} />
          <ChangesTable changes={changes} />
        </div>

        <div className="rightCol">
          <ReviewBottlenecks changes={changes} />
          <BuildsCard builds={builds} />
          <RecentActivity activity={activity} />
          <TopContributors contributors={contributors} />
          <ReviewQueue changes={reviewQueue} />
        </div>
      </div>
        </>
      ) : activeView === "blueprints" ? (
        <BlueprintDashboard />
      ) : (
        <BottleneckDashboard />
      )}
    </div>
  );
}
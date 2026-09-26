import "./ChartsGrid.css";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  PieChart,
  Pie,
  Cell,
} from "recharts";
import { useMemo } from "react";

function Card({ title, children }) {
  return (
    <div className="chartCard">
      <div className="chartTitle">{title}</div>
      <div className="chartBody">{children}</div>
    </div>
  );
}

function formatDay(iso) {
  return iso ? iso.slice(0, 10) : "";
}

/** NEW: Open-change aging buckets (only NEW) */
function buildOpenAgingData(changes, nowMs) {
  const buckets = [
    { key: "0–1d", min: 0, max: 1, value: 0 },
    { key: "1–3d", min: 1, max: 3, value: 0 },
    { key: "3–7d", min: 3, max: 7, value: 0 },
    { key: "7–14d", min: 7, max: 14, value: 0 },
    { key: "14d+", min: 14, max: Infinity, value: 0 },
  ];

  const open = changes.filter((c) => c.status === "NEW");

  for (const c of open) {
    const createdMs = c.created ? new Date(c.created).getTime() : nowMs;
    const ageDays = Math.max(0, (nowMs - createdMs) / (1000 * 60 * 60 * 24));

    const b = buckets.find((x) => ageDays >= x.min && ageDays < x.max);
    if (b) b.value += 1;
  }

  return buckets;
}

function buildRepoData(changes) {
  const map = new Map();
  for (const c of changes) {
    const repo = c.project || "Unknown";
    map.set(repo, (map.get(repo) || 0) + 1);
  }
  const arr = Array.from(map.entries()).map(([name, value]) => ({ name, value }));
  arr.sort((a, b) => b.value - a.value);
  return arr.slice(0, 6);
}

function buildTimeSeriesDaily(changes) {
  const byDay = new Map();
  for (const c of changes) {
    const d = formatDay(c.created);
    if (!d) continue;
    byDay.set(d, (byDay.get(d) || 0) + 1);
  }
  return Array.from(byDay.entries())
    .map(([date, value]) => ({ date, value }))
    .sort((a, b) => a.date.localeCompare(b.date));
}

/** Donut: keep it simple (NEW vs ABANDONED shown in your UI) */
function buildDonutStatusData(changes) {
  const open = changes.filter((c) => c.status === "NEW").length;
  const abandoned = changes.filter((c) => c.status === "ABANDONED").length;

  const arr = [
    { name: "Open (New)", value: open },
    { name: "Abandoned", value: abandoned },
  ].filter((x) => x.value > 0);

  return arr;
}

function NiceTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const v = payload[0]?.value;
  return (
    <div className="chartTooltip">
      <div className="chartTooltipLabel">{label}</div>
      <div className="chartTooltipValue">{v}</div>
    </div>
  );
}

function PieTip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const p = payload[0]?.payload;
  return (
    <div className="chartTooltip">
      <div className="chartTooltipLabel">{p?.name}</div>
      <div className="chartTooltipValue">{p?.value}</div>
    </div>
  );
}

export default function ChartsGrid({ changes = [] }) {
  const hasData = changes.length > 0;

  // keeps "now" stable for this render cycle (prevents weird re-renders)
  const nowMs = useMemo(() => Date.now(), [changes]);

  const agingData = useMemo(() => buildOpenAgingData(changes, nowMs), [changes, nowMs]);
  const repoData = useMemo(() => buildRepoData(changes), [changes]);
  const timeData = useMemo(() => buildTimeSeriesDaily(changes), [changes]);
  const donutData = useMemo(() => buildDonutStatusData(changes), [changes]);

  const axisTick = { fill: "var(--muted)", fontSize: 12 };
  const axisLine = { stroke: "var(--border)" };

  const donutColors = ["var(--chart1)", "var(--chart2)"];
  const totalDonut = donutData.reduce((s, x) => s + x.value, 0);

  return (
    <div className="chartsGrid">
      {/* ✅ Replaces redundant Status Breakdown */}
      <Card title="Open Change Aging">
        {!hasData ? (
          <div className="chartEmpty">No data yet. Search a topic to see charts.</div>
        ) : (
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={agingData} margin={{ top: 12, right: 8, left: 0, bottom: 8 }}>
              <CartesianGrid stroke="var(--grid)" strokeDasharray="4 6" vertical={false} />
              <XAxis
                dataKey="key"
                tick={axisTick}
                axisLine={axisLine}
                tickLine={false}
                tickMargin={10}
              />
              <YAxis
                allowDecimals={false}
                tick={axisTick}
                axisLine={false}
                tickLine={false}
                width={28}
              />
              <Tooltip content={<NiceTooltip />} />
              <Bar dataKey="value" fill="var(--chart1)" radius={[12, 12, 12, 12]} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </Card>

      <Card title="Changes Over Time">
        {!hasData ? (
          <div className="chartEmpty">No data yet. Search a topic to see charts.</div>
        ) : (
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={timeData} margin={{ top: 12, right: 10, left: 0, bottom: 8 }}>
              <CartesianGrid stroke="var(--grid)" strokeDasharray="4 6" vertical={false} />
              <XAxis
                dataKey="date"
                tick={axisTick}
                axisLine={axisLine}
                tickLine={false}
                tickMargin={10}
                minTickGap={24}
              />
              <YAxis
                allowDecimals={false}
                tick={axisTick}
                axisLine={false}
                tickLine={false}
                width={28}
              />
              <Tooltip content={<NiceTooltip />} />
              <Line
                type="monotone"
                dataKey="value"
                stroke="var(--chart1)"
                strokeWidth={3}
                dot={{ r: 3, strokeWidth: 2, stroke: "var(--chart1)", fill: "var(--card)" }}
                activeDot={{ r: 5 }}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </Card>

      <Card title="Top Repositories">
        {!hasData ? (
          <div className="chartEmpty">No data yet. Search a topic to see charts.</div>
        ) : (
          <ResponsiveContainer width="100%" height={260}>
            <BarChart
              data={repoData}
              layout="vertical"
              margin={{ top: 10, right: 10, left: 10, bottom: 6 }}
            >
              <CartesianGrid stroke="var(--grid)" strokeDasharray="4 6" horizontal={false} />
              <XAxis
                type="number"
                allowDecimals={false}
                tick={axisTick}
                axisLine={axisLine}
                tickLine={false}
              />
              <YAxis
                type="category"
                dataKey="name"
                width={90}
                tick={axisTick}
                axisLine={false}
                tickLine={false}
              />
              <Tooltip content={<NiceTooltip />} />
              <Bar dataKey="value" fill="var(--chart2)" radius={[12, 12, 12, 12]} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </Card>

      {/* ✅ Keep your donut */}
      <Card title="Status Distribution">
        {!hasData || donutData.length === 0 ? (
          <div className="chartEmpty">No data yet. Search a topic to see charts.</div>
        ) : (
          <>
            <ResponsiveContainer width="100%" height={240}>
              <PieChart>
                <Tooltip content={<PieTip />} />
                <Pie
                  data={donutData}
                  dataKey="value"
                  nameKey="name"
                  innerRadius={70}
                  outerRadius={95}
                  paddingAngle={3}
                  stroke="var(--card)"
                  strokeWidth={6}
                >
                  {donutData.map((entry, index) => (
                    <Cell key={entry.name} fill={donutColors[index % donutColors.length]} />
                  ))}
                </Pie>
              </PieChart>
            </ResponsiveContainer>

            {/* Simple legend like your screenshot */}
            <div className="donutLegendRow">
              {donutData.map((d, i) => {
                const pct = totalDonut === 0 ? 0 : Math.round((d.value / totalDonut) * 100);
                return (
                  <div className="donutLegendItem" key={d.name}>
                    <span
                      className="donutDot"
                      style={{ background: donutColors[i % donutColors.length] }}
                    />
                    <span className="donutLegendName">{d.name}</span>
                    <span className="donutLegendPct">{pct}%</span>
                  </div>
                );
              })}
            </div>
          </>
        )}
      </Card>
    </div>
  );
}
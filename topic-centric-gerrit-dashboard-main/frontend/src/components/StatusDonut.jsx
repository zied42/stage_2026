import React, { useMemo } from "react";
import { ResponsiveContainer, PieChart, Pie, Cell, Tooltip } from "recharts";

function getCssVar(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name);
  return (v && v.trim()) || fallback;
}

function buildDonutData(changes) {
  const counts = { NEW: 0, MERGED: 0, ABANDONED: 0, DRAFT: 0 };

  for (const c of changes) {
    const s = (c.status || "").toUpperCase();
    if (counts[s] !== undefined) counts[s] += 1;
  }

  const rows = [
    { key: "MERGED", name: "Merged", value: counts.MERGED },
    { key: "NEW", name: "Open (New)", value: counts.NEW },
    { key: "ABANDONED", name: "Abandoned", value: counts.ABANDONED },
    // If you want DRAFT too, uncomment:
    // { key: "DRAFT", name: "Draft", value: counts.DRAFT },
  ];

  return rows.filter((r) => r.value > 0);
}

function DonutTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const p = payload[0]?.payload;
  return (
    <div
      style={{
        borderRadius: 12,
        padding: "10px 12px",
        border: `1px solid ${getCssVar("--border", "#e5e7eb")}`,
        background: getCssVar("--card", "#fff"),
        color: getCssVar("--text", "#0f172a"),
        boxShadow: getCssVar("--shadow", "0 10px 30px rgba(15, 23, 42, 0.06)"),
      }}
    >
      <div style={{ fontWeight: 900 }}>{p?.name}</div>
      <div style={{ opacity: 0.85 }}>{p?.value}</div>
    </div>
  );
}

export default function StatusDonut({ changes = [] }) {
  const data = useMemo(() => buildDonutData(changes), [changes]);
  const total = data.reduce((s, d) => s + d.value, 0);

  const c1 = getCssVar("--chart1", "#2563eb");
  const c2 = getCssVar("--chart2", "rgba(37, 99, 235, 0.55)");
  const c3 = getCssVar("--chart3", "rgba(37, 99, 235, 0.25)");
  const c4 = getCssVar("--chart4", "rgba(37, 99, 235, 0.18)");

  const COLORS = {
    MERGED: c1,
    NEW: c2,
    ABANDONED: c3,
    DRAFT: c4,
  };

  return (
    <div className="chartCard">
      <div className="chartTitle">Status Distribution</div>
      <div className="chartBody">
        {total === 0 ? (
          <div className="chartEmpty">No data yet. Search a topic to see charts.</div>
        ) : (
          <>
            <div style={{ height: 240 }}>
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={data}
                    dataKey="value"
                    nameKey="name"
                    cx="50%"
                    cy="50%"
                    innerRadius="62%"
                    outerRadius="88%"
                    paddingAngle={4}
                    stroke="transparent"
                  >
                    {data.map((d) => (
                      <Cell key={d.key} fill={COLORS[d.key] || c1} />
                    ))}
                  </Pie>
                  <Tooltip content={<DonutTooltip />} />
                </PieChart>
              </ResponsiveContainer>
            </div>

            {/* Legend */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              {data.map((d) => (
                <div
                  key={d.key}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    border: `1px solid rgba(148, 163, 184, 0.18)`,
                    borderRadius: 12,
                    padding: "10px 12px",
                    background: "rgba(2, 6, 23, 0.02)",
                  }}
                >
                  <span
                    style={{
                      width: 10,
                      height: 10,
                      borderRadius: 999,
                      background: COLORS[d.key] || c1,
                    }}
                  />
                  <span style={{ fontWeight: 800 }}>{d.name}</span>
                  <span style={{ marginLeft: "auto" }} className="muted">
                    {Math.round((d.value / total) * 100)}%
                  </span>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
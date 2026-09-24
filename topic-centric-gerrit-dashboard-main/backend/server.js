import express from "express";
import cors from "cors";
import dotenv from "dotenv";
import fetch from "node-fetch";

dotenv.config();

const app = express();
app.use(cors({ origin: true, credentials: true }));
app.use(express.json());

const PORT = process.env.PORT || 3001;
const BASE = (process.env.GERRIT_BASE_URL || "").replace(/\/$/, "");

const OLLAMA_URL = "http://localhost:11434/api/generate";
const OLLAMA_MODEL = process.env.OLLAMA_MODEL || "qwen:0.5b";

/**
 * Build Gerrit URL
 */
function gerritUrl(path) {
  const hasAuth = !!(process.env.GERRIT_USER && process.env.GERRIT_TOKEN);
  const prefix = hasAuth ? "/a" : "";
  return `${BASE}${prefix}${path}`;
}

/**
 * Build Authorization header
 */
function authHeader() {
  const { GERRIT_USER, GERRIT_TOKEN } = process.env;
  if (!GERRIT_USER || !GERRIT_TOKEN) return {};
  const basic = Buffer.from(`${GERRIT_USER}:${GERRIT_TOKEN}`).toString(
    "base64",
  );
  return { Authorization: `Basic ${basic}` };
}

/**
 * Generic Gerrit GET helper
 */
async function gerritGet(path) {
  const res = await fetch(gerritUrl(path), {
    headers: {
      Accept: "application/json",
      ...authHeader(),
    },
  });

  const text = await res.text();

  if (!res.ok) {
    throw new Error(`Gerrit ${res.status}: ${text}`);
  }

  const cleaned = text.replace(/^\)\]\}'\n/, "");
  return JSON.parse(cleaned);
}

function safeArray(value) {
  return Array.isArray(value) ? value : [];
}

function formatOwner(change) {
  return (
    change?.owner?.name ||
    change?.owner?.username ||
    change?.owner?.email ||
    `User ${change?.owner?._account_id ?? ""}`.trim() ||
    "Unknown"
  );
}

function initialsFromName(name) {
  if (!name || name === "Unknown") return "U";
  return name
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0].toUpperCase())
    .join("");
}

function toDateMs(value) {
  const ms = value ? new Date(value).getTime() : NaN;
  return Number.isNaN(ms) ? null : ms;
}

/**
 * Search Gerrit with standard options
 */
async function searchChanges(query) {
  const q = encodeURIComponent(query);

  const data = await gerritGet(
    `/changes/?q=${q}&n=100&pp=0` +
      `&o=DETAILED_ACCOUNTS` +
      `&o=LABELS` +
      `&o=DETAILED_LABELS` +
      `&o=SUBMIT_REQUIREMENTS` +
      `&o=MESSAGES`,
  );

  return safeArray(data);
}

/**
 * Fetch topic changes with fallback strategy:
 * 1) exact topic search
 * 2) commit message search
 * 3) subject search
 */
async function fetchTopicChanges(topic) {
  let data = await searchChanges(`topic:"${topic}"`);
  if (data.length > 0) {
    return {
      changes: data,
      searchMode: "topic",
    };
  }

  console.log(`No topic results for "${topic}". Trying message search...`);

  data = await searchChanges(`message:${topic}`);
  if (data.length > 0) {
    return {
      changes: data,
      searchMode: "message",
    };
  }

  console.log(`No message results for "${topic}". Trying subject search...`);

  data = await searchChanges(`subject:${topic}`);
  return {
    changes: data,
    searchMode: data.length > 0 ? "subject" : "none",
  };
}

/**
 * Topic overview metrics
 */
function buildMetrics(changes) {
  const totalChanges = changes.length;
  const openChanges = changes.filter((c) => c.status === "NEW").length;
  const mergedChanges = changes.filter((c) => c.status === "MERGED").length;
  const abandonedChanges = changes.filter(
    (c) => c.status === "ABANDONED",
  ).length;

  const repositories = new Set(changes.map((c) => c.project).filter(Boolean))
    .size;
  const branches = new Set(changes.map((c) => c.branch).filter(Boolean)).size;

  const mergeRate =
    totalChanges === 0 ? 0 : Math.round((mergedChanges / totalChanges) * 100);

  return {
    totalChanges,
    openChanges,
    mergedChanges,
    abandonedChanges,
    repositories,
    branches,
    mergeRate,
  };
}

/**
 * Recent activity from latest updated changes
 */
function buildRecentActivity(changes) {
  return changes
    .slice()
    .sort((a, b) =>
      String(b.updated || "").localeCompare(String(a.updated || "")),
    )
    .slice(0, 8)
    .map((c) => {
      let action = "updated";
      if (c.status === "MERGED") action = "merged";
      else if (c.status === "ABANDONED") action = "abandoned";

      return {
        who: formatOwner(c),
        action,
        id: c._number ? `#${c._number}` : c.id,
        time: c.updated ? c.updated.slice(0, 16).replace("T", " ") : "—",
        status: c.status || "UNKNOWN",
      };
    });
}

/**
 * Top contributors
 */
function buildContributors(changes) {
  const byOwner = new Map();

  for (const c of changes) {
    const key = c?.owner?._account_id || formatOwner(c);

    if (!byOwner.has(key)) {
      byOwner.set(key, {
        name: formatOwner(c),
        total: 0,
        merged: 0,
        open: 0,
        abandoned: 0,
      });
    }

    const row = byOwner.get(key);
    row.total += 1;
    if (c.status === "MERGED") row.merged += 1;
    if (c.status === "NEW") row.open += 1;
    if (c.status === "ABANDONED") row.abandoned += 1;
  }

  return Array.from(byOwner.values())
    .sort((a, b) => b.total - a.total)
    .slice(0, 5)
    .map((row) => ({
      initials: initialsFromName(row.name),
      name: row.name,
      total: row.total,
      merged: row.merged,
      open: row.open,
      abandoned: row.abandoned,
      meta: `${row.total} changes • ${row.merged} merged`,
    }));
}

/**
 * Review queue = oldest NEW changes first
 */
function buildReviewQueue(changes) {
  const now = Date.now();

  return changes
    .filter((c) => c.status === "NEW")
    .map((c) => {
      const createdMs = toDateMs(c.created) ?? now;
      return {
        id: c._number ? `#${c._number}` : `#${c.id}`,
        subject: c.subject || "—",
        repo: c.project || "—",
        ageDays: Math.max(
          0,
          Math.floor((now - createdMs) / (1000 * 60 * 60 * 24)),
        ),
      };
    })
    .sort((a, b) => b.ageDays - a.ageDays)
    .slice(0, 6);
}

/**
 * Velocity
 */
function buildVelocity(changes) {
  const merged = changes.filter((c) => c.status === "MERGED");
  let mergesPerDay = null;

  if (merged.length > 0) {
    const createdTimes = merged
      .map((c) => toDateMs(c.created))
      .filter((x) => x != null);
    const updatedTimes = merged
      .map((c) => toDateMs(c.updated))
      .filter((x) => x != null);

    if (createdTimes.length > 0 && updatedTimes.length > 0) {
      const minCreated = Math.min(...createdTimes);
      const maxUpdated = Math.max(...updatedTimes);
      const days = Math.max(
        1,
        Math.ceil((maxUpdated - minCreated) / (1000 * 60 * 60 * 24)),
      );
      mergesPerDay = Number((merged.length / days).toFixed(2));
    }
  }

  return {
    medianReviewDuration: null,
    medianTimeToFirstReview: null,
    mergesPerDay,
  };
}

/**
 * Builds from Gerrit labels / submit requirements
 */
function buildBuilds(changes) {
  let success = 0;
  let failures = 0;

  for (const change of changes) {
    let changeSuccess = false;
    let changeFailure = false;

    const verifiedVotes = change?.labels?.Verified?.all || [];

    for (const vote of verifiedVotes) {
      const isBot =
        Array.isArray(vote.tags) && vote.tags.includes("SERVICE_USER");

      if (!isBot) continue;

      if (vote.value === 1) changeSuccess = true;
      if (vote.value === -1) changeFailure = true;
    }

    const messages = Array.isArray(change.messages) ? change.messages : [];

    for (const msg of messages) {
      const tag = String(msg.tag || "").toLowerCase();
      const authorTags = Array.isArray(msg.author?.tags) ? msg.author.tags : [];
      const isBotMessage =
        tag.includes("zuul") ||
        tag.includes("check") ||
        authorTags.includes("SERVICE_USER");

      if (!isBotMessage) continue;

      const text = String(msg.message || "").toLowerCase();

      if (text.includes("verified+1")) changeSuccess = true;
      if (text.includes("verified-1")) changeFailure = true;
    }

    if (changeFailure) failures += 1;
    else if (changeSuccess) success += 1;
  }

  return {
    total: success + failures,
    success,
    failures,
    avgJobTime: null,
  };
}

/**
 * -------- REVIEW BOTTLENECKS --------
 */
function buildReviewBottlenecks(changes) {
  const now = Date.now();
  const openChanges = changes.filter((c) => c.status === "NEW");

  let oldestOpenDays = 0;
  let staleChanges = 0;
  let highComment = 0;
  let unresolved = 0;

  for (const c of openChanges) {
    const createdMs = toDateMs(c.created);
    const updatedMs = toDateMs(c.updated);

    if (createdMs) {
      const ageDays = Math.floor((now - createdMs) / (1000 * 60 * 60 * 24));
      if (ageDays > oldestOpenDays) oldestOpenDays = ageDays;
    }

    if (updatedMs) {
      const staleDays = Math.floor((now - updatedMs) / (1000 * 60 * 60 * 24));
      if (staleDays >= 7) staleChanges += 1;
    }

    if ((c.total_comment_count || 0) >= 10) {
      highComment += 1;
    }

    if ((c.unresolved_comment_count || 0) > 0) {
      unresolved += 1;
    }
  }

  return {
    oldestOpenDays,
    staleChanges,
    highComment,
    unresolved,
  };
}

/**
 * -------- SUMMARY HELPERS --------
 */
function summarizeChangesForPrompt(changes) {
  return changes
    .slice(0, 8)
    .map((c, index) => {
      const comments = c.total_comment_count ?? 0;
      const unresolved = c.unresolved_comment_count ?? 0;
      const owner = formatOwner(c);
      const id = c._number ? `#${c._number}` : c.id;

      return `${index + 1}. ${id}
Subject: ${c.subject || "No subject"}
Status: ${c.status || "UNKNOWN"}
Owner: ${owner}
Repository: ${c.project || "Unknown repo"}
Comments: ${comments}
Unresolved: ${unresolved}`;
    })
    .join("\n\n");
}

function buildLLMPrompt(topic, changes, metrics, builds) {
  const formattedChanges = summarizeChangesForPrompt(changes);

  return `
Write a short Gerrit dashboard summary.

Topic: ${topic}

Facts:
- Total changes: ${metrics.totalChanges}
- Open changes: ${metrics.openChanges}
- Merged changes: ${metrics.mergedChanges}
- Abandoned changes: ${metrics.abandonedChanges}
- Merge rate: ${metrics.mergeRate}%
- Successful builds: ${builds.success}
- Failed builds: ${builds.failures}

Changes:
${formattedChanges}

Write exactly 2 short sentences in plain English.
Sentence 1: explain what the topic appears to be about based only on the visible change subjects.
Sentence 2: explain whether the work looks active, completed, or blocked based only on open, merged, abandoned, unresolved, and build information.

Do not use JSON.
Do not use bullet points.
Do not use numbering.
Do not repeat the instructions.
Do not invent technical details that are not visible in the change subjects or metadata.
If the topic is unclear, say the exact purpose is not fully clear from the visible change metadata.
`;
}

function buildFallbackSummary(topic, changes, metrics, builds, contributors) {
  const topSubjects = changes
    .slice(0, 3)
    .map((c) => c.subject)
    .filter(Boolean);

  const leadContributor = contributors[0]?.name;

  let firstSentence = `The exact purpose of the topic "${topic}" is not fully clear from the visible change metadata.`;
  if (topSubjects.length > 0) {
    firstSentence = `This topic appears to involve changes such as ${topSubjects.join("; ")}.`;
  }

  let secondSentence = "Overall, the work appears to be in progress.";
  if (
    metrics.totalChanges > 0 &&
    metrics.mergedChanges === metrics.totalChanges
  ) {
    secondSentence = "Overall, the work appears to be completed.";
  } else if (metrics.openChanges > 0 && metrics.mergedChanges > 0) {
    secondSentence =
      "Overall, the work appears active, with both open and merged changes visible.";
  } else if (metrics.openChanges > 0 && metrics.mergedChanges === 0) {
    secondSentence = "Overall, the work appears to still be under review.";
  }

  if (changes.some((c) => (c.unresolved_comment_count || 0) > 0)) {
    secondSentence += " Some unresolved review discussion is also visible.";
  } else if (builds.failures > 0) {
    secondSentence +=
      " Some build failures are visible in the available CI data.";
  } else if (leadContributor) {
    secondSentence += ` The most active contributor appears to be ${leadContributor}.`;
  }

  return `${firstSentence} ${secondSentence}`;
}

function cleanModelSummary(raw) {
  if (!raw) return "";

  let text = String(raw).trim();

  text = text.replace(/^```[\w-]*\n?/, "");
  text = text.replace(/```$/, "");
  text = text.replace(/^["'`]+|["'`]+$/g, "");
  text = text.replace(/\s+/g, " ").trim();

  const bannedPatterns = [
    /^\{/,
    /"goal"/i,
    /"keyChanges"/i,
    /"readOrder"/i,
    /one short sentence/i,
    /short item/i,
    /instructions:/i,
    /return plain text only/i,
    /do not use json/i,
    /sentence 1:/i,
    /sentence 2:/i,
    /say what the topic appears/i,
    /say whether the work looks/i,
    /visible change metadata/i,
  ];

  for (const pattern of bannedPatterns) {
    if (pattern.test(text)) return "";
  }

  const sentences = text
    .split(/(?<=[.!?])\s+/)
    .map((s) => s.trim())
    .filter(Boolean);

  const unique = [];
  const seen = new Set();

  for (const sentence of sentences) {
    const key = sentence.toLowerCase();
    if (!seen.has(key)) {
      seen.add(key);
      unique.push(sentence);
    }
  }

  const result = unique.slice(0, 2).join(" ").trim();
  if (!result || result.length < 40) return "";

  return result;
}

async function generateTopicSummary(
  topic,
  changes,
  metrics,
  contributors,
  builds,
) {
  if (!changes || changes.length === 0) {
    return "No summary is available because no changes were found for this topic.";
  }

  try {
    const prompt = buildLLMPrompt(topic, changes, metrics, builds);

    const res = await fetch(OLLAMA_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: OLLAMA_MODEL,
        prompt,
        stream: false,
        options: {
          temperature: 0.0,
          num_predict: 90,
        },
      }),
    });

    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.error || "Failed to generate summary with Ollama");
    }

    const raw = data.response?.trim();
    const cleaned = cleanModelSummary(raw);

    if (cleaned) {
      return cleaned;
    }
  } catch (err) {
    console.error("Ollama summary fallback triggered:", err.message);
  }

  return buildFallbackSummary(topic, changes, metrics, builds, contributors);
}

/**
 * Health check
 */
app.get("/api/health", (req, res) => {
  res.json({ ok: true, ollamaModel: OLLAMA_MODEL });
});

/**
 * Raw changes endpoint
 */
app.get("/api/changes", async (req, res) => {
  try {
    const topic = (req.query.topic || "").trim();
    if (!topic) return res.status(400).json({ error: "Missing ?topic=" });

    const { changes, searchMode } = await fetchTopicChanges(topic);

    res.json({
      topic,
      searchMode,
      changes,
    });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

/**
 * Full dashboard endpoint
 */
app.get("/api/dashboard", async (req, res) => {
  try {
    const topic = (req.query.topic || "").trim();
    if (!topic) return res.status(400).json({ error: "Missing ?topic=" });

    const { changes, searchMode } = await fetchTopicChanges(topic);

    const metrics = buildMetrics(changes);
    const activity = buildRecentActivity(changes);
    const contributors = buildContributors(changes);
    const reviewQueue = buildReviewQueue(changes);
    const velocity = buildVelocity(changes);
    const builds = buildBuilds(changes);
    const bottlenecks = buildReviewBottlenecks(changes);

    const buildDebug = changes.slice(0, 5).map((c) => ({
      id: c._number,
      subject: c.subject,
      labelNames: Object.keys(c.labels || {}),
      submitRequirementNames: Array.isArray(c.submit_requirements)
        ? c.submit_requirements.map((sr) => `${sr.name}:${sr.status}`)
        : [],
    }));

    res.json({
      topic,
      searchMode,
      changes,
      metrics,
      activity,
      contributors,
      reviewQueue,
      velocity,
      builds,
      bottlenecks,
      buildDebug,
    });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

/**
 * LLM summary endpoint
 */
app.post("/api/generate-summary", async (req, res) => {
  try {
    const topic = String(req.body?.topic || "").trim();
    if (!topic) {
      return res.status(400).json({ error: "Missing topic in request body" });
    }

    const { changes, searchMode } = await fetchTopicChanges(topic);
    const metrics = buildMetrics(changes);
    const contributors = buildContributors(changes);
    const builds = buildBuilds(changes);

    const summary = await generateTopicSummary(
      topic,
      changes,
      metrics,
      contributors,
      builds,
    );

    res.json({
      topic,
      searchMode,
      summary,
    });
  } catch (err) {
    console.error("LLM summary error:", err);
    res
      .status(500)
      .json({ error: err.message || "Failed to generate summary" });
  }
});

/**
 * Single change detail
 */
app.get("/api/changes/:id", async (req, res) => {
  try {
    const id = encodeURIComponent(req.params.id);
    const data = await gerritGet(
      `/changes/${id}/detail?pp=0&o=DETAILED_ACCOUNTS&o=LABELS&o=DETAILED_LABELS&o=SUBMIT_REQUIREMENTS&o=MESSAGES`,
    );
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

/**
 * -------- BLUEPRINT PREDICTION PROXY --------
 * Proxies requests to the Python prediction microservice (Flask on port 5001).
 * This keeps Express.js as the single frontend-facing API.
 */
const PREDICTION_SERVICE_URL =
  process.env.PREDICTION_SERVICE_URL || "http://localhost:5001";

async function proxyToPredictor(path) {
  const url = `${PREDICTION_SERVICE_URL}${path}`;
  const res = await fetch(url, {
    headers: { Accept: "application/json" },
  });
  const text = await res.text();
  if (!res.ok) {
    let errMsg;
    try {
      errMsg = JSON.parse(text).error || text;
    } catch {
      errMsg = text;
    }
    const err = new Error(errMsg);
    err.statusCode = res.status;
    throw err;
  }
  return JSON.parse(text);
}

/**
 * List all available blueprints
 */
app.get("/api/blueprints", async (req, res) => {
  try {
    const search = req.query.search || "";
    const project = req.query.project || "";
    let path = "/blueprints";
    const params = [];
    if (search) params.push(`search=${encodeURIComponent(search)}`);
    if (project) params.push(`project=${encodeURIComponent(project)}`);
    if (params.length > 0) path += `?${params.join("&")}`;
    const data = await proxyToPredictor(path);
    res.json(data);
  } catch (err) {
    res.status(err.statusCode || 500).json({ error: err.message });
  }
});

/**
 * Get blueprint metadata
 */
app.get("/api/blueprints/:project/:name", async (req, res) => {
  try {
    const blueprintId = `${req.params.project}::${req.params.name}`;
    const data = await proxyToPredictor(
      `/blueprints/${encodeURIComponent(blueprintId)}`,
    );
    res.json(data);
  } catch (err) {
    res.status(err.statusCode || 500).json({ error: err.message });
  }
});

/**
 * Get 4 hardness prediction results for a blueprint (NO bottleneck)
 */
app.get("/api/blueprints/:project/:name/predictions", async (req, res) => {
  try {
    const blueprintId = `${req.params.project}::${req.params.name}`;
    const data = await proxyToPredictor(
      `/blueprints/${encodeURIComponent(blueprintId)}/predictions`,
    );
    res.json(data);
  } catch (err) {
    res.status(err.statusCode || 500).json({ error: err.message });
  }
});

/**
 * Get coordination bottleneck prediction (separate from hardness)
 */
app.get("/api/blueprints/:project/:name/bottleneck", async (req, res) => {
  try {
    const blueprintId = `${req.params.project}::${req.params.name}`;
    const data = await proxyToPredictor(
      `/blueprints/${encodeURIComponent(blueprintId)}/bottleneck`,
    );
    res.json(data);
  } catch (err) {
    res.status(err.statusCode || 500).json({ error: err.message });
  }
});

/**
 * Get graph JSON data for a blueprint's dependency visualization
 */
app.get("/api/blueprints/:project/:name/graph", async (req, res) => {
  try {
    const blueprintId = `${req.params.project}::${req.params.name}`;
    const data = await proxyToPredictor(
      `/blueprints/${encodeURIComponent(blueprintId)}/graph`,
    );
    res.json(data);
  } catch (err) {
    res.status(err.statusCode || 500).json({ error: err.message });
  }
});

/**
 * Chatbot: send a message about a selected blueprint
 */
app.post("/api/blueprints/:project/:name/chat", async (req, res) => {
  try {
    const blueprintId = `${req.params.project}::${req.params.name}`;
    const url = `${PREDICTION_SERVICE_URL}/blueprints/${encodeURIComponent(blueprintId)}/chat`;
    const proxyRes = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(req.body),
    });
    const text = await proxyRes.text();
    if (!proxyRes.ok) {
      let errMsg;
      try { errMsg = JSON.parse(text).error || text; } catch { errMsg = text; }
      return res.status(proxyRes.status).json({ error: errMsg });
    }
    res.json(JSON.parse(text));
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

/**
 * Prediction service health check
 */
app.get("/api/predictions/health", async (req, res) => {
  try {
    const data = await proxyToPredictor("/health");
    res.json(data);
  } catch (err) {
    res
      .status(500)
      .json({ error: "Prediction service unavailable: " + err.message });
  }
});

app.listen(PORT, () => {
  console.log(`Backend listening on http://localhost:${PORT}`);
  console.log(`Using Ollama model: ${OLLAMA_MODEL}`);
  console.log(`Prediction service: ${PREDICTION_SERVICE_URL}`);
});

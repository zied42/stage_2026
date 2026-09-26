
export default function TopicSummaryCard({
  onGenerate,
  summaryLoading,
  summaryError,
  aiSummary,
}) {
  const displaySummary =
    typeof aiSummary === "string"
      ? aiSummary
      : aiSummary
        ? JSON.stringify(aiSummary, null, 2)
        : "";

  return (
    <div className="card">
      <div className="cardHeaderRow">
        <div>
          <div className="sectionTitle">Topic Summary (AI)</div>
          <div className="sectionSubtitle">Auto-generated overview</div>
        </div>

        <button
          className="primaryBtn"
          onClick={onGenerate}
          disabled={summaryLoading}
        >
          {summaryLoading ? "Generating..." : "Generate"}
        </button>
      </div>

      <div className="summarySingleCard">
        {summaryLoading ? (
          <div className="summaryText">Generating summary...</div>
        ) : summaryError ? (
          <>
            <div className="summaryLabel">ERROR</div>
            <div className="summaryText">{summaryError}</div>
          </>
        ) : displaySummary ? (
          <>
            <div className="summaryLabel">SUMMARY</div>
            <div className="summaryText" style={{ whiteSpace: "pre-wrap" }}>
              {displaySummary}
            </div>
          </>
        ) : (
          <>
            <div className="summaryLabel">SUMMARY</div>
            <div className="summaryText">
              Click Generate to create a short and clear AI summary for this
              topic.
            </div>
          </>
        )}
      </div>
    </div>
  );
}
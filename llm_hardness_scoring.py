"""
Scores blueprint "hardness" using an LLM (via NVIDIA's NIM endpoint,
OpenAI-compatible API) instead of regex/structural heuristics.

Reads hardness_inputs.jsonl (same input as the old feature-extraction script)
and writes hardness_llm_scores.csv, keyed by blueprint_name / lp_project so
it can be merged with hardness_spec_derived_features.csv later.

For each record, the LLM reads the spec (+ summary/topics context) and
returns a structured JSON judgment. This mirrors the old script's section
list, but instead of a True/False "does this section exist" flag, the LLM
gives each section a 0-10 quality/completeness score (0 = section missing
entirely; 1-10 = present, scored on how thorough/clear it is):
    - section_problem_description_score
    - section_proposed_change_score
    - section_alternatives_score
    - section_data_model_score
    - section_rest_api_score
    - section_security_impact_score
    - section_testing_score
    - section_dependencies_score
    - section_documentation_impact_score
    - section_work_items_score
Plus overall judgment fields:
    - hardness_score   (1-10, overall)
    - complexity       (1-10)
    - ambiguity        (1-10)
    - risk             (1-10)
    - rationale        (short free text, 1-3 sentences)

Design notes:
  - Calls run concurrently (ThreadPoolExecutor) with a small worker pool to
    stay polite to the API, and retry on transient failures.
  - Results are written incrementally (flushed after every completed record)
    so a crash / rate-limit kill partway through doesn't lose progress —
    re-running skips blueprint_names already present in the output CSV.
  - The API key is read from the NVIDIA_API_KEY env var, falling back to
    the hardcoded key below (per your instruction — swap/rotate as needed).
"""

import os
import re
import csv
import json
import time
import argparse
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed

from openai import OpenAI

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

INPUT_JSONL = "hardness_inputs.jsonl"
OUTPUT_CSV = "hardness_llm_scores_with_gpt.csv"

# Small/fast instruct model by default - this task is simple structured
# scoring, not deep reasoning, so a big flagship model is overkill and much
# slower per call. mistral-nemotron is built for agentic/instruction-following
# workloads, which suits strict-JSON scoring well. Swap via --model, e.g.
# mistralai/mistral-medium-3.5-128b for a slower/higher-quality pass.
MODEL = "openai/gpt-oss-120b"
BASE_URL = "https://integrate.api.nvidia.com/v1"

# Fallback key is the one you pasted (said to already be revoked). Prefer
# setting NVIDIA_API_KEY in your env instead of relying on this.
API_KEY = os.environ.get(
    "NVIDIA_API_KEY",
    "",
)

MAX_WORKERS = 5
MAX_RETRIES = 6
RETRY_BACKOFF_SECONDS = 3
SPEC_TEXT_CHAR_LIMIT = 12000  # truncate very long specs to keep prompts sane

# Your NIM key is capped at 40 requests/minute. Default a bit under that so
# normal jitter/timing doesn't tip you over. Override with --rpm.
RATE_LIMIT_RPM = 35

# When we DO get a 429, back off much harder than a normal transient error -
# retrying instantly (or after 3s) while still over budget just burns a retry
# for nothing. This is the base; actual wait scales with attempt number too.
RATE_LIMIT_BACKOFF_SECONDS = 20

SECTION_SCORE_FIELDS = [
    "section_problem_description_score",
    "section_proposed_change_score",
    "section_alternatives_score",
    "section_data_model_score",
    "section_rest_api_score",
    "section_security_impact_score",
    "section_testing_score",
    "section_dependencies_score",
    "section_documentation_impact_score",
    "section_work_items_score",
]

FIELDNAMES = (
    ["blueprint_name", "lp_project"]
    + SECTION_SCORE_FIELDS
    + ["hardness_score", "complexity", "ambiguity", "risk", "rationale", "llm_error"]
)

SYSTEM_PROMPT = (
    "You are a senior software architect assessing an OpenStack-style design "
    "blueprint/spec, both section by section and overall.\n\n"
    "For EACH of the 10 standard spec sections below, give a score from 0 to 10:\n"
    "  0  = section is missing / not present at all\n"
    "  1-3 = present but thin, vague, or boilerplate\n"
    "  4-7 = present and reasonably clear/complete\n"
    "  8-10 = present, thorough, precise, and well-specified\n"
    "Sections to score: problem_description, proposed_change, alternatives, "
    "data_model, rest_api, security_impact, testing, dependencies, "
    "documentation_impact, work_items.\n\n"
    "Then give an OVERALL judgment of how HARD this change is to implement, "
    "based on technical complexity, ambiguity/underspecification of the plan, "
    "and delivery risk (breaking changes, cross-project impact, unclear scope).\n\n"
    "Respond with ONLY a JSON object, no prose, no markdown fences, matching "
    "exactly this schema:\n"
    '{"section_problem_description_score": <int 0-10>, '
    '"section_proposed_change_score": <int 0-10>, '
    '"section_alternatives_score": <int 0-10>, '
    '"section_data_model_score": <int 0-10>, '
    '"section_rest_api_score": <int 0-10>, '
    '"section_security_impact_score": <int 0-10>, '
    '"section_testing_score": <int 0-10>, '
    '"section_dependencies_score": <int 0-10>, '
    '"section_documentation_impact_score": <int 0-10>, '
    '"section_work_items_score": <int 0-10>, '
    '"hardness_score": <int 1-10>, "complexity": <int 1-10>, '
    '"ambiguity": <int 1-10>, "risk": <int 1-10>, "rationale": "<1-3 sentences>"}'
)

_write_lock = threading.Lock()


class RateLimiter:
    """Thread-safe sliding-window rate limiter shared across all worker
    threads. Blocks a caller until it's safe to make another request,
    ensuring no more than `rpm` requests happen in any trailing 60s window.
    This is what actually keeps us under the account's request cap -
    max_workers alone doesn't do that, since threads submit as fast as they
    can regardless of thread count."""

    def __init__(self, rpm: int):
        self.rpm = rpm
        self.window_seconds = 60.0
        self._timestamps = deque()
        self._lock = threading.Lock()

    def acquire(self):
        while True:
            with self._lock:
                now = time.monotonic()
                # drop timestamps that have aged out of the trailing window
                while self._timestamps and now - self._timestamps[0] >= self.window_seconds:
                    self._timestamps.popleft()

                if len(self._timestamps) < self.rpm:
                    self._timestamps.append(now)
                    return

                # window is full - figure out how long until the oldest
                # timestamp ages out and a slot frees up
                sleep_for = self.window_seconds - (now - self._timestamps[0]) + 0.05

            time.sleep(max(sleep_for, 0.05))


def build_user_prompt(rec: dict) -> str:
    spec_text = (rec.get("spec_text") or "")[:SPEC_TEXT_CHAR_LIMIT]
    summary = rec.get("summary") or ""
    topics = rec.get("topics") or []
    topic_names = [t.get("name") for t in topics if isinstance(t, dict) and t.get("name")]

    parts = [f"Blueprint: {rec.get('blueprint_name')}", f"Project: {rec.get('lp_project')}"]
    if summary:
        parts.append(f"Summary: {summary}")
    if topic_names:
        parts.append(f"Related topics: {', '.join(topic_names[:15])}")
    parts.append("---- SPEC TEXT ----")
    parts.append(spec_text if spec_text.strip() else "(no spec text provided)")

    return "\n".join(parts)


def extract_json(text: str) -> dict:
    """Pull the first {...} JSON object out of a model response, tolerating
    stray markdown fences or leading/trailing prose."""
    text = text.strip()
    text = re.sub(r"^```(json)?", "", text.strip(), flags=re.IGNORECASE).strip()
    text = re.sub(r"```$", "", text.strip()).strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in response: {text[:200]!r}")
    return json.loads(match.group(0))


def is_rate_limit_error(exc: Exception) -> bool:
    text = str(exc)
    return "429" in text or "RateLimitError" in type(exc).__name__ or "Too Many Requests" in text


def retry_after_seconds(exc: Exception) -> float | None:
    """Best-effort extraction of a Retry-After style hint from the
    exception/response, if the client library surfaces one."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) if response is not None else None
    if headers:
        for key in ("retry-after", "Retry-After"):
            val = headers.get(key)
            if val:
                try:
                    return float(val)
                except (TypeError, ValueError):
                    pass
    return None


def score_record(client: OpenAI, rec: dict, rate_limiter: "RateLimiter") -> dict:
    row = {
        "blueprint_name": rec.get("blueprint_name"),
        "lp_project": rec.get("lp_project"),
        "hardness_score": None,
        "complexity": None,
        "ambiguity": None,
        "risk": None,
        "rationale": "",
        "llm_error": "",
    }
    for field in SECTION_SCORE_FIELDS:
        row[field] = None

    user_prompt = build_user_prompt(rec)

    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        rate_limiter.acquire()
        try:
            completion = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                top_p=1,
                max_tokens=700,
                seed=42,
                stream=False,
            )
            content = completion.choices[0].message.content
            parsed = extract_json(content)

            for field in SECTION_SCORE_FIELDS:
                row[field] = int(parsed[field])
            row["hardness_score"] = int(parsed["hardness_score"])
            row["complexity"] = int(parsed["complexity"])
            row["ambiguity"] = int(parsed["ambiguity"])
            row["risk"] = int(parsed["risk"])
            row["rationale"] = str(parsed.get("rationale", "")).strip()
            return row

        except Exception as e:  # noqa: BLE001 - want to retry on anything transient
            last_err = e
            if attempt < MAX_RETRIES:
                if is_rate_limit_error(e):
                    hinted = retry_after_seconds(e)
                    wait = hinted if hinted is not None else RATE_LIMIT_BACKOFF_SECONDS * attempt
                    print(f"  [rate limited] backing off {wait:.0f}s before retry {attempt + 1}/{MAX_RETRIES}")
                    time.sleep(wait)
                else:
                    time.sleep(RETRY_BACKOFF_SECONDS * attempt)

    row["llm_error"] = f"{type(last_err).__name__}: {last_err}"
    return row


def load_input(path: str) -> list:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_already_done(path: str) -> set:
    done = set()
    if not os.path.exists(path):
        return done
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("blueprint_name") and not r.get("llm_error"):
                done.add(r["blueprint_name"])
    return done


def compact_output_for_resume(path: str):
    """Before resuming, drop any rows that recorded an llm_error. Those
    blueprints will be re-attempted and re-appended; leaving the old error
    rows in place would leave duplicate rows (one error, one success) for
    the same blueprint_name in the final CSV."""
    if not os.path.exists(path):
        return
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [r for r in reader if not r.get("llm_error")]
        fieldnames = reader.fieldnames or FIELDNAMES

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def append_row(path: str, row: dict, write_header: bool):
    with _write_lock:
        file_exists = os.path.exists(path)
        with open(path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            if write_header and not file_exists:
                writer.writeheader()
            writer.writerow(row)


def main():
    global MODEL
    parser = argparse.ArgumentParser(description="LLM-based hardness scoring")
    parser.add_argument("--input", default=INPUT_JSONL)
    parser.add_argument("--output", default=OUTPUT_CSV)
    parser.add_argument("--limit", type=int, default=None, help="only score first N records (testing)")
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="ignore/delete any existing output CSV and start over from scratch. "
        "Without this flag, an existing output file is auto-detected and resumed "
        "from (rows already completed without an error are kept and skipped).",
    )
    parser.add_argument("--model", default=MODEL, help="NIM model id, e.g. mistralai/mistral-nemotron")
    parser.add_argument(
        "--rpm",
        type=int,
        default=RATE_LIMIT_RPM,
        help="max requests/minute across all workers (your NIM key cap is 40; default 35 for safety margin)",
    )
    args = parser.parse_args()
    MODEL = args.model
    rate_limiter = RateLimiter(args.rpm)

    client = OpenAI(base_url=BASE_URL, api_key=API_KEY)

    records = load_input(args.input)
    if args.limit:
        records = records[: args.limit]

    if args.fresh:
        # explicit request to ignore any existing progress and start clean
        if os.path.exists(args.output):
            os.remove(args.output)
            print(f"--fresh passed: deleted existing {args.output}, starting from zero.")
    elif os.path.exists(args.output):
        # default behavior: auto-resume from whatever's already in the CSV
        compact_output_for_resume(args.output)  # strip old error rows first
        done = load_already_done(args.output)
        records = [r for r in records if r.get("blueprint_name") not in done]
        print(f"Found existing {args.output}: {len(done)} already scored without error, {len(records)} remaining.")
    else:
        print(f"No existing {args.output} found - starting from zero.")

    header_written = os.path.exists(args.output)
    total = len(records)
    completed = 0

    print(f"Rate limit: {args.rpm} req/min across {args.workers} workers.")
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(score_record, client, rec, rate_limiter): rec for rec in records}
        for future in as_completed(futures):
            row = future.result()
            append_row(args.output, row, write_header=not header_written)
            header_written = True
            completed += 1
            status = "OK" if not row["llm_error"] else f"ERROR: {row['llm_error']}"
            print(f"[{completed}/{total}] {row['blueprint_name']}: {status}")

    print(f"\nDone. Wrote results to {args.output}")


if __name__ == "__main__":
    main()
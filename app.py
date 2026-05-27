from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import sys, os, csv, json, io, builtins, queue, threading, uuid

os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"

# Add the Bot directory to the path so Python can find the scraper modules
sys.path.append(os.path.join(os.path.dirname(__file__), "Bot"))

from Bot.main import scrape_directory, PHASE2_ONLY_FIELDS
from Bot.debug import debug
from Bot.intent_filter import intent_from_plan
from Phase2Bot.email_extractor import enrich_from_websites
from DiscoveryBot import run_discovery

app = Flask(__name__)
CORS(app,
    origins=["http://localhost:3000", "http://localhost:3001", "http://localhost:3002"],
    methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Custom-Header"],
    supports_credentials=True)

DATA_DUMP = os.path.join(os.path.dirname(__file__), "Data-dump")
PHASE2_DUMP = os.path.join(os.path.dirname(__file__), "Phase2-Dump")

# Active scrape sessions for interactive prompts
# {session_id: {"queue": Queue, "response_event": Event, "response_value": str}}
active_sessions = {}


def classify_message(msg: str) -> str:
    """Classify a print message into a terminal category for the frontend."""
    ml = msg.lower().strip()
    if any(k in ml for k in ["navigat", "directory url", "depth ", "ai says", "ai wants"]):
        return "NAV"
    if any(k in ml for k in ["search", "trigger", "query", "trying '", "blank", "form-based",
                              "view all", "starts with", "alphabet"]):
        return "SEARCH"
    if any(k in ml for k in ["scroll", "batch"]):
        return "SCROLL"
    if any(k in ml for k in ["pagination", "page ", "load more", "categor"]):
        return "PAGE"
    if any(k in ml for k in ["response:", "captured", "total results"]):
        return "CAPTURE"
    if any(k in ml for k in ["iframe"]):
        return "IFRAME"
    if any(k in ml for k in ["pars", "extract", "selector", "sample:", "regex", "haiku",
                              "member list", "member record", "schema.org"]):
        return "PARSE"
    if any(k in ml for k in ["detail", "crawl", "phase ", "api endpoint", "api fast"]):
        return "DETAIL"
    if any(k in ml for k in ["clean", "dedup", "structured", "saved ", "saving"]):
        return "CLEAN"
    return "LOG"


def is_important_message(msg: str) -> bool:
    """Filter out noisy messages — show everything except known spam."""
    ml = msg.strip()
    if not ml:
        return False
    mll = ml.lower()
    # Filter out raw network RESPONSE: lines (fires for every HTTP request — way too noisy)
    if mll.startswith("response:") or mll.startswith("response: ["):
        return False
    # Filter out Playwright internal chatter
    if "protocol error" in mll or "error reading pending" in mll:
        return False
    # Filter out empty/whitespace-only
    if len(ml) < 3:
        return False
    # Everything else is shown
    return True


def _check_fields_from_file(json_path):
    """Check which data fields are *meaningfully* present in a structured
    JSON file.

    A field is considered "found" only when at least HALF the sampled
    records have it — otherwise the Phase 2 enrichment trigger silently
    skips even when ~90% of records are missing the field (which was the
    pre-fix behavior of the `any(...)` check).
    """
    fields = {"name"}
    try:
        with open(json_path) as f:
            members = json.load(f)
        if not isinstance(members, list) or not members:
            return fields
        sample = members[:20]
        n = len(sample)
        threshold = max(1, n // 2)  # ≥50% of the sample must have it

        def _count(predicate):
            return sum(1 for m in sample if predicate(m))

        if _count(lambda m: bool(m.get("phone"))) >= threshold:
            fields.add("phone")
        if _count(lambda m: any(c.get("email") for c in m.get("contacts", []))) >= threshold:
            fields.add("email")
        if _count(lambda m: bool(m.get("street_address") or m.get("mailing_address"))) >= threshold:
            fields.add("address")
        if _count(lambda m: bool(m.get("description"))) >= threshold:
            fields.add("description")
        if _count(lambda m: bool(m.get("website"))) >= threshold:
            fields.add("website")
    except Exception:
        pass
    return fields


@app.route("/scrape/single", methods=["POST"])
def scrape_single():
    """Stream scrape progress as SSE events. Supports interactive prompts."""
    link = request.json.get("link", "").strip()
    debug_mode = request.json.get("debug", False)
    scrape_mode = request.json.get("mode", "auto")  # "auto" or "direct"
    priority_fields = request.json.get("priority_fields", ["email", "phone"])
    if not link:
        return jsonify({"error": "No link"}), 400

    # Normalize URL — add https:// if missing
    if not link.startswith(("http://", "https://")):
        link = "https://" + link

    session_id = str(uuid.uuid4())
    event_queue = queue.Queue()
    response_event = threading.Event()

    active_sessions[session_id] = {
        "queue": event_queue,
        "response_event": response_event,
        "response_value": None,
    }

    def prompt_via_frontend(detail_url_count, message=None):
        """Replacement for input() — sends prompt to frontend, waits for response."""
        session = active_sessions.get(session_id)
        if not session:
            return False
        msg = message or f"Found {detail_url_count} detail pages. Crawl them? (y/n)"
        event_queue.put({
            "type": "prompt",
            "message": msg,
            "detail_url_count": detail_url_count,
        })
        session["response_event"].wait(timeout=300)
        answer = session.get("response_value", "n")
        session["response_event"].clear()
        session["response_value"] = None  # reset for next prompt
        return answer.lower() in ("y", "yes")

    def bot_thread():
        original_print = builtins.print
        debug.enabled = debug_mode
        debug.reset()

        def captured_print(*args, **kwargs):
            msg = " ".join(str(a) for a in args)
            original_print(*args, **kwargs)
            if is_important_message(msg):
                event_queue.put({
                    "type": "log",
                    "message": msg.strip(),
                    "category": classify_message(msg),
                })

        builtins.print = captured_print
        try:
            members = scrape_directory(
                link, prompt_callback=prompt_via_frontend,
                mode=scrape_mode, priority_fields=priority_fields,
            )

            phase1_records = len(members)
            enriched_count = 0
            ran_phase2 = False

            # --- Auto-trigger Phase 2 if priority fields still missing ---
            if members and priority_fields:
                from urllib.parse import urlparse as _urlparse
                domain = _urlparse(link).netloc.replace(".", "_")
                structured_path = os.path.join(DATA_DUMP, f"{domain}_structured.json")

                if os.path.isfile(structured_path):
                    found = _check_fields_from_file(structured_path)
                    missing = set(priority_fields) - found
                    needs_phase2 = bool(missing) or bool(set(priority_fields) & PHASE2_ONLY_FIELDS)

                    if needs_phase2:
                        missing_display = missing or (set(priority_fields) & PHASE2_ONLY_FIELDS)
                        should_enrich = prompt_via_frontend(
                            0,
                            f"Still missing: {', '.join(sorted(missing_display))}. "
                            f"Run Phase 2 enrichment on company websites? (y/n)"
                        )
                        if should_enrich:
                            event_queue.put({
                                "type": "log",
                                "message": "Starting Phase 2 enrichment...",
                                "category": "LOG",
                            })
                            output_path = enrich_from_websites(structured_path)
                            with open(output_path) as ef:
                                enriched_results = json.load(ef)
                            enriched_count = sum(
                                1 for r in enriched_results
                                if r.get("enrichment_status") == "enriched"
                            )
                            # Compute per-field coverage for priority fields
                            field_coverage = {}
                            for pf in priority_fields:
                                if pf == "email":
                                    field_coverage["email"] = sum(
                                        1 for r in enriched_results
                                        if any(c.get("email") for c in r.get("contacts", []))
                                    )
                                elif pf == "phone":
                                    field_coverage["phone"] = sum(1 for r in enriched_results if r.get("phone"))
                                elif pf == "address":
                                    field_coverage["address"] = sum(
                                        1 for r in enriched_results
                                        if r.get("street_address") or r.get("mailing_address")
                                    )
                                elif pf == "description":
                                    field_coverage["description"] = sum(1 for r in enriched_results if r.get("description"))
                                elif pf == "website":
                                    field_coverage["website"] = sum(1 for r in enriched_results if r.get("website"))
                                elif pf == "social_media":
                                    field_coverage["social_media"] = sum(
                                        1 for r in enriched_results
                                        if any(r.get("social", {}).values())
                                    )
                            ran_phase2 = True

            # Send completion event AFTER Phase 2 decision (so terminal stays "running")
            from urllib.parse import urlparse as _urlparse2
            _domain = _urlparse2(link).netloc.replace(".", "_")
            structured_file = f"{_domain}_structured.json"
            enriched_file = f"{_domain}_enriched.json" if ran_phase2 else None

            result = {
                "type": "complete",
                "success": phase1_records > 0,
                "records": phase1_records,
                "output_file": enriched_file or structured_file,
            }
            if ran_phase2:
                result["enriched"] = enriched_count
                result["field_coverage"] = field_coverage
            if debug_mode:
                result["debug_entries"] = debug.get_entries()
                result["debug_summary"] = debug.get_summary()
            event_queue.put(result)

        except Exception as e:
            original_print(f"ERROR: {e}")
            event_queue.put({"type": "error", "message": str(e)})
        finally:
            builtins.print = original_print
            event_queue.put(None)  # sentinel — stream ends
            active_sessions.pop(session_id, None)

    thread = threading.Thread(target=bot_thread, daemon=True)
    thread.start()

    def stream():
        yield f"data: {json.dumps({'type': 'session', 'session_id': session_id})}\n\n"
        while True:
            try:
                event = event_queue.get(timeout=600)
                if event is None:
                    break
                yield f"data: {json.dumps(event)}\n\n"
            except queue.Empty:
                break

    return Response(stream(), mimetype="text/event-stream")


@app.route("/scrape/respond", methods=["POST"])
def scrape_respond():
    """Handle interactive input from the frontend terminal (e.g. y/n for detail crawl)."""
    session_id = request.json.get("session_id")
    value = request.json.get("value", "n")

    session = active_sessions.get(session_id)
    if not session:
        return jsonify({"error": "No active session"}), 404

    session["response_value"] = value
    session["response_event"].set()
    return jsonify({"ok": True})


@app.route("/scrape/csv", methods=["POST"])
def scrape_csv():
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "No file"}), 400

    reader = csv.reader(io.StringIO(file.read().decode("utf-8")))
    next(reader)
    links = [row[0].strip() for row in reader if row]

    def stream():
        for i, link in enumerate(links):
            logs = []
            original_print = builtins.print

            def captured_print(*args, **kwargs):
                msg = " ".join(str(a) for a in args)
                logs.append(msg)
                original_print(*args, **kwargs)

            builtins.print = captured_print
            try:
                members = scrape_directory(link)
                records = len(members)
                success = records > 0
            except Exception as e:
                logs.append(f"ERROR: {e}")
                success, records = False, 0
            finally:
                builtins.print = original_print

            yield f"data: {json.dumps({'index': i, 'link': link, 'success': success, 'records': records, 'logs': logs})}\n\n"
        yield 'data: {"done": true}\n\n'

    return Response(stream(), mimetype="text/event-stream")


@app.route("/scraped-sites", methods=["GET"])
def scraped_sites():
    """Return list of sites that have been scraped (based on structured JSON files)."""
    sites = []
    if os.path.isdir(DATA_DUMP):
        for f in sorted(os.listdir(DATA_DUMP)):
            if f.endswith("_structured.json") and not f.endswith("_detail_structured.json"):
                domain = f.replace("_structured.json", "").replace("_", ".")
                # Read the file to get member count
                try:
                    with open(os.path.join(DATA_DUMP, f), "r") as fh:
                        data = json.load(fh)
                        count = len(data) if isinstance(data, list) else 0
                except Exception:
                    count = 0
                sites.append({"domain": domain, "file": f, "count": count})
    return jsonify(sites)


@app.route("/phase2/files", methods=["GET"])
def phase2_files():
    """Return list of structured JSON files with enrichment potential stats."""
    files = []
    if os.path.isdir(DATA_DUMP):
        for f in sorted(os.listdir(DATA_DUMP)):
            if f.endswith("_structured.json") and not f.endswith("_detail_structured.json"):
                try:
                    with open(os.path.join(DATA_DUMP, f)) as fh:
                        data = json.load(fh)
                        if not isinstance(data, list):
                            continue
                        count = len(data)
                        with_website = sum(1 for m in data if m.get("website"))
                        missing_desc = sum(1 for m in data if m.get("website") and not m.get("description"))
                        missing_phone = sum(1 for m in data if m.get("website") and not m.get("phone"))
                        missing_email = sum(1 for m in data if m.get("website") and not any(c.get("email") for c in m.get("contacts", [])))
                        missing_addr = sum(1 for m in data if m.get("website") and not m.get("street_address"))
                except Exception:
                    continue
                files.append({
                    "file": f,
                    "count": count,
                    "with_website": with_website,
                    "missing_desc": missing_desc,
                    "missing_phone": missing_phone,
                    "missing_email": missing_email,
                    "missing_addr": missing_addr,
                })
    return jsonify(files)


@app.route("/phase2/enrich", methods=["POST"])
def phase2_enrich():
    """Run Phase 2 enrichment on a structured JSON file. Streams SSE progress."""
    json_file = request.json.get("json_file", "").strip()
    if not json_file:
        return jsonify({"error": "No file specified"}), 400

    json_path = os.path.join(DATA_DUMP, json_file)
    if not os.path.isfile(json_path):
        return jsonify({"error": f"File not found: {json_file}"}), 404

    session_id = str(uuid.uuid4())
    event_queue = queue.Queue()

    active_sessions[session_id] = {
        "queue": event_queue,
        "response_event": threading.Event(),
        "response_value": None,
    }

    def enrich_thread():
        original_print = builtins.print

        def captured_print(*args, **kwargs):
            msg = " ".join(str(a) for a in args)
            original_print(*args, **kwargs)
            if is_important_message(msg):
                event_queue.put({
                    "type": "log",
                    "message": msg.strip(),
                    "category": classify_message(msg),
                })

        builtins.print = captured_print
        try:
            output_path = enrich_from_websites(json_path)
            with open(output_path) as f:
                results = json.load(f)
            enriched_count = sum(1 for r in results if r.get("enrichment_status") == "enriched")
            event_queue.put({
                "type": "complete",
                "success": enriched_count > 0,
                "records": len(results),
                "enriched": enriched_count,
                "output_file": os.path.basename(output_path),
            })
        except Exception as e:
            original_print(f"ERROR: {e}")
            event_queue.put({"type": "error", "message": str(e)})
        finally:
            builtins.print = original_print
            event_queue.put(None)
            active_sessions.pop(session_id, None)

    thread = threading.Thread(target=enrich_thread, daemon=True)
    thread.start()

    def stream():
        yield f"data: {json.dumps({'type': 'session', 'session_id': session_id})}\n\n"
        while True:
            try:
                event = event_queue.get(timeout=600)
                if event is None:
                    break
                yield f"data: {json.dumps(event)}\n\n"
            except queue.Empty:
                break

    return Response(stream(), mimetype="text/event-stream")


# --- PHASE 0: DISCOVERY → AUTO-SCRAPE ---


@app.route("/discover", methods=["POST"])
def discover():
    """Phase 0 source discovery → auto-scrape via Phase 1.

    Takes {"goal": "<free-form text>", "priority_fields": [...]}.
    Streams SSE events:
      - Phase 0 progress: stage / intent_parsed / discovery_query /
        preflight_result / classified / discovery_complete
      - Phase 1 progress (per directory): scrape_started / log / scrape_done
      - Final: complete
    """
    goal = (request.json.get("goal") or "").strip()
    priority_fields = request.json.get("priority_fields") or ["email", "phone"]
    if not goal:
        return jsonify({"error": "No goal provided"}), 400

    session_id = str(uuid.uuid4())
    event_queue = queue.Queue()

    active_sessions[session_id] = {
        "queue": event_queue,
        "response_event": threading.Event(),
        "response_value": None,
    }

    def discover_thread():
        original_print = builtins.print

        def captured_print(*args, **kwargs):
            msg = " ".join(str(a) for a in args)
            original_print(*args, **kwargs)
            if is_important_message(msg):
                event_queue.put({
                    "type": "log",
                    "message": msg.strip(),
                    "category": classify_message(msg),
                })

        builtins.print = captured_print

        def emit(event):
            """Push a structured event into the SSE queue."""
            event_queue.put(event)

        try:
            # --- Phase 0: Discovery ---
            result = run_discovery(goal, event_cb=emit)

            # If intent parsing said the message wasn't actionable, the
            # pipeline already emitted a needs_clarification event. Stop
            # cleanly so the stream closes and the user can reply again.
            if result.get("needs_clarification"):
                return

            directories = result.get("directories", [])
            websites = result.get("websites", [])

            if not directories and not websites:
                event_queue.put({
                    "type": "complete",
                    "success": False,
                    "message": "No scrapable sources found for that goal.",
                    "directories_scraped": 0,
                    "records": 0,
                    "output_files": [],
                    "websites": [],
                    "stats": {
                        "rejected_count": result.get("rejected_count", 0),
                        "reject_reasons": result.get("reject_reasons", {}),
                    },
                })
                return

            # --- User confirmation gate ---
            # Even when Phase 0 finds directories, give the user a chance to
            # deselect ones they don't want before we burn time and tokens
            # scraping them. We reuse the existing /scrape/respond plumbing
            # (session_id + response_event) — the frontend posts the list of
            # approved URLs as a JSON-encoded string in `value`.
            if directories:
                session_obj = active_sessions.get(session_id)
                event_queue.put({
                    "type": "confirmation_required",
                    "directories": [
                        {
                            "url": d["url"],
                            "title": d.get("title", ""),
                            "needs_navigation": d.get("needs_navigation", False),
                        }
                        for d in directories
                    ],
                    "websites": [
                        {"url": w["url"], "title": w.get("title", "")}
                        for w in websites
                    ],
                })

                # Block up to 10 minutes for the user to choose. If they
                # close the tab or wait too long, treat it as "skip".
                if session_obj:
                    session_obj["response_event"].wait(timeout=600)
                    response_value = session_obj.get("response_value") or ""
                    session_obj["response_event"].clear()
                    session_obj["response_value"] = None
                else:
                    response_value = ""

                # Parse the response. Expected shapes:
                #   "skip" / "cancel" / "" → user bailed
                #   "all"                  → scrape every directory
                #   JSON list of URLs      → scrape just those
                rv = (response_value or "").strip()
                selected_urls: set[str] | None = None

                if rv.lower() in ("skip", "cancel", "", "n", "no"):
                    selected_urls = set()
                elif rv.lower() in ("all", "y", "yes"):
                    selected_urls = {d["url"] for d in directories}
                else:
                    try:
                        parsed = json.loads(rv)
                        if isinstance(parsed, list):
                            selected_urls = {str(u) for u in parsed}
                    except (json.JSONDecodeError, TypeError):
                        selected_urls = set()

                if not selected_urls:
                    event_queue.put({
                        "type": "complete",
                        "success": False,
                        "message": "Cancelled — no directories selected.",
                        "directories_scraped": 0,
                        "records": 0,
                        "output_files": [],
                        "websites": [w["url"] for w in websites],
                        "per_site": [],
                        "stats": {
                            "rejected_count": result.get("rejected_count", 0),
                            "reject_reasons": result.get("reject_reasons", {}),
                        },
                    })
                    return

                directories = [d for d in directories if d["url"] in selected_urls]
                event_queue.put({
                    "type": "confirmation_accepted",
                    "selected_count": len(directories),
                })

            # --- Phase 1: Auto-scrape each directory ---
            # We pass mode="direct" because Phase 0 already verified card
            # structure exists on the URL. Prompts are auto-declined (batch
            # mode — no human in the loop for detail crawl or Phase 2).
            #
            # Agent mode also passes the parsed intent through, so Phase 1's
            # AI navigator can pick intent-relevant sub-directory links and
            # the category iterator can narrow to matching tabs (e.g. only
            # "Restaurants, Food & Beverages" on a multi-category chamber).
            # The Playground endpoints (/scrape/single, /scrape/csv) do NOT
            # pass intent — their behavior is unchanged.
            intent = intent_from_plan(result.get("plan"))
            output_files = []
            total_records = 0
            per_site_results = []

            def auto_decline(detail_url_count, message=None):
                return False

            def _check_skip():
                """Check if the user requested a skip via the frontend."""
                session = active_sessions.get(session_id)
                if not session:
                    return False
                val = (session.get("response_value") or "").strip().lower()
                if val == "skip":
                    session["response_value"] = None
                    session["response_event"].clear()
                    return True
                return False

            for i, d in enumerate(directories):
                url = d["url"]
                # Always use auto mode. Phase 0 verified the URL belongs to
                # a directory site, but the actual listing may be one click
                # away (when DDG returned the homepage). Phase 1's AI
                # navigator handles both cases uniformly.
                scrape_mode = "auto"

                # --- Skip gate: user can abort this directory before Phase 1 ---
                if _check_skip():
                    event_queue.put({
                        "type": "scrape_skipped",
                        "index": i,
                        "total": len(directories),
                        "url": url,
                        "reason": "user_skipped",
                    })
                    continue

                event_queue.put({
                    "type": "scrape_started",
                    "index": i,
                    "total": len(directories),
                    "url": url,
                    "mode": scrape_mode,
                })

                try:
                    members = scrape_directory(
                        url,
                        prompt_callback=auto_decline,
                        mode=scrape_mode,
                        priority_fields=priority_fields,
                        intent=intent,
                    )

                    from urllib.parse import urlparse as _urlparse
                    domain = _urlparse(url).netloc.replace(".", "_")
                    structured_file = f"{domain}_structured.json"
                    structured_path = os.path.join(DATA_DUMP, structured_file)
                    record_count = len(members)
                    total_records += record_count

                    # --- Auto Phase 2 enrichment on each successful scrape ---
                    enriched_count = 0
                    output_file = structured_file
                    if members and os.path.isfile(structured_path):
                        # Re-check skip before expensive Phase 2
                        if _check_skip():
                            event_queue.put({
                                "type": "log",
                                "message": f"Skipping Phase 2 enrichment for {url} (user requested skip)",
                                "category": "LOG",
                            })
                        else:
                            event_queue.put({
                                "type": "log",
                                "message": f"Starting Phase 2 enrichment for {url}...",
                                "category": "LOG",
                            })
                            try:
                                enriched_path = enrich_from_websites(structured_path)
                                output_file = os.path.basename(enriched_path)
                                with open(enriched_path) as ef:
                                    enriched_results = json.load(ef)
                                enriched_count = sum(
                                    1 for r in enriched_results
                                    if r.get("enrichment_status") == "enriched"
                                )
                            except Exception as e:
                                event_queue.put({
                                    "type": "log",
                                    "message": f"Phase 2 failed for {url}: {e}",
                                    "category": "ERROR",
                                })

                    output_files.append(output_file)
                    per_site_results.append({
                        "url": url,
                        "records": record_count,
                        "enriched": enriched_count,
                        "output_file": output_file,
                    })

                    event_queue.put({
                        "type": "scrape_done",
                        "index": i,
                        "total": len(directories),
                        "url": url,
                        "records": record_count,
                        "enriched": enriched_count,
                        "output_file": output_file,
                    })
                except Exception as e:
                    event_queue.put({
                        "type": "scrape_error",
                        "index": i,
                        "total": len(directories),
                        "url": url,
                        "error": str(e),
                    })

            event_queue.put({
                "type": "complete",
                "success": total_records > 0,
                "records": total_records,
                "directories_scraped": len(directories),
                "websites_found": len(websites),
                "websites": [w["url"] for w in websites],
                "output_files": output_files,
                "per_site": per_site_results,
                "stats": {
                    "rejected_count": result.get("rejected_count", 0),
                    "reject_reasons": result.get("reject_reasons", {}),
                },
            })
        except Exception as e:
            original_print(f"ERROR: {e}")
            event_queue.put({"type": "error", "message": str(e)})
        finally:
            builtins.print = original_print
            event_queue.put(None)  # sentinel
            active_sessions.pop(session_id, None)

    thread = threading.Thread(target=discover_thread, daemon=True)
    thread.start()

    def stream():
        yield f"data: {json.dumps({'type': 'session', 'session_id': session_id})}\n\n"
        while True:
            try:
                event = event_queue.get(timeout=600)
                if event is None:
                    break
                yield f"data: {json.dumps(event)}\n\n"
            except queue.Empty:
                break

    return Response(stream(), mimetype="text/event-stream")


# --- CSV CONVERSION & DOWNLOAD ---

# Column order for CSV — most important fields first
_CSV_COLUMNS = [
    "company_name", "category", "website",
    "phone", "fax",
    "contact_name", "contact_email",
    "street_address", "mailing_address",
    "description",
    # Phase 2 enrichment fields
    "facebook", "linkedin", "instagram", "twitter", "youtube", "yelp", "pinterest", "tiktok",
    "hours", "services", "founded",
    "team",
    "enrichment_status", "enrichment_source", "website_source",
]


def _flatten_record(record: dict) -> dict:
    """Flatten a nested member record into a single-level dict for CSV.
    Contacts get merged into contact_name/contact_email (semicolon-separated if multiple).
    Social media gets flattened from nested dict to top-level keys.
    Lists (services, team) get joined into comma-separated strings."""
    row = {}

    # Simple fields — copy directly
    for key in ("company_name", "category", "website", "phone", "fax",
                "street_address", "mailing_address", "description",
                "hours", "founded", "enrichment_status", "enrichment_source", "website_source"):
        val = record.get(key)
        row[key] = str(val).strip() if val else ""

    # Contacts — flatten into semicolon-separated name/email
    contacts = record.get("contacts", [])
    if contacts and isinstance(contacts, list):
        names = [c.get("name", "") for c in contacts if c.get("name")]
        emails = [c.get("email", "") for c in contacts if c.get("email")]
        row["contact_name"] = "; ".join(names)
        row["contact_email"] = "; ".join(emails)
    else:
        row["contact_name"] = ""
        row["contact_email"] = ""

    # Social media — flatten nested dict
    social = record.get("social_media", {}) or {}
    for platform in ("facebook", "linkedin", "instagram", "twitter", "youtube", "yelp", "pinterest", "tiktok"):
        row[platform] = social.get(platform, "") or ""

    # Services — join list
    services = record.get("services", [])
    row["services"] = ", ".join(services) if isinstance(services, list) else str(services or "")

    # Team — flatten to "Name (Title); Name (Title)"
    team = record.get("team", [])
    if team and isinstance(team, list):
        parts = []
        for member in team:
            if isinstance(member, dict):
                name = member.get("name", "")
                title = member.get("title", "")
                parts.append(f"{name} ({title})" if title else name)
            elif isinstance(member, str):
                parts.append(member)
        row["team"] = "; ".join(parts)
    else:
        row["team"] = ""

    return row


def _records_to_csv(records: list) -> str:
    """Convert a list of member records to CSV string."""
    output = io.StringIO()

    # Determine which columns actually have data (skip empty columns)
    columns_with_data = []
    flat_records = [_flatten_record(r) for r in records]
    for col in _CSV_COLUMNS:
        if any(row.get(col) for row in flat_records):
            columns_with_data.append(col)

    writer = csv.DictWriter(output, fieldnames=columns_with_data, extrasaction="ignore")
    writer.writeheader()
    for row in flat_records:
        writer.writerow(row)

    return output.getvalue()


@app.route("/download/<path:filename>", methods=["GET"])
def download_file(filename):
    """Download a structured or enriched JSON file as JSON or CSV.
    Query param: ?format=csv or ?format=json (default: json)"""
    fmt = request.args.get("format", "json").lower()

    # Check both Data-dump and Phase2-Dump directories
    file_path = None
    for directory in (DATA_DUMP, PHASE2_DUMP):
        candidate = os.path.join(directory, filename)
        if os.path.isfile(candidate):
            file_path = candidate
            break

    if not file_path:
        return jsonify({"error": f"File not found: {filename}"}), 404

    try:
        with open(file_path) as f:
            data = json.load(f)
    except Exception as e:
        return jsonify({"error": f"Failed to read file: {e}"}), 500

    if not isinstance(data, list):
        return jsonify({"error": "File does not contain a list of records"}), 400

    if fmt == "csv":
        csv_content = _records_to_csv(data)
        csv_filename = filename.rsplit(".", 1)[0] + ".csv"
        return Response(
            csv_content,
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={csv_filename}"},
        )
    else:
        return Response(
            json.dumps(data, indent=2, ensure_ascii=False),
            mimetype="application/json",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )


if __name__ == "__main__":
    app.run(host="localhost", port=5000, debug=False, threaded=True)

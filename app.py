from flask import Flask, request, jsonify, Response, send_file
from flask_cors import CORS
import sys, os, csv, json, io, builtins, queue, threading, time, uuid, re, traceback

os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"

# Add the Bot directory to the path so Python can find the scraper modules
sys.path.append(os.path.join(os.path.dirname(__file__), "Bot"))

from Bot.main import scrape_directory, PHASE2_ONLY_FIELDS, read_members, read_metadata
from Bot.debug import debug
from Bot.intent_filter import intent_from_plan
# Bare import (Bot/ is on sys.path via the append above) so this resolves to the
# SAME top-level `live_view` module that Bot/browser.py imports — one shared
# registry. Importing it as `Bot.live_view` would create a second instance.
from live_view import live
from Phase2Bot.email_extractor import enrich_from_websites
from DiscoveryBot import run_discovery, parse_intent
from exporter import export_final_dataset, records_to_csv
from analytics import record_page_view, record_event, get_stats

app = Flask(__name__)

# CORS: allow localhost dev servers + any custom origins set via env var.
# When nginx serves frontend and API from the same domain, CORS is a no-op.
_cors_origins_env = os.environ.get("CORS_ORIGINS", "")
_cors_origins = (
    [o.strip() for o in _cors_origins_env.split(",") if o.strip()]
    if _cors_origins_env
    else ["http://localhost:3000", "http://localhost:3001", "http://localhost:3002"]
)
CORS(app,
    origins=_cors_origins,
    methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Custom-Header"],
    supports_credentials=True)

DATA_DUMP = os.path.join(os.path.dirname(__file__), "Data-dump")
PHASE2_DUMP = os.path.join(os.path.dirname(__file__), "Phase2-Dump")
DEBUG_DUMP = os.path.join(os.path.dirname(__file__), "Debug-dump")

# Active scrape sessions for interactive prompts
# {session_id: {"queue": Queue, "response_event": Event, "response_value": str}}
active_sessions = {}


def _same_site_hint(base_url: str, raw_href: str) -> str | None:
    """Resolve Phase 0's landing_link href against the page it was found on.

    Returns an absolute http(s) URL only when it stays on the same site
    (subdomains ok) — a footer link to an external 'directory' must not
    teleport the scrape off-site. None on any mismatch or parse failure.
    """
    from urllib.parse import urljoin, urlparse
    try:
        cand = urljoin(base_url, raw_href)
        if not cand.startswith(("http://", "https://")):
            return None
        base_host = urlparse(base_url).netloc.lower().removeprefix("www.")
        hint_host = urlparse(cand).netloc.lower().removeprefix("www.")
        if not base_host or not hint_host:
            return None
        if hint_host == base_host or hint_host.endswith("." + base_host):
            return cand
    except Exception:
        pass
    return None


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
        members = read_members(json_path)
        if not members:
            return fields
        sample = members[:20]
        n = len(sample)
        threshold = max(1, n // 2)  # ≥50% of the sample must have it

        def _count(predicate):
            return sum(1 for m in sample if predicate(m))

        # Person-schema records carry email/personal_website at the top level
        # (no contacts list); business records never have those keys, so the
        # extra checks are no-ops for them.
        if _count(lambda m: bool(m.get("phone"))) >= threshold:
            fields.add("phone")
        if _count(lambda m: bool(m.get("email"))
                  or any(c.get("email") for c in m.get("contacts", []))) >= threshold:
            fields.add("email")
        if _count(lambda m: bool(m.get("street_address") or m.get("mailing_address"))) >= threshold:
            fields.add("address")
        if _count(lambda m: bool(m.get("description"))) >= threshold:
            fields.add("description")
        if _count(lambda m: bool(m.get("website") or m.get("personal_website"))) >= threshold:
            fields.add("website")
    except Exception:
        pass
    return fields


def _normalize_link(raw: str) -> tuple[str | None, str | None]:
    """Clean up a user-pasted URL. Returns (link, error) — exactly one is set.

    Users paste links wrapped in <>/quotes (email, Slack), with uppercase or
    missing schemes, or scheme-relative (//host/path). Anything that still
    has no plausible host afterwards gets a readable error instead of being
    handed to the browser, where it grinds against about:blank for minutes
    and then reports a misleading "0 members".
    """
    from urllib.parse import urlparse

    link = (raw or "").strip().strip("<>\"'").strip()
    if not link:
        return None, "No link provided"
    if link.startswith("//"):  # scheme-relative paste
        link = "https:" + link

    scheme_match = re.match(r"^([a-zA-Z][a-zA-Z0-9+.-]*)://(.*)$", link)
    if scheme_match:
        scheme = scheme_match.group(1).lower()
        if scheme not in ("http", "https"):
            return None, f"Unsupported URL scheme '{scheme}' — only http(s) pages can be scraped"
        link = f"{scheme}://{scheme_match.group(2)}"
    else:
        link = "https://" + link

    parsed = urlparse(link)
    try:
        hostname = parsed.hostname or ""
    except ValueError:  # e.g. malformed IPv6 bracket syntax
        hostname = ""
    if not hostname or " " in parsed.netloc:
        return None, f"'{raw.strip()}' doesn't look like a valid URL"
    # Require a dot (domain), a colon (IPv6), or localhost — bare words like
    # "hoa directory texas" are search queries, not scrape targets.
    if "." not in hostname and ":" not in hostname and hostname != "localhost":
        return None, (f"'{raw.strip()}' doesn't look like a valid URL — "
                      f"paste the full address of the directory page")
    return link, None


def _sse_error_response(message: str) -> Response:
    """One-shot SSE stream carrying a single error event. The frontend
    terminal renders `error` events with their message; a bare 400 would
    surface only as "Error: 400 BAD REQUEST" with no explanation."""
    def stream():
        yield f"data: {json.dumps({'type': 'error', 'message': message})}\n\n"
    return Response(stream(), mimetype="text/event-stream")


def _emit_paused(event_queue, session_id, reason, message, vendor=None):
    """Tell the main scrape stream the run has paused for a human. Emits BOTH a
    human-readable log line (so the terminal shows it even with no new frontend
    handling) and a structured `paused` event the Live View UI reacts to
    (flash the button, flip to interactive). Also flips the live session's
    status so a stream already open updates immediately."""
    live.set_status(session_id, reason, vendor=vendor)
    event_queue.put({"type": "log", "message": f"⏸ {message}", "category": "SYSTEM"})
    event_queue.put({
        "type": "paused",
        "reason": reason,
        "vendor": vendor,
        "message": message,
        "session_id": session_id,
    })


def _emit_resumed(event_queue, session_id):
    """Counterpart to _emit_paused — the human resumed or skipped."""
    live.set_status(session_id, "running")
    event_queue.put({"type": "resumed", "session_id": session_id})


@app.route("/scrape/single", methods=["POST"])
def scrape_single():
    """Stream scrape progress as SSE events. Supports interactive prompts."""
    raw_link = request.json.get("link", "")
    debug_mode = request.json.get("debug", False)
    scrape_mode = request.json.get("mode", "auto")  # "auto" or "direct"
    priority_fields = request.json.get("priority_fields", ["email", "phone"])
    accurate_enrichment = bool(request.json.get("accurate_enrichment", False))
    # Optional Auto-Discover intent: free-form "what to discover on this site".
    # Only used in auto mode; direct scrapes ignore it. Empty / "everything"
    # goals resolve to intent=None (parse_intent → coverage:"all"), i.e. the
    # unchanged plain auto-discover flow.
    goal = (request.json.get("goal") or "").strip()
    if not (raw_link or "").strip():
        return jsonify({"error": "No link"}), 400

    link, url_error = _normalize_link(raw_link)
    if url_error:
        return _sse_error_response(url_error)

    session_id = str(uuid.uuid4())
    event_queue = queue.Queue()
    response_event = threading.Event()

    active_sessions[session_id] = {
        "queue": event_queue,
        "response_event": response_event,
        "response_value": None,
    }
    # Enable Live View for this run: binds the scraper's browser page (created
    # later, deep in capture_responses) to this session id so the frontend can
    # stream it and take control during a pause. Torn down in the finally below.
    live.register(session_id)

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
        # `or "n"` (not a .get default): the key always exists and is None on
        # timeout / after a reset — .get's default never applies, and
        # None.lower() used to kill the whole scrape thread here.
        answer = str(session.get("response_value") or "n")
        session["response_event"].clear()
        session["response_value"] = None  # reset for next prompt
        return answer.lower() in ("y", "yes")

    def login_via_frontend(page, domain):
        """Login-wall handler for the web UI. On a headless VPS there's no
        visible browser window, so the user drives it through Live View: the
        run pauses, they open Live View, log in inside the streamed page, then
        press Resume. Returns True to re-verify/continue, False to skip."""
        _emit_paused(event_queue, session_id, "login",
                     f"Login wall on {domain.replace('_', '.')} — open Live View, "
                     f"log in inside the page, then press Resume.")
        cont = live.control_until_resume(session_id, page, reason="login")
        _emit_resumed(event_queue, session_id)
        return cont

    def captcha_via_frontend(page, domain, vendor):
        """CAPTCHA / anti-bot-challenge handler for the web UI. The scraper
        pauses here; the user opens Live View, solves the challenge inside the
        streamed page (click tiles / press & hold), then presses Resume.
        Returns True to re-check/resume, False to skip this site."""
        _emit_paused(event_queue, session_id, "captcha",
                     f"{vendor} challenge detected on {domain.replace('_', '.')} — "
                     f"the scraper is PAUSED. Open Live View to solve it, then "
                     f"press Resume.", vendor=vendor)
        cont = live.control_until_resume(session_id, page, reason="captcha",
                                         vendor=vendor)
        _emit_resumed(event_queue, session_id)
        return cont

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
            # Auto-Discover intent (single-URL): parse the user's free-form
            # goal into the same flattened intent the /discover path uses, so
            # this scrape gets intent-driven sub-page discovery, XHR replay,
            # category narrowing, and record filtering. Direct mode and empty/
            # "everything" goals leave intent=None (unchanged behavior).
            intent = None
            if scrape_mode == "auto" and goal:
                try:
                    intent = intent_from_plan(parse_intent(goal))
                except Exception as e:
                    print(f"  Intent parse failed (non-fatal, scraping everything): {e}")
                    intent = None

            members = scrape_directory(
                link, prompt_callback=prompt_via_frontend,
                mode=scrape_mode, priority_fields=priority_fields,
                intent=intent,
                login_callback=login_via_frontend,
                captcha_callback=captcha_via_frontend,
                live_session_id=session_id,
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
                            output_path = enrich_from_websites(
                                structured_path,
                                accurate_enrichment=accurate_enrichment,
                            )
                            with open(output_path) as ef:
                                enriched_results = read_members(output_path)
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
            # Additive (Phase 2 count gate): surface a short-count scrape
            # next to field_coverage — no event renames.
            try:
                _meta = read_metadata(os.path.join(DATA_DUMP, structured_file))
            except Exception:
                _meta = None
            if _meta and _meta.get("partial"):
                result["partial"] = True
                result["expected_count"] = _meta.get("expected_count")
            if debug_mode:
                result["debug_entries"] = debug.get_entries()
                result["debug_summary"] = debug.get_summary()
            event_queue.put(result)

        except Exception as e:
            # Full traceback to the server log — the bare message alone made
            # crashes like "'NoneType' object has no attribute 'lower'"
            # undebuggable from journalctl.
            original_print(f"ERROR: {e}\n{traceback.format_exc()}")
            event_queue.put({"type": "error", "message": str(e)})
        finally:
            builtins.print = original_print
            live.unregister(session_id)  # tear down Live View for this run
            event_queue.put(None)  # sentinel — stream ends
            active_sessions.pop(session_id, None)

    thread = threading.Thread(target=bot_thread, daemon=True)
    thread.start()

    def stream():
        yield f"data: {json.dumps({'type': 'session', 'session_id': session_id})}\n\n"
        while True:
            try:
                event = event_queue.get(timeout=15)
                if event is None:
                    break
                yield f"data: {json.dumps(event)}\n\n"
            except queue.Empty:
                # No scraper output for a while (e.g. a long silent detail crawl):
                # send an SSE comment as a keepalive so nginx / the browser don't
                # drop the idle connection. Both frontend parsers skip frames that
                # don't start with "data: ". Only the None sentinel ends the stream.
                yield ": keepalive\n\n"

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
    next(reader, None)  # header row; empty file must not raise StopIteration
    links = [row[0].strip() for row in reader if row and row[0].strip()]

    def stream():
        for i, raw_link in enumerate(links):
            link, url_error = _normalize_link(raw_link)
            if url_error:
                yield f"data: {json.dumps({'index': i, 'link': raw_link, 'success': False, 'records': 0, 'logs': [url_error]})}\n\n"
                continue

            logs = []
            original_print = builtins.print

            def captured_print(*args, **kwargs):
                msg = " ".join(str(a) for a in args)
                logs.append(msg)
                original_print(*args, **kwargs)

            builtins.print = captured_print
            try:
                # Batch endpoint: auto-decline interactive prompts. The default
                # handlers fall back to terminal input(), which hangs the server
                # thread forever — nobody is at Flask's stdin.
                members = scrape_directory(
                    link,
                    prompt_callback=lambda count, message=None: False,
                    login_callback=lambda page, domain: False,
                )
                records = len(members)
                success = records > 0
            except Exception as e:
                logs.append(f"ERROR: {e}")
                original_print(f"ERROR: {e}\n{traceback.format_exc()}")
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
                    data = read_members(os.path.join(DATA_DUMP, f))
                    count = len(data)
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
                    data = read_members(os.path.join(DATA_DUMP, f))
                    if not data:
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
    accurate_enrichment = bool(request.json.get("accurate_enrichment", False))
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
            output_path = enrich_from_websites(
                json_path,
                accurate_enrichment=accurate_enrichment,
            )
            with open(output_path) as f:
                results = read_members(output_path)
            enriched_count = sum(1 for r in results if r.get("enrichment_status") == "enriched")
            event_queue.put({
                "type": "complete",
                "success": enriched_count > 0,
                "records": len(results),
                "enriched": enriched_count,
                "output_file": os.path.basename(output_path),
            })
        except Exception as e:
            original_print(f"ERROR: {e}\n{traceback.format_exc()}")
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
                event = event_queue.get(timeout=15)
                if event is None:
                    break
                yield f"data: {json.dumps(event)}\n\n"
            except queue.Empty:
                # No scraper output for a while (e.g. a long silent detail crawl):
                # send an SSE comment as a keepalive so nginx / the browser don't
                # drop the idle connection. Both frontend parsers skip frames that
                # don't start with "data: ". Only the None sentinel ends the stream.
                yield ": keepalive\n\n"

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
    # No priority fields selected = "give me everything": every detected
    # detail page gets crawled unconditionally (crawl_all). The email/phone
    # default still stands in for the Phase 2 enrichment decisions below —
    # it no longer gates the detail crawl.
    requested_fields = request.json.get("priority_fields")
    crawl_all = not requested_fields
    priority_fields = requested_fields or ["email", "phone"]
    accurate_enrichment = bool(request.json.get("accurate_enrichment", False))
    if not goal:
        return jsonify({"error": "No goal provided"}), 400

    session_id = str(uuid.uuid4())
    event_queue = queue.Queue()

    active_sessions[session_id] = {
        "queue": event_queue,
        "response_event": threading.Event(),
        "response_value": None,
    }
    # Live View for the Agent run too — each per-site scrape below binds its
    # browser page to this session id. Torn down in the finally.
    live.register(session_id)

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

        # Full-run debug trace, always on for /discover: Phase 0 saves one
        # timeline file per run, then each Phase 1 scrape resets and saves its
        # own Debug-dump/{domain}_debug.json (see Bot/main.py). Every entry
        # carries elapsed time; spans carry durations; decisions carry the why.
        debug.enabled = True
        debug.reset()

        def emit(event):
            """Push a structured event into the SSE queue."""
            event_queue.put(event)

        def ask_scope(plan):
            """Blocking frontend prompt: specialists-only vs anyone-who-does-it.

            Asked AFTER discovery (so searching never waits on it) and only when
            intent parsing flagged the goal as scope-ambiguous. Reuses the same
            response_event + /scrape/respond plumbing as the directory-selection
            gate. The frontend posts the literal token "specialist" or
            "inclusive". Anything else (timeout, tab closed, garbage) falls open
            to "inclusive".
            """
            session_obj = active_sessions.get(session_id)
            event_queue.put({
                "type": "scope_refinement_required",
                "question": plan.get("scope_question")
                or "Do you want specialists only, or anyone who does this work?",
                "options": plan.get("scope_options")
                or ["Specialists only", "Anyone who does it"],
            })
            if not session_obj:
                return "inclusive"
            got = session_obj["response_event"].wait(timeout=600)
            rv = (session_obj.get("response_value") or "").strip().lower()
            session_obj["response_event"].clear()
            session_obj["response_value"] = None
            if got and rv == "specialist":
                return "specialist"
            return "inclusive"

        try:
            # --- Phase 0: Discovery (independent of scope — see run_discovery) ---
            result = run_discovery(goal, event_cb=emit)

            # Persist the Phase 0 trace now — each Phase 1 scrape resets the
            # logger for its own per-site trace file.
            debug.save_report(os.path.join(
                DEBUG_DUMP, f"discover_{int(time.time())}_phase0_debug.json"))

            # If intent parsing said the message wasn't actionable, the
            # pipeline already emitted a needs_clarification event. Stop
            # cleanly so the stream closes and the user can reply again.
            if result.get("needs_clarification"):
                return

            # --- API route: authoritative data, no scraping ---
            # Phase 0 decided this goal is answerable by a public registry
            # (currently NPI for US healthcare practitioners). No DDG, no
            # browser, no source picker — fetch, save in the standard
            # structured format, emit complete.
            if result.get("api_vertical") == "npi":
                from Phase2Bot.vertical_enrichment import npi_search_by_taxonomy
                from datetime import datetime as _dt, timezone as _tz
                ap = result.get("api_params") or {}
                term = ap.get("term") or "providers"
                state = ap.get("state") or ""
                city = ap.get("city")

                def _npi_progress(n):
                    event_queue.put({
                        "type": "stage", "stage": "api_route",
                        "message": f"NPI registry: {n} {term} found so far...",
                    })

                try:
                    members, hit_ceiling = npi_search_by_taxonomy(
                        ap.get("taxonomy_queries") or [], state, city=city,
                        progress_cb=_npi_progress,
                    )
                except Exception as e:
                    event_queue.put({"type": "error", "message": f"NPI lookup failed: {e}"})
                    return

                if hit_ceiling:
                    event_queue.put({
                        "type": "stage", "stage": "api_route",
                        "message": (f"Hit the NPI API's ~1,200-record cap for {term} in "
                                    f"{state} — results are partial. Narrow by city for the rest."),
                    })

                loc_slug = (f"{state}_{city}" if city else state).replace(" ", "_")
                fname = f"npi_{term}_{loc_slug}_structured.json".lower().replace(" ", "_")
                struct_path = os.path.join(DATA_DUMP, fname)
                os.makedirs(DATA_DUMP, exist_ok=True)
                metadata = {
                    "scraped_at": _dt.now(_tz.utc).isoformat(),
                    "source_url": "npi_registry_api",
                    "total_members": len(members),
                    "with_name": sum(1 for m in members if m.get("company_name")),
                    "with_phone": sum(1 for m in members if m.get("phone")),
                    "with_address": sum(1 for m in members
                                        if m.get("street_address") or m.get("mailing_address")),
                    "with_category": sum(1 for m in members if m.get("category")),
                    "partial_results": hit_ceiling,
                }
                with open(struct_path, "w") as f:
                    json.dump({"metadata": metadata, "members": members}, f, indent=4)

                # Same final deliverable as the scrape path (cleaned JSON +
                # Excel) — the frontend result bubble only renders download
                # links off final_json/final_xlsx, so without this the NPI
                # route produced a file the UI never surfaced.
                npi_final_json = None
                npi_final_xlsx = None
                if members:
                    try:
                        export_info = export_final_dataset(
                            [fname], [DATA_DUMP], DATA_DUMP,
                            fname.rsplit("_structured.json", 1)[0],
                            goal=goal, industry=term, locations=[state],
                        )
                        if export_info:
                            npi_final_json = export_info["json_file"]
                            npi_final_xlsx = export_info.get("xlsx_file")
                    except Exception as e:
                        event_queue.put({
                            "type": "log",
                            "message": f"Final export failed (structured file unaffected): {e}",
                            "category": "ERROR",
                        })

                where = f"{term} in {state}" + (f", {city}" if city else "")
                event_queue.put({
                    "type": "complete",
                    "success": len(members) > 0,
                    "records": len(members),
                    "directories_scraped": 0,
                    "websites_found": 0,
                    "websites": [],
                    "output_files": [fname],
                    "merged_file": npi_final_json,
                    "final_json": npi_final_json,
                    "final_xlsx": npi_final_xlsx,
                    "per_site": [{
                        "url": f"NPI registry — {where}",
                        "records": len(members),
                        "enriched": 0,
                        "output_file": fname,
                    }],
                    "stats": {"rejected_count": 0, "reject_reasons": {}},
                })
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

            # --- Scope refinement (AFTER discovery) ---
            # Only ask once we know there are directories to scrape, and only
            # when the goal was scope-ambiguous. Stored on the plan so it flows
            # into Phase 1 via intent_from_plan. Asked before the directory
            # picker so the sequence reads: "here's what I found → specialists
            # or anyone? → pick which to scrape".
            plan = result.get("plan") or {}
            if directories and plan.get("scope_ambiguous"):
                plan["scope"] = ask_scope(plan)

            # --- User confirmation gate ---
            # Even when Phase 0 finds directories, give the user a chance to
            # deselect ones they don't want before we burn time and tokens
            # scraping them. We reuse the existing /scrape/respond plumbing
            # (session_id + response_event) — the frontend posts the list of
            # approved URLs as a JSON-encoded string in `value`.
            # Standalone (single-business) sites the user opts to scrape.
            # Populated from the same confirmation gate as directories.
            selected_web_urls: list[str] = []

            if directories or websites:
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
                #   "all"                  → every directory + every site
                #   JSON list of URLs      → just those. The list mixes
                #     directory and standalone-site URLs; we partition each
                #     URL by which set it came from.
                rv = (response_value or "").strip()
                dir_url_set = {d["url"] for d in directories}
                web_url_set = {w["url"] for w in websites}

                if rv.lower() in ("skip", "cancel", "", "n", "no"):
                    selected: set[str] = set()
                elif rv.lower() in ("all", "y", "yes"):
                    selected = dir_url_set | web_url_set
                else:
                    try:
                        parsed = json.loads(rv)
                        selected = {str(u) for u in parsed} if isinstance(parsed, list) else set()
                    except (json.JSONDecodeError, TypeError):
                        selected = set()

                directories = [d for d in directories if d["url"] in selected]
                selected_web_urls = [w["url"] for w in websites if w["url"] in selected]

                if not directories and not selected_web_urls:
                    event_queue.put({
                        "type": "complete",
                        "success": False,
                        "message": "Cancelled — nothing selected.",
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

                event_queue.put({
                    "type": "confirmation_accepted",
                    "selected_count": len(directories) + len(selected_web_urls),
                })

            # --- Phase 1: Auto-scrape each directory ---
            # Per-directory mode is decided from Phase 0's own fetch (see the
            # loop below). Prompts are auto-declined (batch mode — no human in
            # the loop for detail crawl or Phase 2).
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

            def auto_detail_crawl(detail_url_count, message=None):
                """Agent mode auto-accepts detail crawling.

                This callback is only reached after main.py's existing guards
                decide a crawl is warranted: detail links were detected AND a
                priority field is still missing ("no new data → don't crawl" is
                handled there, main.py:529). crawl_detail_pages keeps its own
                fallbacks too (API fast-path, selector validation, regex
                fallback, abort-on-junk). Detail data merges in BEFORE the
                Stage 1 intent filter, so a crawled category/description can
                rescue or reject an otherwise name-only record.
                """
                event_queue.put({
                    "type": "log",
                    "message": f"Auto-crawling {detail_url_count} member detail pages for missing fields...",
                    "category": "LOG",
                })
                return True

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
                # Scrape the URL preflight actually validated (post-redirect),
                # not the raw search-result URL.
                url = d.get("final_url") or d["url"]

                # Phase 0 already fetched this page and recorded where the
                # listing lives:
                #   needs_navigation=False → cards / multi-entry signals are on
                #     THIS page. Scrape it as-is (mode="direct") — re-running
                #     the AI navigator on a confirmed listing page is how the
                #     scrape gets "lost" on a worse sub-page than the one the
                #     user just approved.
                #   needs_navigation=True → the listing is a click away (or the
                #     page is JS-rendered). Auto mode, seeded with Phase 0's
                #     landing_link when it found one, so the navigator starts
                #     on the likely directory sub-page instead of re-deriving
                #     the first hop from the homepage.
                # Aggregators always stay on auto: their value is the
                # intent-driven search-box fill, not the landing page as-is.
                needs_nav = d.get("needs_navigation", True)
                is_agg = d.get("is_aggregator", False)
                scrape_mode = "auto" if (needs_nav or is_agg) else "direct"

                landing_hint = None
                if scrape_mode == "auto" and not is_agg and d.get("landing_link"):
                    landing_hint = _same_site_hint(url, d["landing_link"])

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
                if scrape_mode == "direct":
                    event_queue.put({
                        "type": "log",
                        "message": f"Listing confirmed on this page during discovery — scraping it directly (no navigation)",
                        "category": "NAV",
                    })
                elif landing_hint:
                    event_queue.put({
                        "type": "log",
                        "message": f"Starting navigation from the directory link found during discovery: {landing_hint}",
                        "category": "NAV",
                    })

                def _agent_login(page, domain):
                    """Agent-run login handler. Pauses for the human to log in
                    via Live View instead of auto-skipping — the old behavior
                    silently dropped every login-gated directory."""
                    _emit_paused(event_queue, session_id, "login",
                                 f"Login wall on {domain.replace('_', '.')} — open "
                                 f"Live View, log in inside the page, then Resume "
                                 f"(or Skip to move on).")
                    cont = live.control_until_resume(session_id, page, reason="login")
                    _emit_resumed(event_queue, session_id)
                    return cont

                def _agent_captcha(page, domain, vendor):
                    """Agent-run CAPTCHA handler. Pauses so the human can solve
                    the challenge in Live View, then resumes this site's scrape."""
                    _emit_paused(event_queue, session_id, "captcha",
                                 f"{vendor} challenge on {domain.replace('_', '.')} — "
                                 f"the scraper is PAUSED. Open Live View to solve it, "
                                 f"then press Resume.", vendor=vendor)
                    cont = live.control_until_resume(session_id, page,
                                                     reason="captcha", vendor=vendor)
                    _emit_resumed(event_queue, session_id)
                    return cont

                try:
                    members = scrape_directory(
                        url,
                        prompt_callback=auto_detail_crawl,
                        mode=scrape_mode,
                        priority_fields=priority_fields,
                        intent=intent,
                        is_aggregator=is_agg,
                        landing_hint=landing_hint,
                        login_callback=_agent_login,
                        captcha_callback=_agent_captcha,
                        live_session_id=session_id,
                        crawl_all=crawl_all,
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
                                enriched_path = enrich_from_websites(
                                    structured_path,
                                    accurate_enrichment=accurate_enrichment,
                                )
                                output_file = os.path.basename(enriched_path)
                                with open(enriched_path) as ef:
                                    enriched_results = read_members(enriched_path)
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

            # --- Standalone sites the user selected --------------------------
            # Phase 0 found these as single-business WEBSITEs, not directories.
            # We treat each as a one-row member and run the same website
            # enrichment that fills contact details — that IS "scraping" a
            # standalone site here (visit the homepage, extract email/phone/
            # address). No-op when the user ticked none.
            if selected_web_urls and not _check_skip():
                import time as _time
                from datetime import datetime as _dt, timezone as _tz
                title_by_url = {w["url"]: w.get("title", "") for w in websites}
                site_members = [
                    {"company_name": title_by_url.get(u, ""), "website": u}
                    for u in selected_web_urls
                ]
                site_fname = f"standalone_sites_{int(_time.time())}_structured.json"
                site_struct_path = os.path.join(DATA_DUMP, site_fname)
                os.makedirs(DATA_DUMP, exist_ok=True)
                with open(site_struct_path, "w") as sf:
                    json.dump({
                        "metadata": {
                            "scraped_at": _dt.now(_tz.utc).isoformat(),
                            "source_url": "phase0_standalone_websites",
                            "total_members": len(site_members),
                        },
                        "members": site_members,
                    }, sf, indent=4)

                event_queue.put({
                    "type": "log",
                    "message": f"Scraping {len(site_members)} standalone site(s) via website enrichment...",
                    "category": "LOG",
                })
                try:
                    site_enriched_path = enrich_from_websites(
                        site_struct_path,
                        event_callback=lambda ev: event_queue.put(ev),
                        accurate_enrichment=accurate_enrichment,
                    )
                    site_results = read_members(site_enriched_path)
                    site_enriched_n = sum(
                        1 for r in site_results
                        if r.get("enrichment_status") == "enriched"
                    )
                    total_records += len(site_results)
                    output_files.append(os.path.basename(site_enriched_path))
                    per_site_results.append({
                        "url": f"{len(selected_web_urls)} standalone site(s)",
                        "records": len(site_results),
                        "enriched": site_enriched_n,
                        "output_file": os.path.basename(site_enriched_path),
                    })
                except Exception as e:
                    event_queue.put({
                        "type": "log",
                        "message": f"Standalone-site enrichment failed: {e}",
                        "category": "ERROR",
                    })

            # --- Final deliverable: one cleaned JSON + Excel workbook ---
            # Consolidates EVERY output file of this run (Phase 1 structured,
            # Phase 2 enriched — which live in Phase2-Dump and were silently
            # skipped by the old Data-dump-only merge — NPI pulls, standalone
            # sites) into {industry}_{states}_final.json/.xlsx: deduped
            # across sources, canonical field order, source-tagged records.
            merged_file = None
            final_xlsx = None
            export_info = None
            if output_files:
                try:
                    plan_industry = (result.get("plan") or {}).get("industry") or {}
                    plan_locations = (result.get("plan") or {}).get("locations") or []
                    industry_name = plan_industry.get("canonical") or ""
                    industry_slug = (industry_name or "results").replace(" ", "_")[:40]
                    states = "_".join(
                        loc.get("state", "") for loc in plan_locations[:3] if loc.get("state")
                    )
                    base_name = f"{industry_slug}_{states}" if states else industry_slug

                    export_info = export_final_dataset(
                        output_files, [DATA_DUMP, PHASE2_DUMP], DATA_DUMP,
                        base_name, goal=goal, industry=industry_name,
                        locations=[loc.get("state", "") for loc in plan_locations],
                    )
                    if export_info:
                        merged_file = export_info["json_file"]
                        final_xlsx = export_info.get("xlsx_file")
                        dup_note = (f", {export_info['duplicates_merged']} duplicates merged"
                                    if export_info["duplicates_merged"] else "")
                        event_queue.put({
                            "type": "log",
                            "message": (f"Final dataset: {export_info['total']} unique records "
                                        f"from {len(export_info['sources'])} source(s){dup_note} "
                                        f"→ {merged_file}"
                                        + (f" + {final_xlsx}" if final_xlsx else "")),
                            "category": "CLEAN",
                        })
                except Exception as e:
                    event_queue.put({
                        "type": "log",
                        "message": f"Final export failed (per-site files unaffected): {e}",
                        "category": "ERROR",
                    })

            _final_complete = {
                "type": "complete",
                "success": total_records > 0,
                "records": total_records,
                "directories_scraped": len(directories),
                "websites_found": len(websites),
                "websites": [w["url"] for w in websites],
                "output_files": output_files,
                "merged_file": merged_file,
                "final_json": merged_file,
                "final_xlsx": final_xlsx,
                "per_site": per_site_results,
                "stats": {
                    "rejected_count": result.get("rejected_count", 0),
                    "reject_reasons": result.get("reject_reasons", {}),
                },
            }
            # Additive (Phase 2 count gate): flag when any source extracted
            # less than its site's stated total — no event renames.
            if export_info and export_info.get("partial"):
                _final_complete["partial"] = True
            event_queue.put(_final_complete)
        except Exception as e:
            original_print(f"ERROR: {e}\n{traceback.format_exc()}")
            event_queue.put({"type": "error", "message": str(e)})
        finally:
            builtins.print = original_print
            live.unregister(session_id)  # tear down Live View for this run
            event_queue.put(None)  # sentinel
            active_sessions.pop(session_id, None)

    thread = threading.Thread(target=discover_thread, daemon=True)
    thread.start()

    def stream():
        yield f"data: {json.dumps({'type': 'session', 'session_id': session_id})}\n\n"
        while True:
            try:
                event = event_queue.get(timeout=15)
                if event is None:
                    break
                yield f"data: {json.dumps(event)}\n\n"
            except queue.Empty:
                # No scraper output for a while (e.g. a long silent detail crawl):
                # send an SSE comment as a keepalive so nginx / the browser don't
                # drop the idle connection. Both frontend parsers skip frames that
                # don't start with "data: ". Only the None sentinel ends the stream.
                yield ": keepalive\n\n"

    return Response(stream(), mimetype="text/event-stream")


# --- CSV CONVERSION & DOWNLOAD ---

# Flattening + CSV live in exporter.py (one implementation for CSV and XLSX).
# Alias kept because ad-hoc tests import _records_to_csv from app.
_records_to_csv = records_to_csv


@app.route("/download/<path:filename>", methods=["GET"])
def download_file(filename):
    """Download a structured or enriched JSON file as JSON or CSV.
    Query param: ?format=csv or ?format=json (default: json)"""
    fmt = request.args.get("format", "json").lower()

    # Dump files are always flat basenames — reject anything path-shaped
    # (guards the os.path.join below against ../ traversal).
    if os.path.basename(filename) != filename:
        return jsonify({"error": "Invalid filename"}), 400

    # Check both Data-dump and Phase2-Dump directories
    file_path = None
    for directory in (DATA_DUMP, PHASE2_DUMP):
        candidate = os.path.join(directory, filename)
        if os.path.isfile(candidate):
            file_path = candidate
            break

    if not file_path:
        return jsonify({"error": f"File not found: {filename}"}), 404

    # Excel workbooks are served as-is (binary) — no format conversion.
    if filename.lower().endswith(".xlsx"):
        return send_file(file_path, as_attachment=True,
                         download_name=os.path.basename(file_path))

    try:
        members = read_members(file_path)
        metadata = read_metadata(file_path)
    except Exception as e:
        return jsonify({"error": f"Failed to read file: {e}"}), 500

    if not members:
        return jsonify({"error": "File does not contain a list of records"}), 400

    if fmt == "csv":
        csv_content = _records_to_csv(members, entity_type=(metadata or {}).get("entity_type", "business"))
        csv_filename = filename.rsplit(".", 1)[0] + ".csv"
        return Response(
            csv_content,
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={csv_filename}"},
        )
    else:
        output: dict = {"members": members}
        if metadata:
            output["metadata"] = metadata
        return Response(
            json.dumps(output, indent=2, ensure_ascii=False),
            mimetype="application/json",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )


# --- LIVE VIEW ---
# Stream the scraper's browser to the frontend and relay the user's clicks/keys
# back into it while a run is paused (CAPTCHA / login / manual take-control).
# All four endpoints are keyed by the scrape's SSE session id and are no-ops for
# a session that isn't live-registered (Playground batch, CLI). See
# Bot/live_view.py for the threading model.


@app.route("/live/stream", methods=["GET"])
def live_stream():
    """SSE stream of JPEG frames + status for one scrape session.

    Emits:
      {"type":"meta", ...}                        once, on connect
      {"type":"status","status":..., "vendor":?}  whenever the run's state flips
      {"type":"frame","seq":N,"data":"<b64 jpeg>"}on each new frame
    Ends when the session is torn down (scrape finished)."""
    sid = request.args.get("session", "").strip()

    def stream():
        last_seq = -1
        last_status = None
        yield f"data: {json.dumps({'type': 'meta', **live.get_status(sid)})}\n\n"
        stale = 0
        while True:
            if not live.is_registered(sid):
                yield f"data: {json.dumps({'type': 'status', 'status': 'closed'})}\n\n"
                break
            st = live.get_status(sid)
            if st.get("status") != last_status:
                last_status = st.get("status")
                yield f"data: {json.dumps({'type': 'status', **st})}\n\n"
                stale = 0
            seq, frame = live.get_frame(sid)
            if frame is not None and seq != last_seq:
                last_seq = seq
                yield f"data: {json.dumps({'type': 'frame', 'seq': seq, 'data': frame})}\n\n"
                stale = 0
            else:
                stale += 1
                if stale >= 150:  # ~15 s with no new frame — keep nginx alive
                    yield ": keepalive\n\n"
                    stale = 0
            time.sleep(0.1)

    return Response(stream(), mimetype="text/event-stream")


@app.route("/live/input", methods=["POST"])
def live_input():
    """Relay one input command from the frontend into the paused browser page.

    Body: {"session": "<id>", "cmd": {"type":"click","x":0.5,"y":0.3}, ...}
    x/y are fractions of the displayed frame (0..1); the backend scales them to
    the browser viewport. Applied only while the run is paused."""
    data = request.get_json(force=True, silent=True) or {}
    sid = (data.get("session") or "").strip()
    cmd = data.get("cmd")
    if not sid or not isinstance(cmd, dict):
        return jsonify({"error": "session and cmd required"}), 400
    live.enqueue_input(sid, cmd)
    return jsonify({"ok": True})


@app.route("/live/control", methods=["POST"])
def live_control():
    """Resume / skip / request-pause a run from the frontend.

    Body: {"session": "<id>", "action": "resume"|"skip"|"pause"}"""
    data = request.get_json(force=True, silent=True) or {}
    sid = (data.get("session") or "").strip()
    action = (data.get("action") or "").strip()
    if not live.set_control(sid, action):
        return jsonify({"error": "unknown session or action"}), 400
    return jsonify({"ok": True})


@app.route("/live/status", methods=["GET"])
def live_status():
    """One-shot status probe (the frontend uses the /live/stream feed for live
    updates; this is for a quick check on demand)."""
    sid = request.args.get("session", "").strip()
    return jsonify(live.get_status(sid))


# --- ANALYTICS ---

ANALYTICS_PASSWORD = os.environ.get("ANALYTICS_PASSWORD", "trawlbase")  # change in .env!


@app.route("/a", methods=["POST"])
def analytics_collect():
    """Fire-and-forget event recording.  Lightweight — no auth needed to log.

    Expects JSON: {visitor_id, type: "page_view"|"event",
                   path?, event_name?, event_data?, referrer?}
    Returns 204 No Content on success.
    """
    try:
        data = request.get_json(force=True, silent=True) or {}
    except Exception:
        return "", 204

    vid = (data.get("visitor_id") or "").strip()
    if not vid:
        return "", 204

    ev_type = (data.get("type") or "").strip()

    if ev_type == "page_view":
        record_page_view(
            visitor_id=vid,
            path=data.get("path", "/"),
            referrer=data.get("referrer", ""),
            user_agent=request.headers.get("User-Agent", ""),
        )
    elif ev_type == "event":
        record_event(
            visitor_id=vid,
            event_name=data.get("event_name", "unknown"),
            event_data=data.get("event_data"),
            page=data.get("path", ""),
        )

    return "", 204


@app.route("/analytics/stats", methods=["GET"])
def analytics_stats():
    """Return aggregate analytics.  Protected by ANALYTICS_PASSWORD.

    Query params:
      password (required)
      days     (optional, default 30)
    """
    pw = request.args.get("password", "")
    if pw != ANALYTICS_PASSWORD:
        return jsonify({"error": "Invalid password"}), 401

    try:
        days = int(request.args.get("days", "30"))
    except ValueError:
        days = 30

    stats = get_stats(days=days)
    return jsonify(stats)


if __name__ == "__main__":
    host = os.environ.get("FLASK_HOST", "localhost")
    port = int(os.environ.get("FLASK_PORT", "5000"))
    app.run(host=host, port=port, debug=False, threaded=True)

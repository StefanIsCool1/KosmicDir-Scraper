from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import sys, os, csv, json, io, builtins, queue, threading, uuid

os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"

# Add the Bot directory to the path so Python can find the scraper modules
sys.path.append(os.path.join(os.path.dirname(__file__), "Bot"))

from Bot.main import scrape_directory
from Bot.debug import debug

app = Flask(__name__)
CORS(app,
    origins=["http://localhost:3000"],
    methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Custom-Header"],
    supports_credentials=True)

DATA_DUMP = os.path.join(os.path.dirname(__file__), "Data-dump")

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


@app.route("/scrape/single", methods=["POST"])
def scrape_single():
    """Stream scrape progress as SSE events. Supports interactive prompts."""
    link = request.json.get("link")
    debug_mode = request.json.get("debug", False)
    if not link:
        return jsonify({"error": "No link"}), 400

    session_id = str(uuid.uuid4())
    event_queue = queue.Queue()
    response_event = threading.Event()

    active_sessions[session_id] = {
        "queue": event_queue,
        "response_event": response_event,
        "response_value": None,
    }

    def prompt_via_frontend(detail_url_count):
        """Replacement for input() — sends prompt to frontend, waits for response."""
        session = active_sessions.get(session_id)
        if not session:
            return False
        event_queue.put({
            "type": "prompt",
            "message": f"Found {detail_url_count} detail pages. Crawl them? (y/n)",
            "detail_url_count": detail_url_count,
        })
        session["response_event"].wait(timeout=300)
        answer = session.get("response_value", "n")
        session["response_event"].clear()
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
            members = scrape_directory(link, prompt_callback=prompt_via_frontend)
            result = {
                "type": "complete",
                "success": len(members) > 0,
                "records": len(members),
            }
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


if __name__ == "__main__":
    app.run(host="localhost", port=5000, debug=False, threaded=True)

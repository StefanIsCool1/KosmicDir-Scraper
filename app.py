from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import sys, os, csv, json, io, builtins



os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"
sys.path.append(os.path.join(os.path.dirname(__file__), "Bot"))

from Bot.FetchXHR import responsepull
from playwright.sync_api import sync_playwright

app = Flask(__name__)
CORS(app, 
     origins=["http://localhost:3000"],  # Explicit > wildcard
     methods=["GET", "POST", "OPTIONS"],  # Explicitly include OPTIONS
     allow_headers=["Content-Type", "X-Custom-Header"],  # Match your headers
     supports_credentials=True)  # Handle cookies/auth

DATA_DUMP = os.path.join(os.path.dirname(__file__), "Data-dump")

def run_scrape(link):
    logs = []
    original_print = builtins.print
    def captured_print(*args, **kwargs):
        msg = " ".join(str(a) for a in args)
        logs.append(msg)
        original_print(*args, **kwargs)
    builtins.print = captured_print
    try:
        with sync_playwright() as playwright:
            responsepull(playwright, link)
        domain = link.replace("https://", "").replace("http://", "").split("/")[0]
        filepath = os.path.join(DATA_DUMP, domain.replace(".", "_") + ".json")
        if os.path.exists(filepath) and os.path.getsize(filepath) > 50:
            with open(filepath) as f:
                data = json.load(f)
            records = sum(len(r.get("data", [])) if isinstance(r.get("data"), list) else 1 for r in data)
            success = True
        else:
            success, records = False, 0
    except Exception as e:
        logs.append(f"ERROR: {e}")
        success, records = False, 0
    finally:
        builtins.print = original_print
    return success, records, logs

@app.route("/scrape/single", methods=["POST"])
def scrape_single():
    link = request.json.get("link")
    if not link:
        return jsonify({"error": "No link"}), 400
    success, records, logs = run_scrape(link)
    return jsonify({"success": success, "records": records, "logs": logs})

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
            success, records, logs = run_scrape(link)
            yield f"data: {json.dumps({'index': i, 'link': link, 'success': success, 'records': records, 'logs': logs})}\n\n"
        yield 'data: {"done": true}\n\n'
    return Response(stream(), mimetype="text/event-stream")

if __name__ == "__main__":
    app.run(host="localhost", port=5000, debug=False, threaded=True)

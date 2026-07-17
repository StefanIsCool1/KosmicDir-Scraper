"""
Live View — stream the scraper's browser to the frontend and hand a human
direct control of the page during a pause (CAPTCHA / login / debug).

Why this module exists and how it stays out of the scraper's way
----------------------------------------------------------------
The scraper drives Playwright's **sync** API from a single background thread
(app.py's bot_thread / discover_thread). A Playwright `Page` may only be
touched from that same thread — a Flask request thread calling
`page.screenshot()` or `page.mouse.click()` would corrupt Playwright's state.

So this module never drives the page from a request thread. Instead:

  * Flask threads only ever read a byte buffer (the latest JPEG frame) and push
    input commands onto a thread-safe queue. Both are lock-guarded and cheap.
  * The Playwright-owning thread is the ONLY thing that touches the page. It
    does so at two kinds of moment, both of which it already controls:
      1. Passively, via a CDP screencast whose frames arrive while the thread
         pumps Playwright (navigations, waits, scrolls). Best-effort — if the
         CDP session can't be created the live view simply falls back to (2).
      2. Actively, inside `control_until_resume()` / `checkpoint()`, which run
         ON the Playwright thread (they're called from the scraper's own
         captcha_callback / login_callback / pagination checkpoints). There the
         thread owns itself: it drains the input queue and grabs a fresh
         screenshot each tick until the user resumes.

Everything is keyed by the scrape's existing `session_id` (the same id app.py
already tracks in `active_sessions`). When a session was never `register()`ed —
the Playground CSV batch path, the CLI, any run the user didn't open Live View
for — every entry point here is a cheap no-op, so the scraper is unaffected.

The viewport the scraper uses (Bot/config.py:new_stealth_page) is 1440x900.
Input from the browser arrives as fractions of the displayed image (0..1) and is
scaled by VIEWPORT here, so the two only have to agree on the constant below.
"""

import threading
import time
import base64

# Must match the context viewport in Bot/config.py:new_stealth_page.
VIEWPORT_W = 1440
VIEWPORT_H = 900

# Screencast tuning. maxWidth downscales frames for bandwidth; quality is the
# JPEG quality. everyNthFrame=1 = every repaint (Chromium only emits on change,
# so a static page costs nothing).
_CAST_MAX_W = 1280
_CAST_MAX_H = 800
_CAST_QUALITY = 55

# How long a pause waits for the human before giving up and skipping the site.
_PAUSE_TIMEOUT = 600  # seconds

# Pump cadence while paused: screenshot + input-drain interval, in ms.
_PUMP_INTERVAL_MS = 90


class _LiveSession:
    __slots__ = (
        "sid", "lock", "frame_b64", "frame_seq",
        "status", "vendor", "input_q",
        "resume", "skip", "pause_requested",
        "page", "cdp", "closed",
    )

    def __init__(self, sid):
        self.sid = sid
        self.lock = threading.Lock()
        self.frame_b64 = None          # latest JPEG frame, base64 str
        self.frame_seq = 0             # bumps on every new frame
        self.status = "running"        # running | captcha | login | paused | closed
        self.vendor = None             # anti-bot vendor name when status=captcha
        self.input_q = []              # queued input commands (dicts)
        self.resume = False            # user pressed Resume
        self.skip = False              # user pressed Skip site
        self.pause_requested = False   # user pressed Take control (arm a pause)
        self.page = None               # top-level Playwright page (PW thread only)
        self.cdp = None                # CDP session for the screencast
        self.closed = False


class LiveViewManager:
    def __init__(self):
        self._sessions = {}                 # sid -> _LiveSession
        self._by_thread = {}                # thread ident -> sid
        self._glock = threading.Lock()

    # -- lifecycle (called from app.py, any thread) -----------------------

    def register(self, sid):
        """Mark a scrape session as live-view capable. Call at scrape start."""
        if not sid:
            return
        with self._glock:
            self._sessions[sid] = _LiveSession(sid)

    def unregister(self, sid):
        """Tear a session down. Call in the scrape's finally block."""
        if not sid:
            return
        with self._glock:
            sess = self._sessions.pop(sid, None)
            for tid, mapped in list(self._by_thread.items()):
                if mapped == sid:
                    self._by_thread.pop(tid, None)
        if sess:
            with sess.lock:
                sess.closed = True
                sess.status = "closed"

    def is_registered(self, sid):
        with self._glock:
            return sid in self._sessions

    def _get(self, sid):
        with self._glock:
            return self._sessions.get(sid)

    # -- attach the page (PW thread, from browser.py) ---------------------

    def attach(self, sid, page):
        """Bind the scraper's page to this session and start the screencast.

        Runs on the Playwright thread. Records thread->sid so no-arg
        `checkpoint()` calls elsewhere in the scraper can find their session
        without threading the id through every function. Fully fail-open:
        any exception leaves the scrape running with the pause-loop fallback.
        """
        sess = self._get(sid)
        if sess is None:
            return
        with sess.lock:
            sess.page = page
        with self._glock:
            self._by_thread[threading.get_ident()] = sid
        # Best-effort CDP screencast for live viewing during active scraping.
        try:
            self._start_screencast(sess, page)
        except Exception:
            # No screencast — pause-loop screenshots still cover the CAPTCHA
            # path, which is the part that must work.
            pass

    def _start_screencast(self, sess, page):
        cdp = page.context.new_cdp_session(page)

        def _on_frame(params):
            try:
                data = params.get("data")
                if data:
                    with sess.lock:
                        sess.frame_b64 = data
                        sess.frame_seq += 1
                # Ack or Chromium stops after its small buffer fills.
                cdp.send("Page.screencastFrameAck",
                         {"sessionId": params.get("sessionId")})
            except Exception:
                pass

        cdp.on("Page.screencastFrame", _on_frame)
        cdp.send("Page.startScreencast", {
            "format": "jpeg",
            "quality": _CAST_QUALITY,
            "maxWidth": _CAST_MAX_W,
            "maxHeight": _CAST_MAX_H,
            "everyNthFrame": 1,
        })
        with sess.lock:
            sess.cdp = cdp

    # -- status (PW thread sets, request threads read) --------------------

    def set_status(self, sid, status, vendor=None):
        sess = self._get(sid)
        if sess is None:
            return
        with sess.lock:
            sess.status = status
            sess.vendor = vendor

    def get_status(self, sid):
        sess = self._get(sid)
        if sess is None:
            return {"status": "closed", "registered": False}
        with sess.lock:
            return {
                "status": sess.status,
                "vendor": sess.vendor,
                "registered": True,
                "viewport": {"w": VIEWPORT_W, "h": VIEWPORT_H},
                "paused": sess.status in ("captcha", "login", "paused"),
            }

    # -- frames (request thread reads) ------------------------------------

    def get_frame(self, sid):
        """Return (seq, base64_jpeg_or_None). seq lets the streamer skip
        re-sending an unchanged frame."""
        sess = self._get(sid)
        if sess is None:
            return (0, None)
        with sess.lock:
            return (sess.frame_seq, sess.frame_b64)

    # -- input + control (request thread writes) --------------------------

    def enqueue_input(self, sid, cmd):
        """Queue an input command from the frontend. Applied by the PW thread
        only while paused (see _pump_inputs). Ignored when not paused — direct
        control is a paused/debug affordance, not something that races the bot
        mid-action."""
        sess = self._get(sid)
        if sess is None or not isinstance(cmd, dict):
            return
        with sess.lock:
            if len(sess.input_q) < 200:  # guard against a stuck/flooding client
                sess.input_q.append(cmd)

    def set_control(self, sid, action):
        """action: 'resume' | 'skip' | 'pause'. Returns True if applied."""
        sess = self._get(sid)
        if sess is None:
            return False
        with sess.lock:
            if action == "resume":
                sess.resume = True
            elif action == "skip":
                sess.skip = True
            elif action == "pause":
                sess.pause_requested = True
            else:
                return False
        return True

    # -- pause loop (PW thread) -------------------------------------------

    def control_until_resume(self, sid, page, reason="paused", vendor=None,
                             timeout=_PAUSE_TIMEOUT):
        """Block the scraper here, handing the human live control of `page`,
        until they press Resume (return True) or Skip (return False).

        MUST be called from the Playwright-owning thread. Each tick it applies
        any queued input and refreshes a screenshot, so the frontend stays live
        and interactive even though the scraper thread is otherwise parked.
        """
        sess = self._get(sid)
        if sess is None:
            # Not a live session — nothing can drive it; behave like the old
            # unattended path and skip rather than hang forever.
            return False

        with sess.lock:
            sess.status = reason
            sess.vendor = vendor
            sess.resume = False
            sess.skip = False
            sess.pause_requested = False
            sess.page = page

        deadline = time.time() + timeout
        try:
            while time.time() < deadline:
                with sess.lock:
                    if sess.closed:
                        return False
                    if sess.resume:
                        sess.resume = False
                        return True
                    if sess.skip:
                        sess.skip = False
                        return False
                self._pump_inputs(sess, page)
                self._grab_frame(sess, page)
                try:
                    page.wait_for_timeout(_PUMP_INTERVAL_MS)
                except Exception:
                    time.sleep(_PUMP_INTERVAL_MS / 1000)
            return False  # timed out — treat as skip (old behavior)
        finally:
            with sess.lock:
                sess.status = "running"
                sess.vendor = None

    def checkpoint(self):
        """No-arg cooperative pause point for the scraper thread.

        A no-op unless the user pressed Take control for THIS thread's session.
        Lets a couple of long-running scraper loops (e.g. pagination) yield to a
        manual pause without threading a session id through their signatures.
        Safe to call anywhere on the Playwright thread; returns immediately when
        no pause is pending.
        """
        with self._glock:
            sid = self._by_thread.get(threading.get_ident())
        if not sid:
            return
        sess = self._get(sid)
        if sess is None:
            return
        with sess.lock:
            armed = sess.pause_requested and not sess.closed
            page = sess.page
        if armed and page is not None:
            self.control_until_resume(sid, page, reason="paused")

    def _pump_inputs(self, sess, page):
        with sess.lock:
            cmds = sess.input_q
            sess.input_q = []
        for cmd in cmds:
            try:
                self._apply_input(page, cmd)
            except Exception:
                # A bad coordinate / detached element must not kill the pause.
                pass

    def _apply_input(self, page, cmd):
        kind = cmd.get("type")
        if kind == "click":
            x = float(cmd.get("x", 0)) * VIEWPORT_W
            y = float(cmd.get("y", 0)) * VIEWPORT_H
            clicks = int(cmd.get("clicks", 1)) or 1
            button = cmd.get("button", "left")
            page.mouse.click(x, y, button=button, click_count=clicks)
        elif kind == "move":
            page.mouse.move(float(cmd.get("x", 0)) * VIEWPORT_W,
                            float(cmd.get("y", 0)) * VIEWPORT_H)
        elif kind == "wheel":
            page.mouse.wheel(float(cmd.get("dx", 0)), float(cmd.get("dy", 0)))
        elif kind == "type":
            text = str(cmd.get("text", ""))
            if text:
                page.keyboard.type(text)
        elif kind == "key":
            key = str(cmd.get("key", ""))
            if key:
                page.keyboard.press(key)
        elif kind == "back":
            page.go_back()
        elif kind == "forward":
            page.go_forward()
        elif kind == "reload":
            page.reload()
        elif kind == "goto":
            url = str(cmd.get("url", "")).strip()
            if url.startswith(("http://", "https://")):
                page.goto(url)

    def _grab_frame(self, sess, page):
        """Take a viewport JPEG and store it. The guaranteed frame source while
        paused (independent of the CDP screencast)."""
        try:
            png = page.screenshot(type="jpeg", quality=_CAST_QUALITY,
                                  full_page=False)
        except Exception:
            return
        b64 = base64.b64encode(png).decode("ascii")
        with sess.lock:
            sess.frame_b64 = b64
            sess.frame_seq += 1


# Process-wide singleton. app.py and browser.py both `import live_view` (Bot is
# on sys.path) so they share this one instance and its registry.
live = LiveViewManager()

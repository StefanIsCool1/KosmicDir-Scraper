import FetchXHR
#fetches 
with FetchXHR.sync_playwright() as playwright:
    FetchXHR.run(playwright)




def score_assigner(req):
    score = 0
    url = req['url'].lower()
    keywords = [
        "search", "directory", "member", "listing", "assets",
        "results", "api", "profiles", "people", "companies"
    ]
    if any(k in url for k in keywords):
        score += 5

    # Query parameters often indicate data endpoints
    if "?" in url:
        score += 2

    # Versioned API endpoints
    if "/v1/" in url or "/v2/" in url or "/api/" in url:
        score += 3

    # JSON-like endings
    if url.endswith("search") or url.endswith("list") or url.endswith("results"):
        score += 2

    # XHR/fetch is required
    if req["resource_type"] in ("xhr", "fetch"):
        score += 3

    return score



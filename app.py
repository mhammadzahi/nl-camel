import requests
import csv
import time
import random
import threading
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import re

# -------------------------
# Configuration
# -------------------------
CSV_FILE = "newsletter_sites.csv"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
REQUEST_TIMEOUT = 8
MAX_WORKERS = 20
MAX_DOMAINS = 100000
TRANCO_LIST_SIZE = 10000

TRANCO_URL = "https://tranco-list.eu/top-1m.csv.zip"

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Connection": "keep-alive",
}

NEWSLETTER_KEYWORDS = [
    "newsletter",
    "subscribe",
    "subscription",
    "sign up",
    "signup",
    "join our",
    "mailing list",
    "email updates",
    "get updates",
    "stay updated",
    "weekly digest"
]

csv_lock = threading.Lock()
stats_lock = threading.Lock()
stats = {"processed": 0, "with_newsletter": 0, "without_newsletter": 0, "errors": 0}

def init_csv():
    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "timestamp",
            "domain",
            "url",
            "has_newsletter",
            "confidence_score",
            "signals_found",
            "found_newsletter_path"
        ])

def fetch_domains_from_tranco():
    print("📥 Downloading Tranco top sites list...")
    try:
        import zipfile
        import io
        r = requests.get(TRANCO_URL, timeout=30)
        r.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            csv_filename = z.namelist()[0]
            with z.open(csv_filename) as f:
                content = f.read().decode('utf-8')
        print("✅ Downloaded Tranco list successfully")
        lines = content.strip().split('\n')
        count = 0
        for line in lines:
            if count >= TRANCO_LIST_SIZE:
                break
            parts = line.split(',')
            if len(parts) >= 2:
                domain = parts[1].strip()
                if domain:
                    yield domain
                    count += 1
    except Exception as e:
        print(f"❌ Error fetching Tranco list: {e}")
        print("💡 Falling back to common domain generation...")
        for domain in generate_common_domains():
            yield domain

def generate_common_domains():
    common_words = [
        "blog", "news", "tech", "business", "media", "digital", "daily",
        "weekly", "post", "times", "journal", "magazine", "review", "insider",
        "today", "world", "network", "online", "web", "site", "hub", "central"
    ]
    tlds = ["com", "org", "net", "io", "co"]
    for word in common_words:
        for tld in tlds:
            yield f"{word}.{tld}"

def detect_newsletter(html, url):
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(separator=" ").lower()
    signals = set()
    confidence = 0
    for form in soup.find_all("form"):
        email_inputs = form.find_all("input", {"type": "email"})
        text_inputs = form.find_all("input", {"type": "text"})
        if email_inputs:
            signals.add("form:email_input_type")
            confidence += 30
        for inp in text_inputs:
            name = (inp.get("name", "") + inp.get("id", "") + inp.get("placeholder", "")).lower()
            if any(kw in name for kw in ["email", "mail", "e-mail"]):
                signals.add("form:email_named_input")
                confidence += 25
        action = form.get("action", "").lower()
        if any(kw in action for kw in ["subscribe", "newsletter", "signup", "join", "register"]):
            signals.add("form:newsletter_action")
            confidence += 20
        buttons = form.find_all(["button", "input"])
        for btn in buttons:
            btn_text = (btn.get("value", "") + btn.get_text()).lower()
            if any(kw in btn_text for kw in NEWSLETTER_KEYWORDS):
                signals.add("form:newsletter_button")
                confidence += 15
    newsletter_patterns = [
        r'newsletter.*sign.*up',
        r'subscribe.*newsletter',
        r'join.*mailing.*list',
        r'email.*subscription',
        r'get.*weekly.*digest'
    ]
    for pattern in newsletter_patterns:
        if re.search(pattern, text):
            signals.add(f"pattern:{pattern[:20]}")
            confidence += 10
    newsletter_services = [
        "mailchimp", "substack", "convertkit", "buttondown",
        "revue", "tinyletter", "sendinblue", "getresponse"
    ]
    html_lower = html.lower()
    for service in newsletter_services:
        if service in html_lower:
            signals.add(f"service:{service}")
            confidence += 25
    iframes = soup.find_all("iframe")
    for iframe in iframes:
        src = iframe.get("src", "").lower()
        if any(s in src for s in newsletter_services):
            signals.add("iframe:newsletter_widget")
            confidence += 20
    has_newsletter = confidence >= 30
    return has_newsletter, confidence, ";".join(sorted(signals))

def analyze_domain(domain):
    paths_to_check = ["/", "/newsletter", "/subscribe", "/contact", "/about"]
    all_signals = set()
    successful_url = None
    max_confidence = 0
    found_paths = set()
    base_url = f"https://{domain}"
    for path in paths_to_check:
        url = base_url + path
        try:
            r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True, verify=False)
            if r.status_code >= 400:
                continue
            if not successful_url:
                successful_url = r.url
            has_newsletter, confidence, signals = detect_newsletter(r.text, r.url)
            if has_newsletter and confidence > max_confidence:
                max_confidence = confidence
                found_paths.add(path)
                for signal in signals.split(";"):
                    if signal:
                        all_signals.add(f"{path}:{signal}")
                if path == "/" and confidence >= 50:
                    break
        except requests.RequestException as e:
            continue
    if successful_url:
        has_newsletter = max_confidence >= 30
        return {
            "domain": domain,
            "url": successful_url,
            "has_newsletter": has_newsletter,
            "confidence": max_confidence,
            "signals": ";".join(sorted(all_signals)) if all_signals else "",
            "found_paths": ";".join(sorted(found_paths)) if found_paths else ""
        }
    return None

def append_csv(row):
    with csv_lock:
        with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.utcnow().isoformat(),
                row["domain"],
                row["url"],
                row["has_newsletter"],
                row["confidence"],
                row["signals"],
                row["found_paths"]
            ])

def update_stats(has_newsletter, error=False):
    with stats_lock:
        stats["processed"] += 1
        if error:
            stats["errors"] += 1
        elif has_newsletter:
            stats["with_newsletter"] += 1
        else:
            stats["without_newsletter"] += 1

def print_stats():
    with stats_lock:
        total = stats["processed"]
        newsletters = stats["with_newsletter"]
        rate = (newsletters / total * 100) if total > 0 else 0
        print(f"\n📊 Stats: {total} processed | ✅ {newsletters} with newsletter ({rate:.1f}%) | "
              f"❌ {stats['without_newsletter']} without | ⚠️  {stats['errors']} errors\n")

def process_domain(domain):
    try:
        result = analyze_domain(domain)
        if result:
            append_csv(result)
            update_stats(result["has_newsletter"])
            status = "✅ FOUND" if result["has_newsletter"] else "❌ none"
            conf = result.get("confidence", 0)
            paths = result.get("found_paths", "")
            print(f"{status} | {domain} | confidence: {conf} | paths: {paths or 'N/A'}")
            return result
        else:
            update_stats(False, error=True)
            print(f"⚠️  ERROR | {domain} | Failed to fetch")
    except Exception as e:
        update_stats(False, error=True)
        print(f"⚠️  ERROR | {domain} | {str(e)[:50]}")
    return None

def run():
    print("🚀 Newsletter Scanner Starting...")
    print(f"⚙️  Configuration: {MAX_WORKERS} workers, timeout {REQUEST_TIMEOUT}s")
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    init_csv()
    print(f"📝 CSV file initialized: {CSV_FILE}\n")
    domains = list(fetch_domains_from_tranco())
    if not domains:
        print("❌ No domains to process!")
        return
    print(f"🎯 Processing {min(len(domains), MAX_DOMAINS)} domains...\n")
    processed_count = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {}
        for domain in domains[:MAX_DOMAINS]:
            future = executor.submit(process_domain, domain)
            futures[future] = domain
            processed_count += 1
        completed = 0
        for future in as_completed(futures):
            completed += 1
            if completed % 50 == 0:
                print_stats()
    print_stats()
    print(f"\n✅ Scan complete! Results saved to {CSV_FILE}")

if __name__ == "__main__":
    run()

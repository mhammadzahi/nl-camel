import csv
import time
import random
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import logging
import re

# -------------------------
# Configuration
# -------------------------
INPUT_CSV = "newsletter_sites.csv"
OUTPUT_CSV = "registration_results.csv"
EMAILS_FILE = "emails.txt"
REGISTRATION_TIMEOUT = 10
DELAY_BETWEEN_REGISTRATIONS = (2, 5)

# Load email addresses from file
def load_emails():
    try:
        with open(EMAILS_FILE, 'r', encoding='utf-8') as f:
            emails = [line.strip() for line in f if line.strip()]

        random.shuffle(emails)
        random.shuffle(emails)
        random.shuffle(emails)
        return emails
    except FileNotFoundError:
        print(f"Error: {EMAILS_FILE} not found!")
        return []

EMAIL_ADDRESSES = load_emails()



logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

def find_newsletter_form(soup, url):
    forms = soup.find_all('form')
    for form in forms:
        form_str = str(form).lower()
        email_inputs = form.find_all('input', {'type': 'email'})
        if not email_inputs:
            text_inputs = form.find_all('input', {'type': 'text'})
            for inp in text_inputs:
                name = (inp.get('name', '') + inp.get('id', '') + inp.get('placeholder', '')).lower()
                if 'email' in name or 'mail' in name:
                    email_inputs.append(inp)
        if email_inputs:
            newsletter_keywords = ['newsletter', 'subscribe', 'signup', 'join', 'mailing']
            if any(kw in form_str for kw in newsletter_keywords):
                email_input = email_inputs[0]
                action = form.get('action', '')
                method = form.get('method', 'post').lower()
                fields = {}
                for inp in form.find_all(['input', 'textarea']):
                    name = inp.get('name')
                    if name:
                        value = inp.get('value', '')
                        input_type = inp.get('type', '').lower()
                        if input_type in ['submit', 'button']:
                            continue
                        fields[name] = value
                email_field_name = email_input.get('name', 'email')
                return {
                    'action': urljoin(url, action) if action else url,
                    'method': method,
                    'fields': fields,
                    'email_field': email_field_name
                }
    return None

def register_to_newsletter(url, email, paths):
    session = requests.Session()
    session.headers.update(HEADERS)
    paths_to_try = []
    if paths:
        paths_to_try = paths.split(';')
    if not paths_to_try or '/' not in paths_to_try:
        paths_to_try.insert(0, '/')
    for path in paths_to_try:
        try:
            parsed = urlparse(url)
            base_url = f"{parsed.scheme}://{parsed.netloc}"
            full_url = base_url + path
            logger.info(f"Trying {full_url}")
            response = session.get(full_url, timeout=REGISTRATION_TIMEOUT, verify=False)
            if response.status_code >= 400:
                logger.warning(f"Got status {response.status_code}")
                continue
            soup = BeautifulSoup(response.text, 'lxml')
            form_data = find_newsletter_form(soup, full_url)
            if not form_data:
                logger.warning(f"No newsletter form found on {full_url}")
                continue
            form_data['fields'][form_data['email_field']] = email
            logger.info(f"Found form, submitting to {form_data['action']}")
            logger.info(f"Email field: {form_data['email_field']}")
            if form_data['method'] == 'get':
                submit_response = session.get(form_data['action'], params=form_data['fields'], timeout=REGISTRATION_TIMEOUT, verify=False, allow_redirects=True)
            else:
                submit_response = session.post(form_data['action'], data=form_data['fields'], timeout=REGISTRATION_TIMEOUT, verify=False, allow_redirects=True)
            response_text = submit_response.text.lower()
            success_keywords = ['thank', 'success', 'confirm', 'subscribed', 'check your email', 'welcome']
            error_keywords = ['error', 'invalid', 'failed', 'already subscribed']
            has_success = any(kw in response_text for kw in success_keywords)
            has_error = any(kw in response_text for kw in error_keywords)
            if has_success and not has_error:
                logger.info(f"✅ Successfully registered to {full_url}")
                return True, "Success - confirmation detected"
            elif has_error:
                logger.info(f"⚠️  Form submitted but got error message")
                return False, "Failed - error message in response"
            else:
                logger.info(f"✅ Form submitted to {full_url}")
                return True, "Success - form submitted"
        except requests.Timeout:
            logger.warning(f"Timeout on {full_url}")
            continue
        except Exception as e:
            logger.warning(f"Error on {full_url}: {str(e)[:100]}")
            continue
    return False, "Failed - no working form found"

def read_newsletter_sites():
    sites = []
    try:
        with open(INPUT_CSV, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get('has_newsletter', '').lower() in ['true', '1', 'yes']:
                    confidence = int(row.get('confidence_score', 0))
                    if confidence >= 30:
                        sites.append({
                            'domain': row['domain'],
                            'url': row['url'],
                            'confidence': confidence,
                            'paths': row.get('found_newsletter_path', '')
                        })
        # Shuffle the sites list for randomness
        random.shuffle(sites)
        random.shuffle(sites)
        random.shuffle(sites)
        logger.info(f"Found {len(sites)} sites with newsletters (shuffled)")
        return sites
    except FileNotFoundError:
        logger.error(f"Input file {INPUT_CSV} not found!")
        return []
    except Exception as e:
        logger.error(f"Error reading CSV: {e}")
        return []

def save_result(domain, url, email, success, message):
    try:
        with open(OUTPUT_CSV, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if f.tell() == 0:
                writer.writerow(['timestamp', 'domain', 'url', 'email', 'success', 'message'])
            writer.writerow([time.strftime('%Y-%m-%d %H:%M:%S'), domain, url, email, success, message])
    except Exception as e:
        logger.error(f"Error saving result: {e}")

def run():
    logger.info("🚀 Newsletter Registration Bot Starting...")
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    sites = read_newsletter_sites()
    if not sites:
        logger.error("No sites to process. Run app.py first to scan for newsletters.")
        return
    logger.info(f"📧 Using {len(EMAIL_ADDRESSES)} email addresses")
    logger.info(f"🎯 Processing {len(sites)} sites")
    logger.info(f"📝 Strategy: Try first email, if successful then register all others\n")
    
    success_count = 0
    fail_count = 0
    skipped_count = 0
    sites_with_success = 0
    
    try:
        for i, site in enumerate(sites, 1):
            logger.info(f"\n{'='*60}")
            logger.info(f"[SITE {i}/{len(sites)}] {site['domain']} (confidence: {site['confidence']})")
            logger.info(f"{'='*60}")
            
            # Try with first email
            first_email = EMAIL_ADDRESSES[0]
            logger.info(f"\n  [1/{len(EMAIL_ADDRESSES)}] Testing with: {first_email}")
            
            success, message = register_to_newsletter(site['url'], first_email, site['paths'])
            save_result(site['domain'], site['url'], first_email, success, message)
            
            if success:
                success_count += 1
                sites_with_success += 1
                logger.info(f"  ✅ {message}")
                time.sleep(3)  # Wait 3 seconds after successful registration
                logger.info(f"  → Registering remaining {len(EMAIL_ADDRESSES) - 1} emails...")
                
                # Register remaining emails
                for j, email in enumerate(EMAIL_ADDRESSES[1:], 2):
                    logger.info(f"\n  [{j}/{len(EMAIL_ADDRESSES)}] Using email: {email}")
                    
                    success2, message2 = register_to_newsletter(site['url'], email, site['paths'])
                    save_result(site['domain'], site['url'], email, success2, message2)
                    
                    if success2:
                        success_count += 1
                        logger.info(f"  ✅ {message2}")
                        time.sleep(3)  # Wait 3 seconds after successful registration
                    else:
                        fail_count += 1
                        logger.info(f"  ❌ {message2}")
                    
                    # Small delay between emails for same site
                    time.sleep(1)
            else:
                fail_count += 1
                skipped_count += len(EMAIL_ADDRESSES) - 1
                logger.info(f"  ❌ {message}")
                logger.info(f"  → Skipping remaining {len(EMAIL_ADDRESSES) - 1} emails (form doesn't work)")
            
            # Delay between different sites
            if i < len(sites):
                logger.info(f"\nWaiting 3 seconds before next site...")
                time.sleep(3)
        
        total_attempts = success_count + fail_count
        logger.info("\n" + "="*60)
        logger.info("📊 REGISTRATION SUMMARY")
        logger.info(f"Total sites processed: {len(sites)}")
        logger.info(f"Sites with working forms: {sites_with_success} ({sites_with_success/len(sites)*100:.1f}%)")
        logger.info(f"Total registration attempts: {total_attempts}")
        logger.info(f"✅ Successful registrations: {success_count}")
        logger.info(f"❌ Failed registrations: {fail_count}")
        logger.info(f"⏭️  Skipped (no working form): {skipped_count}")
        logger.info(f"📝 Results saved to: {OUTPUT_CSV}")
        logger.info("="*60)
    except Exception as e:
        logger.error(f"Fatal error: {e}")

if __name__ == "__main__":
    run()

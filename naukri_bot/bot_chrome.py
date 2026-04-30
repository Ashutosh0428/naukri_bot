import email
import imaplib
import json
import logging
import os
import re
import sys
import random
import base64
import traceback
import time
from datetime import datetime

import requests
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s:%(levelname)s:%(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

# ---------------------------------------------------------------------------
# Credentials — env vars (GitHub Secrets) take priority over credentials.json
# ---------------------------------------------------------------------------
def load_credentials():
    username = os.environ.get("NAUKRI_USERNAME")
    password = os.environ.get("NAUKRI_PASSWORD")
    resume_path = os.environ.get("RESUME_FILE_PATH", "")

    if not username or not password:
        creds_file = os.path.join(os.path.dirname(__file__), "credentials.json")
        if os.path.exists(creds_file):
            with open(creds_file) as f:
                creds = json.load(f)
            username = creds.get("username", username)
            password = creds.get("password", password)
            resume_path = creds.get("resume_path", resume_path)

    if not username or not password:
        raise ValueError("NAUKRI_USERNAME and NAUKRI_PASSWORD must be set")

    # Default: resume.pdf in same folder as this script
    if not resume_path:
        resume_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resume.pdf")

    return username, password, resume_path


USERNAME, PASSWORD, RESUME_PATH = load_credentials()
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")    # from @BotFather
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")  # your personal chat ID


# ---------------------------------------------------------------------------
# Telegram notification
# ---------------------------------------------------------------------------
def send_telegram(message: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logging.warning("Telegram not configured — skipping notification")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        r = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=15)
        logging.info(f"Telegram sent [{r.status_code}]: {message[:60]}")
    except Exception as e:
        logging.error(f"Telegram send failed: {e}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def human_delay(min_sec=1, max_sec=3):
    time.sleep(random.uniform(min_sec, max_sec))


def click_js(driver, element):
    driver.execute_script("arguments[0].click();", element)
    human_delay(0.5, 1.5)


def scroll_to(driver, element):
    driver.execute_script("arguments[0].scrollIntoView(true);", element)
    human_delay(0.5, 1.0)


def type_slow(element, text):
    element.clear()
    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(0.05, 0.15))


def build_driver() -> webdriver.Chrome:
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-extensions")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_experimental_option(
        "prefs", {"credentials_enable_service": False, "profile.password_manager_enabled": False}
    )

    driver = webdriver.Chrome(options=options)
    driver.execute_cdp_cmd(
        "Network.setUserAgentOverride",
        {"userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"},
    )
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    driver.execute_script("Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]})")
    driver.execute_script("Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']})")
    return driver


# ---------------------------------------------------------------------------
# Cookie persistence — avoids OTP on repeated runs
# ---------------------------------------------------------------------------
COOKIES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "naukri_cookies.json")


def save_cookies(driver):
    try:
        with open(COOKIES_FILE, "w") as f:
            json.dump(driver.get_cookies(), f)
        logging.info(f"Cookies saved: {COOKIES_FILE}")
    except Exception as e:
        logging.warning(f"Cookie save failed: {e}")


def try_cookie_login(driver) -> bool:
    if not os.path.exists(COOKIES_FILE):
        logging.info("No cookies file — will do fresh login")
        return False
    try:
        driver.get("https://www.naukri.com")
        human_delay(2, 3)
        with open(COOKIES_FILE) as f:
            cookies = json.load(f)
        for cookie in cookies:
            cookie.pop("sameSite", None)
            try:
                driver.add_cookie(cookie)
            except Exception:
                pass
        driver.get("https://www.naukri.com/mnjuser/profile")
        human_delay(5, 7)
        cur = driver.current_url
        logging.info(f"Cookie login check URL: {cur}")
        if "mnjuser/profile" in cur and "nlogin" not in cur:
            logging.info("Cookie login OK — skipping OTP entirely")
            return True
        logging.info(f"Cookies stale/invalid (redirected to {cur}) — fresh login")
        return False
    except Exception as e:
        logging.warning(f"Cookie login attempt failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------
def login(driver):
    logging.info("Logging in...")

    # Reuse saved session — skips OTP on GitHub Actions
    if try_cookie_login(driver):
        return

    driver.get("https://www.naukri.com/nlogin/login")
    human_delay(3, 5)

    email_input = WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.ID, "usernameField"))
    )
    email_input.click()
    human_delay(0.5, 1)
    type_slow(email_input, USERNAME)
    human_delay(1, 2)

    pwd_input = driver.find_element(By.ID, "passwordField")
    pwd_input.click()
    human_delay(0.5, 1)
    type_slow(pwd_input, PASSWORD)
    human_delay(1, 2)

    login_btn = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable(
            (By.XPATH, "//button[@type='submit' and normalize-space(text())='Login']")
        )
    )
    click_js(driver, login_btn)
    human_delay(8, 12)

    logging.info(f"Post-click URL: {driver.current_url}")

    # If still on login page → OTP challenge (Naukri overlays OTP on same URL)
    if "nlogin/login" in driver.current_url:
        logging.info("Still on login page — OTP required")
        handle_otp_if_present(driver)
        if "nlogin/login" in driver.current_url:
            driver.save_screenshot("/tmp/login_failed.png")
            raise Exception(
                f"Login failed — still on login page after OTP attempt. "
                f"Check credentials or screenshot at /tmp/login_failed.png"
            )

    save_cookies(driver)
    logging.info("Login done")


def get_otp_from_gmail(max_wait_sec: int = 90) -> str:
    """Read the NEWEST Naukri OTP from Gmail. Waits for fresh email."""
    import email.utils as eutils
    gmail_user = os.environ.get("GMAIL_USER", "Ashutosh14072@gmail.com")
    gmail_app_password = os.environ.get("GMAIL_APP_PASSWORD", "")
    if not gmail_app_password:
        raise Exception("GMAIL_APP_PASSWORD secret not set")

    # Record time BEFORE waiting so we can filter emails sent after this point
    triggered_at = time.time()

    # Give Naukri time to actually send the email
    logging.info("Waiting 20s for Naukri OTP email to arrive...")
    time.sleep(20)

    logging.info(f"Polling Gmail for OTP (up to {max_wait_sec}s total)...")
    deadline = triggered_at + max_wait_sec

    while time.time() < deadline:
        try:
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            mail.login(gmail_user, gmail_app_password)
            mail.select("inbox")

            _, msgs = mail.search(None, 'FROM "naukri"')
            if msgs[0]:
                ids = msgs[0].split()
                # Walk most-recent first, stop at first fresh OTP
                for msg_id in reversed(ids[-10:]):
                    _, data = mail.fetch(msg_id, "(RFC822)")
                    raw = data[0][1]
                    msg_obj = email.message_from_bytes(raw)

                    # Skip emails older than when we triggered login
                    date_hdr = msg_obj.get("Date", "")
                    try:
                        email_ts = eutils.parsedate_to_datetime(date_hdr).timestamp()
                        age = triggered_at - email_ts
                        if age > 120:           # older than 2 min before trigger
                            logging.info(f"Skipping old email (age {int(age)}s): {date_hdr}")
                            continue
                    except Exception:
                        pass  # can't parse date — still try

                    body = ""
                    if msg_obj.is_multipart():
                        for part in msg_obj.walk():
                            if part.get_content_type() in ("text/plain", "text/html"):
                                body = part.get_payload(decode=True).decode(errors="ignore")
                                break
                    else:
                        body = msg_obj.get_payload(decode=True).decode(errors="ignore")

                    match = re.search(r'\b(\d{6})\b', body)
                    if match:
                        otp = match.group(1)
                        logging.info(f"OTP found: {otp} | email date: {date_hdr}")
                        mail.store(msg_id, "+FLAGS", "\\Seen")   # mark read
                        mail.close()
                        mail.logout()
                        return otp

            mail.close()
            mail.logout()

        except Exception as e:
            logging.warning(f"Gmail IMAP attempt: {e}")

        time.sleep(5)

    raise Exception(f"OTP not received in Gmail within {max_wait_sec}s")


def handle_otp_if_present(driver):
    """Handle OTP challenge — only called when post-login URL is still the login page."""
    # Extra wait: Naukri overlays OTP form dynamically after login click
    human_delay(4, 6)
    driver.save_screenshot("/tmp/otp_page.png")

    src = driver.page_source.lower()
    logging.info(f"'otp' in page source: {'otp' in src}")

    if "otp" not in src and "verification" not in src and "verify" not in src:
        # No OTP — likely wrong password or account issue
        logging.warning("No OTP content on login page — check credentials")
        return

    # Find OTP input — Naukri may use various attributes
    otp_input = None
    for by, sel in [
        (By.XPATH, "//input[contains(translate(@placeholder,'OTP','otp'),'otp')]"),
        (By.XPATH, "//input[contains(@id,'otp') or contains(@name,'otp') or contains(@class,'otp')]"),
        (By.XPATH, "//input[@type='number']"),
        (By.XPATH, "//input[@type='tel']"),
        (By.XPATH, "//input[@type='text' and @maxlength='6']"),
        (By.XPATH, "//input[@type='text' and @maxlength]"),
    ]:
        try:
            otp_input = WebDriverWait(driver, 3).until(EC.presence_of_element_located((by, sel)))
            logging.info(f"OTP input found: {sel}")
            break
        except TimeoutException:
            continue

    if not otp_input:
        logging.error("OTP text found but no input field — check /tmp/otp_page.png")
        return

    logging.info("Reading OTP from Gmail...")
    otp = get_otp_from_gmail(max_wait_sec=90)
    logging.info(f"Entering OTP: {otp}")

    # Approach 1: JS native setter + React synthetic events
    driver.execute_script("""
        var inp = arguments[0], val = arguments[1];
        var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        setter.call(inp, val);
        inp.dispatchEvent(new Event('input',  { bubbles: true }));
        inp.dispatchEvent(new Event('change', { bubbles: true }));
        inp.dispatchEvent(new Event('keyup',  { bubbles: true }));
    """, otp_input, otp)
    human_delay(0.5, 1)

    filled_val = otp_input.get_attribute("value") or ""
    logging.info(f"After JS fill, value='{filled_val}'")

    if not filled_val:
        # Approach 2: direct send_keys character by character
        logging.info("JS fill empty — using send_keys fallback")
        otp_input.click()
        human_delay(0.3, 0.6)
        otp_input.clear()
        for char in otp:
            otp_input.send_keys(char)
            time.sleep(0.12)
        human_delay(0.5, 1)
        filled_val = otp_input.get_attribute("value") or ""
        logging.info(f"After send_keys, value='{filled_val}'")

    # Try Verify button — regular Selenium click first, JS fallback
    submitted = False
    for sel in ["//button[contains(text(),'Verify')]", "//button[contains(text(),'Submit')]",
                "//button[contains(text(),'Continue')]", "//button[@type='submit']",
                "//input[@type='submit']"]:
        try:
            btn = WebDriverWait(driver, 4).until(EC.element_to_be_clickable((By.XPATH, sel)))
            try:
                btn.click()
            except Exception:
                driver.execute_script("arguments[0].click();", btn)
            logging.info(f"OTP submitted via: {sel}")
            submitted = True
            break
        except TimeoutException:
            continue

    if not submitted:
        logging.error("Could not find OTP submit button")

    human_delay(10, 14)
    driver.save_screenshot("/tmp/post_otp.png")
    logging.info(f"Post-OTP URL: {driver.current_url}")
    logging.info(f"Post-OTP title: {driver.title}")


# ---------------------------------------------------------------------------
# Headline dot-toggle (keeps profile "last active" date fresh)
# ---------------------------------------------------------------------------
def toggle_headline_dot(driver) -> str:
    logging.info("Toggling headline dot...")
    driver.get("https://www.naukri.com/mnjuser/profile")
    human_delay(5, 8)

    # Log page title + URL to help debug
    logging.info(f"Page: {driver.title} | URL: {driver.current_url}")

    # Try JS approach first — most reliable across Naukri DOM changes
    clicked = driver.execute_script("""
        var selectors = [
            '#lazyResumeHead .edit.icon',
            '#lazyResumeHead span.edit',
            '.resumeHeadline .edit',
            '.widgetHead .edit',
            'span.edit.icon'
        ];
        for (var s of selectors) {
            var el = document.querySelector(s);
            if (el) { el.click(); return 'clicked: ' + s; }
        }
        // Try by text content (material icon font)
        var spans = document.querySelectorAll('span');
        for (var sp of spans) {
            if (sp.textContent.trim() === 'editOneTheme' || sp.textContent.trim() === 'edit') {
                var rect = sp.getBoundingClientRect();
                if (rect.top > 0) { sp.click(); return 'clicked by text: ' + sp.textContent.trim(); }
            }
        }
        return null;
    """)

    if clicked:
        logging.info(f"JS click: {clicked}")
        human_delay(1, 2)
    else:
        # Fallback to Selenium selectors
        edit_selectors = [
            (By.XPATH, "//span[contains(@class,'edit') and contains(@class,'icon')]"),
            (By.XPATH, "//span[text()='editOneTheme']"),
            (By.XPATH, "//span[normalize-space(text())='edit' and contains(@class,'nI-gNb')]"),
            (By.XPATH, "//div[@id='lazyResumeHead']//span[contains(@class,'edit')]"),
            (By.XPATH, "//div[contains(@class,'resumeHeadline')]//span"),
            (By.CSS_SELECTOR, ".resumeHeadline .editIcon"),
            (By.CSS_SELECTOR, "#lazyResumeHead .edit"),
        ]
        edit_btn = None
        for by, sel in edit_selectors:
            try:
                edit_btn = WebDriverWait(driver, 4).until(EC.element_to_be_clickable((by, sel)))
                logging.info(f"Edit button found: {sel}")
                break
            except TimeoutException:
                continue

        if not edit_btn:
            driver.save_screenshot("/tmp/profile_page_debug.png")
            # Log all span classes to help debug
            spans_info = driver.execute_script(
                "return Array.from(document.querySelectorAll('span')).slice(0,30).map(s => s.className + '|' + s.textContent.trim().slice(0,20))"
            )
            logging.error(f"Spans on page: {spans_info}")
            raise Exception("Could not find headline edit button")

        scroll_to(driver, edit_btn)
        click_js(driver, edit_btn)

    textarea = WebDriverWait(driver, 10).until(
        EC.visibility_of_element_located((By.ID, "resumeHeadlineTxt"))
    )
    human_delay(0.5, 1.5)
    current = textarea.get_attribute("value") or ""

    new_val = current[:-1] if current.endswith(".") else current + "."
    action = "removed dot" if current.endswith(".") else "added dot"

    type_slow(textarea, new_val)
    human_delay(1, 2)

    save_selectors = [
        (By.XPATH, "//button[@type='submit' and contains(@class,'btn-dark')]"),
        (By.XPATH, "//button[normalize-space(text())='Save']"),
        (By.CSS_SELECTOR, "button.btn-dark-ot[type='submit']"),
    ]
    for by, sel in save_selectors:
        try:
            save_btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((by, sel)))
            click_js(driver, save_btn)
            logging.info(f"Saved — {action}")
            human_delay(2, 4)
            return action
        except TimeoutException:
            continue

    raise Exception("Could not find save button")


# ---------------------------------------------------------------------------
# Resume upload — supports local path or base64 via RESUME_BASE64 env var
# ---------------------------------------------------------------------------
def upload_resume(driver) -> bool:
    resume_b64 = os.environ.get("RESUME_BASE64", "")
    resume_file = RESUME_PATH

    if resume_b64:
        tmp_path = "/tmp/resume.pdf"
        with open(tmp_path, "wb") as f:
            f.write(base64.b64decode(resume_b64))
        resume_file = tmp_path
        logging.info("Resume decoded from RESUME_BASE64")

    if not resume_file or not os.path.exists(resume_file):
        logging.info("No resume file — skipping upload")
        return False

    logging.info(f"Uploading resume: {resume_file}")
    try:
        file_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//input[@type='file']"))
        )
        file_input.send_keys(os.path.abspath(resume_file))
        human_delay(3, 5)
        logging.info("Resume uploaded")
        return True
    except Exception as e:
        logging.warning(f"Resume upload failed (non-fatal): {e}")
        return False


# ---------------------------------------------------------------------------
# Get last-updated text from profile page
# ---------------------------------------------------------------------------
def get_last_updated(driver) -> str:
    try:
        el = WebDriverWait(driver, 8).until(
            EC.visibility_of_element_located(
                (By.XPATH, "//div[contains(@class,'mod-date')]//span[contains(@class,'mod-date-val')]")
            )
        )
        return el.text
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    now = datetime.now().strftime("%d-%m-%Y %H:%M")
    logging.info(f"Run started: {now}")

    driver = None
    try:
        driver = build_driver()
        login(driver)
        action = toggle_headline_dot(driver)
        resume_uploaded = upload_resume(driver)
        last_updated = get_last_updated(driver)

        msg = (
            f"✅ Naukri updated!\n"
            f"Action: {action}\n"
            f"Resume: {'uploaded ✓' if resume_uploaded else 'skipped'}\n"
            f"Last active: {last_updated}\n"
            f"Time: {now} IST"
        )
        logging.info(msg)
        send_telegram(msg)

    except Exception as e:
        err = f"❌ Naukri bot FAILED\nError: {str(e)}\nTime: {now} IST"
        logging.error(err)
        logging.error(traceback.format_exc())
        send_telegram(err)
        sys.exit(1)
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


if __name__ == "__main__":
    main()

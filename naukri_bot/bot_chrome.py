import json
import logging
import os
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
# Login
# ---------------------------------------------------------------------------
def login(driver):
    logging.info("Logging in...")
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

    # Handle OTP screen if Naukri requires verification from new IP
    handle_otp_if_present(driver)
    logging.info("Login done")


def handle_otp_if_present(driver):
    """If Naukri shows OTP screen, detect it and raise clear error."""
    try:
        otp_input = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located(
                (By.XPATH, "//input[contains(@placeholder,'OTP') or contains(@id,'otp') or contains(@name,'otp')]")
            )
        )
        # OTP screen detected — take screenshot for debugging
        driver.save_screenshot("/tmp/otp_screen.png")
        logging.error("OTP screen detected! Naukri requires manual OTP verification.")
        logging.error("FIX: Log in manually once from the GitHub Actions IP to mark it as trusted.")
        logging.error(f"Current URL: {driver.current_url}")
        raise Exception(
            "OTP required — Naukri flagged GitHub Actions IP as new device. "
            "Run the bot manually once OR log in to naukri.com and verify the device."
        )
    except TimeoutException:
        pass  # No OTP — good


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

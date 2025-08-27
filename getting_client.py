import os
import re
import time
from typing import Optional, Any

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from impresso import connect
import urllib.parse  # added


TOKEN_URL = "https://impresso-project.ch/datalab/token"

# Prefer JWT-like tokens; fallbacks require longer lengths to avoid picking CSRF/session IDs
JWT_REGEX = r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+'
HEX_LONG_REGEX = r'[a-fA-F0-9]{64,}'
BASE64ISH_LONG_REGEX = r'[A-Za-z0-9_\-]{64,}'

DEFAULT_EMAIL_SELECTORS = [
    'input[type="email"]',
    'input[name="email"]',
    '#email',
    'input[name="username"]',
]
DEFAULT_PASSWORD_SELECTORS = [
    'input[type="password"]',
    '#password',
    'input[name="password"]',
]
DEFAULT_SUBMIT_SELECTORS = [
    'button[type="submit"]',
    'input[type="submit"]',
    'button:has-text("Sign in")',
    'button:has-text("Log in")',
    'button:has-text("Continue")',
    'button:has-text("Next")',
]

DEFAULT_GENERATE_SELECTORS = [
    'button:has-text("Generate token")',
    'button:has-text("Generate")',
    'a:has-text("Generate token")',
    'a:has-text("Generate")',
    'text=Generate token',
]

DEFAULT_TOKEN_SELECTORS = [
    '[data-testid="token"]',
    'input[readonly]',
    'input[type="text"]',
    'textarea[readonly]',
    'code',
    'pre',
]

# New: triggers for the login modal and common "terms" buttons
DEFAULT_LOGIN_TRIGGER_SELECTORS = [
    'button:has-text("LOG IN OR REGISTER")',
    'text=LOG IN OR REGISTER',
    'button:has-text("Log in or register")',
]
DEFAULT_TERMS_OPEN_SELECTORS = [
    'button:has-text("READ AND ACCEPT THE TERMS OF USE TO GENERATE THE TOKEN")',
    'text=READ AND ACCEPT THE TERMS OF USE TO GENERATE THE TOKEN',
    'button:has-text("TERMS OF USE")',
]
DEFAULT_TERMS_ACCEPT_SELECTORS = [
    'button:has-text("Accept")',
    'button:has-text("I accept")',
    'button:has-text("I agree")',
    'button:has-text("ACCEPT")',
]

# New: placeholder keywords for inputs labeled like "User Name" and "Password"
EMAIL_PLACEHOLDER_KEYWORDS = ["User Name", "Username", "Email"]
PASSWORD_PLACEHOLDER_KEYWORDS = ["Password"]

# Extend default selectors with placeholder/aria-label/label-based fallbacks
DEFAULT_EMAIL_SELECTORS.extend([
    'input[placeholder="User Name"]',
    'input[placeholder*="User Name"]',
    'input[placeholder*="Username"]',
    'input[placeholder*="Email"]',
    'input[aria-label="User Name"]',
    'input[aria-label*="User Name"]',
    'input[aria-label*="Username"]',
    'input[aria-label*="Email"]',
    'xpath=//label[contains(normalize-space(.),"User Name")]/following::input[1]',
    'xpath=//label[contains(normalize-space(.),"Username")]/following::input[1]',
    'xpath=//label[contains(normalize-space(.),"Email")]/following::input[1]',
])

DEFAULT_PASSWORD_SELECTORS.extend([
    'input[placeholder="Password"]',
    'input[placeholder*="Password"]',
    'input[aria-label="Password"]',
    'input[aria-label*="Password"]',
    'xpath=//label[contains(normalize-space(.),"Password")]/following::input[1]',
])

DEFAULT_SUBMIT_SELECTORS = [
    'button[type="submit"]',
    'input[type="submit"]',
    'button:has-text("Sign in")',
    'button:has-text("Log in")',
    'button:has-text("Continue")',
    'button:has-text("Next")',
]

DEFAULT_GENERATE_SELECTORS = [
    'button:has-text("Generate token")',
    'button:has-text("Generate")',
    'a:has-text("Generate token")',
    'a:has-text("Generate")',
    'text=Generate token',
]

DEFAULT_TOKEN_SELECTORS = [
    '[data-testid="token"]',
    'input[readonly]',
    'input[type="text"]',
    'textarea[readonly]',
    'code',
    'pre',
]

# New: triggers for the login modal and common "terms" buttons
DEFAULT_LOGIN_TRIGGER_SELECTORS = [
    'button:has-text("LOG IN OR REGISTER")',
    'text=LOG IN OR REGISTER',
    'button:has-text("Log in or register")',
]
DEFAULT_TERMS_OPEN_SELECTORS = [
    'button:has-text("READ AND ACCEPT THE TERMS OF USE TO GENERATE THE TOKEN")',
    'text=READ AND ACCEPT THE TERMS OF USE TO GENERATE THE TOKEN',
    'button:has-text("TERMS OF USE")',
]
DEFAULT_TERMS_ACCEPT_SELECTORS = [
    'button:has-text("Accept")',
    'button:has-text("I accept")',
    'button:has-text("I agree")',
    'button:has-text("ACCEPT")',
]

# New: selectors used on the second login choice and form
DEFAULT_SECOND_LOGIN_CHOICE_SELECTORS = [
    'button:has-text("Log in")',
    'a:has-text("Log in")',
    'role=button[name="Log in"]',
    'text=Log in',
]


def _first_selector(page, selectors, timeout_ms=5000):
    last_err = None
    slice_timeout = max(1000, timeout_ms // max(1, len(selectors)))
    for sel in selectors:
        try:
            el = page.wait_for_selector(sel, timeout=slice_timeout, state="visible")
            if el:
                return el
        except Exception as e:
            last_err = e
    if last_err:
        raise last_err
    raise PlaywrightTimeoutError("No selector matched")

# New: search for the first visible selector across all frames (helps when login form is inside an iframe)
def _first_selector_any_frame(page, selectors, timeout_ms=5000):
    deadline = time.time() + (timeout_ms / 1000.0)
    last_err = None
    while time.time() < deadline:
        for sel in selectors:
            for frame in page.frames:
                try:
                    el = frame.wait_for_selector(sel, state="visible", timeout=750)
                    if el:
                        return el
                except Exception as e:
                    last_err = e
        time.sleep(0.1)
    if last_err:
        raise last_err
    raise PlaywrightTimeoutError("No selector matched in any frame")

# Token utilities
def _clean_token_artifacts(s: str) -> str:
    if s is None:
        return s
    # Trim whitespace and remove common surrounding quotes and zero-width chars
    s = s.strip().strip('"').strip("'")
    s = s.replace('\u200b', '').replace('\u200c', '').replace('\ufeff', '')
    # Also remove actual zero-width characters if present
    s = s.replace('\u200b', '').replace('\u200c', '').replace('\ufeff', '')
    # Collapse whitespace within
    return re.sub(r'\s+', '', s)


def _is_plausible_token(tok: str) -> bool:
    if not tok:
        return False
    tok = tok.strip()
    if re.fullmatch(JWT_REGEX, tok):
        return True
    if re.fullmatch(HEX_LONG_REGEX, tok):
        return True
    if re.fullmatch(BASE64ISH_LONG_REGEX, tok):
        return True
    return False

# New: dump what we see for debugging the first login UI
def _dump_login_debug(page) -> None:
    try:
        print("    [debug] page url:", page.url)
    except Exception:
        pass
    try:
        print("    [debug] page title:", page.title())
    except Exception:
        pass

    # List frames
    try:
        frames = page.frames
        print(f"    [debug] frames: {len(frames)}")
        for idx, f in enumerate(frames):
            u = ""
            try:
                u = f.url
            except Exception:
                pass
            print(f"      - frame[{idx}]: {u}")
    except Exception:
        pass

    # Visible inputs
    def _safe(el, attr):
        try:
            return el.get_attribute(attr) or ""
        except Exception:
            return ""

    try:
        print("    [debug] visible inputs (first 25 per frame):")
        for idx, f in enumerate(page.frames):
            try:
                els = f.query_selector_all("input")
            except Exception:
                continue
            shown = 0
            for el in els:
                try:
                    if not el.is_visible():
                        continue
                except Exception:
                    continue
                t = (_safe(el, "type") or "").lower()
                name = _safe(el, "name")
                fid = _safe(el, "id")
                ph = _safe(el, "placeholder")
                aria = _safe(el, "aria-label")
                print(f"      frame[{idx}] <input type='{t}' name='{name}' id='{fid}' placeholder='{ph}' aria-label='{aria}'>")
                shown += 1
                if shown >= 25:
                    break
    except Exception:
        pass

    # Visible buttons/submit/links
    try:
        print("    [debug] visible buttons/submit/links (first 25 per frame):")
        btn_sel = "button, input[type='submit'], a[role='button']"
        for idx, f in enumerate(page.frames):
            try:
                els = f.query_selector_all(btn_sel)
            except Exception:
                continue
            shown = 0
            for el in els:
                try:
                    if not el.is_visible():
                        continue
                except Exception:
                    continue
                tag = ""
                try:
                    tag = el.evaluate("e => e.tagName")
                except Exception:
                    pass
                text = ""
                try:
                    # inner_text can be expensive; keep short
                    text = (el.inner_text() or "").strip().replace("\n", " ")
                except Exception:
                    pass
                val = _safe(el, "value")
                print(f"      frame[{idx}] <{tag}> text='{text[:80]}' value='{val}'")
                shown += 1
                if shown >= 25:
                    break
    except Exception:
        pass


def _attempt_login(page, email: Optional[str], password: Optional[str], timeout_ms=15000) -> bool:
    if not email or not password:
        return False
    # Find email/username field
    try:
        email_el = _first_selector(page, DEFAULT_EMAIL_SELECTORS, timeout_ms)
        print("    [debug] login: found username/email by selector.")
    except PlaywrightTimeoutError:
        # Try across iframes
        try:
            email_el = _first_selector_any_frame(page, DEFAULT_EMAIL_SELECTORS, timeout_ms=timeout_ms)
            print("    [debug] login: found username/email inside an iframe by selector.")
        except PlaywrightTimeoutError:
            # Placeholder/aria-label across frames
            try:
                email_el = _find_input_by_placeholder(page, EMAIL_PLACEHOLDER_KEYWORDS, types=("text","email",None), timeout_ms=timeout_ms)
                print("    [debug] login: found username/email by placeholder/aria-label.")
            except PlaywrightTimeoutError:
                print("    [debug] login: username/email field not found. Dumping page info...")
                _dump_login_debug(page)
                return False

    email_el.fill(email)

    # Find password field
    try:
        pwd_el = _first_selector(page, DEFAULT_PASSWORD_SELECTORS, 5000)
        print("    [debug] login: found password by selector.")
    except PlaywrightTimeoutError:
        try:
            pwd_el = _first_selector_any_frame(page, DEFAULT_PASSWORD_SELECTORS, timeout_ms=5000)
            print("    [debug] login: found password inside an iframe by selector.")
        except PlaywrightTimeoutError:
            try:
                pwd_el = _find_input_by_placeholder(page, PASSWORD_PLACEHOLDER_KEYWORDS, types=("password","text",None), timeout_ms=5000)
                print("    [debug] login: found password by placeholder/aria-label.")
            except PlaywrightTimeoutError:
                print("    [debug] login: password field not found. Dumping page info...")
                _dump_login_debug(page)
                return False

    pwd_el.fill(password)

    # Submit
    try:
        submit_el = _first_selector(page, DEFAULT_SUBMIT_SELECTORS, 5000)
        submit_el.click()
    except Exception:
        try:
            submit_el = _first_selector_any_frame(page, DEFAULT_SUBMIT_SELECTORS, timeout_ms=2000)
            submit_el.click()
        except Exception:
            pwd_el.press("Enter")

    try:
        page.wait_for_load_state("networkidle", timeout=20000)
    except Exception:
        pass
    return True


def _click_generate(page, custom_selector: Optional[str]) -> None:
    candidates = []
    if custom_selector:
        candidates.append(custom_selector)
    candidates.extend(DEFAULT_GENERATE_SELECTORS)
    for sel in candidates:
        try:
            page.click(sel, timeout=5000)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            return
        except Exception:
            continue
    raise RuntimeError("Could not find/click the 'Generate token' button. Set GENERATE_SELECTOR in .env")


def _extract_token(page, custom_selector: Optional[str]) -> str:
    candidates = []
    if custom_selector:
        candidates.append(custom_selector)
    candidates.extend(DEFAULT_TOKEN_SELECTORS)

    # Try straightforward elements first
    for sel in candidates:
        try:
            el = page.wait_for_selector(sel, timeout=3000)
            if not el:
                continue
            # Prefer value for inputs/textarea
            try:
                val = el.input_value()
                token = _clean_token_artifacts((val or "").strip())
                # Only accept plausible tokens to avoid CSRF/session ids
                if _is_plausible_token(token):
                    return token
            except Exception:
                txt = _clean_token_artifacts((el.inner_text() or "").strip())
                # Pick JWT first
                m = re.search(JWT_REGEX, txt)
                if m:
                    return m.group(0)
                # Fallback: long hex or long base64ish
                m = re.search(HEX_LONG_REGEX, txt)
                if m:
                    return m.group(0)
                m = re.search(BASE64ISH_LONG_REGEX, txt)
                if m:
                    return m.group(0)
        except Exception:
            continue

    # Fallback: scan whole page content
    html = _clean_token_artifacts(page.content())
    for rx in [
        JWT_REGEX,
        HEX_LONG_REGEX,
        BASE64ISH_LONG_REGEX,
    ]:
        m = re.search(rx, html)
        if m:
            return m.group(0)

    raise RuntimeError("Could not extract token. Set TOKEN_SELECTOR in .env to a specific element.")


def _open_login_modal(page) -> None:
    # Click "LOG IN OR REGISTER" if present to reveal the email/password form
    for sel in DEFAULT_LOGIN_TRIGGER_SELECTORS:
        try:
            page.click(sel, timeout=2500)
            # Give the modal a moment to render
            page.wait_for_selector('text=Login', timeout=4000)
            return
        except Exception:
            continue
    # If it's not present, assume we are already on the login form or logged in.


def _accept_terms_if_needed(page) -> None:
    # If a "read and accept terms" button is present, open and accept
    for sel in DEFAULT_TERMS_OPEN_SELECTORS:
        try:
            page.click(sel, timeout=2500)
            break
        except Exception:
            continue
    else:
        return  # nothing to accept

    # Try to scroll to bottom (some UIs require reading to enable the accept button)
    try:
        page.mouse.wheel(0, 20000)
    except Exception:
        pass

    for sel in DEFAULT_TERMS_ACCEPT_SELECTORS:
        try:
            page.click(sel, timeout=4000)
            # Wait for dialog to disappear/network to settle
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            return
        except Exception:
            continue


def _goto_with_retries(page, url: str, attempts: int = 3):
    last_err = None
    for i in range(attempts):
        try:
            # Try a lighter wait first, avoids flakiness that causes connection reset
            return page.goto(url, wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            last_err = e
    # Final attempt waiting a bit more
    try:
        return page.goto(url, wait_until="load", timeout=60000)
    except Exception:
        raise last_err or e

# New: small helpers for 401 handling
def _get_status(resp) -> int | None:
    try:
        return resp.status if resp else None
    except Exception:
        return None

def _inject_basic_auth(url: str, username: str, password: str) -> str:
    from urllib.parse import urlsplit, urlunsplit, quote
    parts = urlsplit(url)
    host = parts.hostname or ""
    port = f":{parts.port}" if parts.port else ""
    userinfo = f"{quote(username, safe='')}:{quote(password, safe='')}"
    netloc = f"{userinfo}@{host}{port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def get_impresso_token() -> str:
    load_dotenv()

    headless = os.getenv("HEADLESS", "true").lower() != "false"
    first_email = os.getenv("FIRST_EMAIL")
    first_password = os.getenv("FIRST_PASSWORD")
    # Support either BASIC_AUTH_* or fallback to SECOND_* (kept for completeness)
    basic_user = os.getenv("BASIC_AUTH_USER") or os.getenv("SECOND_EMAIL")
    basic_pass = os.getenv("BASIC_AUTH_PASSWORD") or os.getenv("SECOND_PASSWORD")
    custom_generate_selector = os.getenv("GENERATE_SELECTOR")
    custom_token_selector = os.getenv("TOKEN_SELECTOR")

    # Second-login credentials (UI form)
    second_email = os.getenv("SECOND_EMAIL")
    second_password = os.getenv("SECOND_PASSWORD")

    if not first_email or not first_password:
        raise RuntimeError("Missing FIRST_EMAIL/FIRST_PASSWORD in .env")

    print("[1/5] Launching browser...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context_kwargs = {
            "ignore_https_errors": True,
            "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        }
        if basic_user and basic_pass:
            context_kwargs["http_credentials"] = {"username": basic_user, "password": basic_pass}

        context = browser.new_context(**context_kwargs)
        page = context.new_page()

        print("[2/5] Navigating to token page...")
        resp = _goto_with_retries(page, TOKEN_URL)
        status = _get_status(resp)
        title = ""
        try:
            title = page.title() or ""
        except Exception:
            title = ""

        if status == 401 or "401" in title:
            print(f"    Got 401 (status={status}, title='{title}'). Retrying with HTTP Basic Auth...")
            # Choose credentials for Basic Auth: prefer BASIC_AUTH_*, then FIRST_*, then SECOND_*
            ba_user = os.getenv("BASIC_AUTH_USER") or first_email or second_email
            ba_pass = os.getenv("BASIC_AUTH_PASSWORD") or first_password or second_password
            if not ba_user or not ba_pass:
                raise RuntimeError("401 received and no BASIC_AUTH_USER/BASIC_AUTH_PASSWORD (or FIRST_*/SECOND_*) available in .env")

            # Recreate context with http_credentials
            try:
                page.close()
            except Exception:
                pass
            try:
                context.close()
            except Exception:
                pass

            print("    Recreating context with http_credentials and retrying navigation...")
            context_kwargs["http_credentials"] = {"username": ba_user, "password": ba_pass}
            context = browser.new_context(**context_kwargs)
            page = context.new_page()
            resp = _goto_with_retries(page, TOKEN_URL)
            status = _get_status(resp)
            try:
                title = page.title() or ""
            except Exception:
                title = ""

            if status == 401 or "401" in title:
                print("    Still 401 after http_credentials. Trying credential-in-URL fallback...")
                auth_url = _inject_basic_auth(TOKEN_URL, ba_user, ba_pass)
                resp = _goto_with_retries(page, auth_url)
                status = _get_status(resp)
                try:
                    title = page.title() or ""
                except Exception:
                    title = ""
                if status == 401 or "401" in title:
                    raise RuntimeError("Still 401 after trying http_credentials and credential-in-URL fallback. Check BASIC_AUTH_* in .env.")

        print(f"    Reached token page (status={status or 'unknown'}).")

        # First login (UI)
        print("[3/5] Attempting first login...")
        _open_login_modal(page)  # no-op if not needed
        did_first = _attempt_login(page, first_email, first_password, timeout_ms=10000)
        if did_first:
            print("    Passed first login.")
        else:
            print("    First login form not found; assuming already logged in.")

        # If a second login is required, open the chooser, select "Log in", then submit credentials
        did_second = False
        if second_email and second_password:
            print("[4/5] Checking for second login...")
            try:
                _open_second_login_choice(page)
                _select_second_login_form(page)
                did_second = _attempt_login(page, second_email, second_password, timeout_ms=15000)
            except Exception:
                did_second = False
            if did_second:
                print("    Passed second login.")
            else:
                print("    Second login not detected or already authenticated.")

        # Optional: accept ToU if present (harmless if absent)
        _accept_terms_if_needed(page)

        # Extract token, click Generate if needed
        print("[5/5] Extracting token from page...")
        token = None
        try:
            token = _extract_token(page, custom_token_selector)
        except Exception:
            token = None

        # If not plausible, try clicking Generate and re-extract
        if not token or not _is_plausible_token(token):
            try:
                print("    Token not found or not plausible. Trying 'Generate token' button...")
                _click_generate(page, custom_generate_selector)
                token = _extract_token(page, custom_token_selector)
            except Exception:
                pass

        # Debug print the raw token
        if token is not None:
            cleaned = _clean_token_artifacts(token)
            print(f"    Raw token debug: len={len(token)} repr={token!r}")
            if token != cleaned:
                print(f"    Cleaned token debug: len={len(cleaned)} repr={cleaned!r}")
            token = cleaned

        if not token:
            print("    Token element not found, trying clipboard...")
            token = _read_clipboard_token(page)

        context.close()
        browser.close()

    if not token or not _is_plausible_token(token):
        raise RuntimeError("Token is empty or could not be extracted, or does not look valid.")
    print(f"    Copied token ({len(token)} chars).")
    return token


def get_impresso_client() -> Any:
    """
    Acquire an Impresso API client by performing the automated authentication flow.
    Usage from another module:

        from testing_client import get_impresso_client
        client = get_impresso_client()

    Returns:
        The connected Impresso client instance.
    Raises:
        RuntimeError: If a valid token cannot be retrieved.
    """
    token = get_impresso_token()
    return _connect_with_token(token)


def _connect_with_token(token: str):
    # Export for clients that read env
    os.environ["IMPRESSO_TOKEN"] = token
    os.environ["IMPRESSO_API_TOKEN"] = token

    # Prefer explicit kwarg if supported
    try:
        return connect(token=token)
    except TypeError:
        pass
    except Exception:
        pass

    # Fallback: monkeypatch prompt functions BEFORE calling connect()
    import getpass
    import builtins
    original_getpass = getattr(getpass, "getpass", None)
    original_input = builtins.input
    try:
        if original_getpass:
            getpass.getpass = lambda prompt="": token
        builtins.input = lambda prompt="": token
        return connect()
    finally:
        if original_getpass:
            getpass.getpass = original_getpass
        builtins.input = original_input


# Helper: find an input by placeholder/aria-label keywords (case-insensitive)
def _find_input_by_placeholder(page, keywords, types=("text", "email", "password", None), timeout_ms=5000):
    deadline = time.time() + (timeout_ms / 1000.0)
    lowered = [k.lower() for k in keywords]
    last_err = None
    while time.time() < deadline:
        try:
            for frame in page.frames:
                inputs = frame.query_selector_all("input")
                for el in inputs:
                    try:
                        if not el.is_visible():
                            continue
                    except Exception:
                        continue
                    t = (el.get_attribute("type") or "").lower() or None
                    if types and t not in types:
                        continue
                    ph = (el.get_attribute("placeholder") or "")
                    aria = (el.get_attribute("aria-label") or "")
                    labelish = f"{ph} {aria}".strip().lower()
                    if any(k in labelish for k in lowered):
                        return el
        except Exception as e:
            last_err = e
        time.sleep(0.2)
    raise PlaywrightTimeoutError(f"No input found by placeholder among {keywords}. Last error: {last_err}")


# Helpers for optional second-login UI

def _open_second_login_choice(page, timeout_ms: int = 5000) -> None:
    # Try to click a generic "Log in" choice button/link if present
    try:
        el = _first_selector_any_frame(page, DEFAULT_SECOND_LOGIN_CHOICE_SELECTORS, timeout_ms=timeout_ms)
        try:
            el.click()
        except Exception:
            try:
                page.click('text=Log in', timeout=1500)
            except Exception:
                pass
        try:
            page.wait_for_load_state('networkidle', timeout=4000)
        except Exception:
            pass
    except Exception:
        # No second-login chooser present
        pass


def _select_second_login_form(page, timeout_ms: int = 5000) -> None:
    # No-op if the form is already visible; otherwise attempt to expose it by clicking common toggles
    try:
        _first_selector_any_frame(page, DEFAULT_EMAIL_SELECTORS, timeout_ms=1500)
        return  # form already visible
    except Exception:
        pass
    # Try a few common toggles
    for sel in [
        'button:has-text("Log in")', 'text=Log in',
        'button:has-text("Sign in")', 'text=Sign in',
    ]:
        try:
            page.click(sel, timeout=1000)
            _first_selector_any_frame(page, DEFAULT_EMAIL_SELECTORS, timeout_ms=timeout_ms)
            return
        except Exception:
            continue


def _read_clipboard_token(page) -> Optional[str]:
    # Attempt to read from clipboard via the page context (requires permissions)
    try:
        txt = page.evaluate("() => navigator.clipboard && navigator.clipboard.readText ? navigator.clipboard.readText() : ''")
        tok = _clean_token_artifacts(txt or '')
        if _is_plausible_token(tok):
            print("    Clipboard token found.")
            return tok
    except Exception:
        pass
    return None


if __name__ == "__main__":
    token = get_impresso_token()
    os.environ["IMPRESSO_TOKEN"] = token  # also export for any downstream usage
    client = _connect_with_token(token)
    print("Token acquired and client connected.")
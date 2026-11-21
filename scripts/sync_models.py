import csv
import html
import io
import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
}

PLAY_DEVICES_CSV_URL = "https://storage.googleapis.com/play_public/supported_devices.csv"

MODEL_CODE_REGEX = re.compile(
    r"\b("
    r"SM-[A-Z]\d{3,4}[A-Z0-9]{0,3}|"
    r"CPH\d{4}|OPD\d{4}|P[A-Z]{2,3}[A-Z0-9]\d{2,3}|"
    r"RMX\d{4}|"
    r"V\d{4}[A-Z]?|PD\d{4}[A-Z]?|"
    r"2[1-7]\d{4}[A-Z0-9]{2,4}|M\d{4}[A-Z]\d{1,2}[A-Z]|"
    r"X\d{4}[A-Z]?|K[EFGJL]\d[a-z]?|BG\d[a-z]?|CK\d[a-z]?|CL\d[a-z]?|CM\d[a-z]?|"
    r"XT\d{4}(?:-\d|[A-Z])?|"
    r"[A-Z]{3}-(?:LX|NX|AL|AN|TL|BD|L\d)[0-9A-Z]{0,2}"
    r")\b"
)

BIT_REGEX = re.compile(
    r"\b(?:BIT|BINARY|BIN|REV)\s*[:\-]?\s*([1-9A-F](?:\s*[-/]\s*[1-9A-F])?|1[0-6])\b|\b(U[1-9A-F])\b",
    re.IGNORECASE
)
ANDROID_REGEX = re.compile(r"\bAndroid\s*(?:ver(?:sion)?\s*[:\-]?\s*)?(\d{2}(?:\s*[/\-&,]\s*\d{2})*)\b", re.IGNORECASE)
OS_SKIN_REGEX = re.compile(r"\b((?:HyperOS|One\s?UI|MIUI|ColorOS|Funtouch\s?OS|MagicOS|HiOS|XOS)\s*\d*(?:\.\d+)?(?:\s*[/\-]\s*\d+)*)\b", re.IGNORECASE)
PATCH_REGEX = re.compile(
    r"(?:patch|security(?:\s*(?:patch|update))?)\s*[:\-]?\s*"
    r"(202[3-7][-/]\d{1,2}(?:[-/]\d{1,2})?|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s*202[3-7]?)",
    re.IGNORECASE
)
MONTH_PATCH_REGEX = re.compile(
    r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+202[3-7])\s+security",
    re.IGNORECASE
)
SW_VER_REGEX = re.compile(r"software\s+version\s+([\d\.]+)", re.IGNORECASE)
TOOL_VER_REGEX = re.compile(r"\bv\.?\s*(\d+\.\d+(?:\.\d+){0,2})\b", re.IGNORECASE)
CHIP_ID_REGEX = re.compile(r"\b(MT\d{4}[A-Z]?|SM\d{4}|SDM\d{3}|MSM\d{4}|T\d{3,4})\b", re.IGNORECASE)

OP_KEYWORDS = {
    "FRP": ["frp", "google account", "remove frp", "reset frp", "frp bypass"],
    "Factory Reset": ["factory reset", "format", "wipe data", "safe format"],
    "Flash": ["flash", "firmware", "write flash", "unbrick", "read flash", "write dump"],
    "MDM/KG": ["mdm", "kg lock", "knox", "payjoy", "it admin", "demo", "carrier relock", "anti-crack"],
    "Bootloader": ["bootloader", "ubl", "unlock bl", "relock"],
    "IMEI": ["imei", "repair network", "patch cert", "nvram", "efs", "repair security"],
    "Screen Lock": ["screen lock", "pin", "pattern", "passcode", "mi account", "heytap", "huawei id"]
}

MODE_KEYWORDS = {
    "EDL 9008": ["edl", "9008", "firehose", "fbtoedl"],
    "Preloader": ["preloader", "pl mode"],
    "BROM": ["brom", "bootrom"],
    "EUB": ["eub"],
    "MTP": ["mtp"],
    "ADB": ["adb"],
    "Fastboot": ["fastboot"],
    "Mi Assistant": ["mi assistant", "sideload", "recovery mode"],
    "Server / Auth": ["server", "credit", "auth", "online", "instant"],
    "Unisoc Diag": ["diag", "fdl", "spd", "unisoc"],
    "Download Mode": ["download mode", "odin"],
    "Test Point": ["test point", "testpoint", "tp mode", "com 1.0"]
}

CPU_KEYWORDS = {
    "MediaTek": ["mediatek", "mtk", "helio", "dimensity"],
    "Qualcomm": ["qualcomm", "snapdragon", "qcom", "qc"],
    "Unisoc": ["unisoc", "spreadtrum", "spd"],
    "Exynos": ["exynos"],
    "Kirin": ["kirin", "hisilicon"],
    "Tensor": ["tensor"]
}

BRAND_NORMALIZE = {
    "samsung": "Samsung",
    "xiaomi": "Xiaomi",
    "redmi": "Xiaomi",
    "poco": "Xiaomi",
    "oppo": "Oppo",
    "realme": "Realme",
    "vivo": "Vivo",
    "iqoo": "Vivo",
    "tecno": "Tecno",
    "infinix": "Infinix",
    "itel": "Itel",
    "motorola": "Motorola",
    "moto": "Motorola",
    "honor": "Honor",
    "huawei": "Huawei",
    "oneplus": "OnePlus",
    "nokia": "Nokia",
    "google": "Google",
    "lenovo": "Lenovo",
    "nothing": "Nothing",
    "sony": "Sony",
    "asus": "Asus",
    "zte": "ZTE",
    "nubia": "ZTE",
    "tcl": "TCL",
    "alcatel": "Alcatel",
    "lg": "LG",
    "htc": "HTC",
    "meizu": "Meizu",
    "sharp": "Sharp",
    "cubot": "Cubot",
    "umidigi": "Umidigi",
    "doogee": "Doogee",
    "blackview": "Blackview",
    "ulefone": "Ulefone",
    "oukitel": "Oukitel"
}

HYDRA_BRAND_HINTS = {
    "178": "Xiaomi",
    "118": "Oppo",
    "136": "Samsung",
    "257": "Realme",
    "66": "Huawei",
    "154": "Tecno"
}


def normalize_brand(raw_brand: str) -> str:
    cleaned = " ".join(str(raw_brand or "").split()).strip()
    if not cleaned:
        return "Other"
    low = cleaned.lower()
    if low in BRAND_NORMALIZE:
        return BRAND_NORMALIZE[low]
    for key, val in BRAND_NORMALIZE.items():
        if key in low:
            return val
    return cleaned


def decode_play_csv(raw_bytes: bytes) -> str:
    if raw_bytes.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw_bytes.decode("utf-16", errors="replace")
    try:
        return raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw_bytes.decode("latin-1", errors="replace")


def parse_play_devices_csv(csv_text: str) -> dict:
    """Builds lookup dict by both Model code and Device codename (e.g. SM-A155F, ruby, fleur)."""
    lookup = {}
    reader = csv.DictReader(io.StringIO(csv_text))
    for row in reader:
        if not row:
            continue
        raw_brand = (row.get("Retail Branding") or "").strip()
        marketing = " ".join((row.get("Marketing Name") or "").split()).strip()
        raw_device = " ".join((row.get("Device") or "").split()).strip()
        raw_model = " ".join((row.get("Model") or "").split()).strip()
        if not raw_model and not raw_device:
            continue

        brand = normalize_brand(raw_brand)
        marketing = marketing.replace("\\'", "'").strip()
        entry_name = marketing if marketing else raw_model

        keys = set()
        if raw_model:
            upper_model = raw_model.upper()
            keys.add(upper_model)
            if "/" in upper_model:
                keys.add(upper_model.split("/", 1)[0].strip())
            for m in MODEL_CODE_REGEX.findall(upper_model):
                keys.add(m.upper())
        if raw_device and len(raw_device) >= 3:
            keys.add("CODENAME:" + raw_device.upper())

        for key in keys:
            if not key:
                continue
            existing = lookup.get(key)
            if not existing or (existing["marketing_name"].upper() == key and entry_name.upper() != key):
                lookup[key] = {
                    "brand": brand,
                    "marketing_name": entry_name,
                    "model_code": raw_model.upper() if raw_model else ""
                }
    return lookup


def load_play_device_catalog() -> dict:
    try:
        resp = requests.get(PLAY_DEVICES_CSV_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        text = decode_play_csv(resp.content)
        catalog = parse_play_devices_csv(text)
        print(f"[CATALOG] Loaded {len(catalog)} model mappings from Google Play supported_devices.csv")
        return catalog
    except Exception as exc:
        print(f"[WARN] Could not load Google Play supported_devices.csv: {type(exc).__name__}")
        return {}


def infer_brand(code: str, context: str) -> str:
    c = code.upper()
    if c.startswith("SM-"):
        return "Samsung"
    if c.startswith(("CPH", "OPD", "PEQ", "PGF", "PGE", "PFF", "PHY", "PKJ", "PKH", "PHN", "PLE", "PCH", "PEM")):
        return "Oppo"
    if c.startswith("RMX"):
        return "Realme"
    if c.startswith(("V", "PD")):
        return "Vivo"
    if c.startswith("XT"):
        return "Motorola"
    if c.startswith("X"):
        return "Infinix"
    if re.match(r"^(K[EFGJL]|BG|CK|CL|CM)\d", c):
        return "Tecno"
    if re.match(r"^(2[1-7]\d{4}|M\d{4})", c):
        return "Xiaomi"
    low_ctx = context.lower()
    for b in [
        "Samsung", "Xiaomi", "Redmi", "Poco", "Vivo", "Oppo", "Realme",
        "Tecno", "Infinix", "Motorola", "Honor", "Huawei", "OnePlus",
        "Nokia", "Google", "Itel", "Lenovo", "Nothing"
    ]:
        if b.lower() in low_ctx:
            return "Xiaomi" if b in ("Redmi", "Poco") else b
    return "Other"


def lookup_device_info(code: str, context: str, catalog: dict) -> tuple:
    key = code.upper().strip()
    info = catalog.get(key)
    if not info and "/" in key:
        info = catalog.get(key.split("/", 1)[0].strip())
    if not info:
        info = catalog.get("CODENAME:" + key)
    if info:
        brand = info["brand"] if info["brand"] != "Other" else infer_brand(key, context)
        marketing_name = info["marketing_name"] or key
        return brand, marketing_name
    return infer_brand(key, context), key


def extract_bits(text: str) -> str:
    found = []
    for m in BIT_REGEX.finditer(text):
        val = (m.group(1) or m.group(2) or "").upper().replace(" ", "")
        if val:
            label = val if val.startswith("U") else "BIT " + val
            if label not in found:
                found.append(label)
    return ", ".join(found[:4])


def extract_os_versions(text: str) -> str:
    found = []
    for m in ANDROID_REGEX.findall(text):
        cleaned = re.sub(r"\s+", "", m)
        val = "Android " + cleaned
        if val not in found:
            found.append(val)
    for skin in OS_SKIN_REGEX.findall(text):
        clean = " ".join(skin.split())
        if clean not in found:
            found.append(clean)
    sw = SW_VER_REGEX.search(text)
    if sw:
        ver_str = "Ver " + sw.group(1)
        if ver_str not in found:
            found.append(ver_str)
    return ", ".join(found[:3])


def extract_patch(text: str) -> str:
    mp = MONTH_PATCH_REGEX.search(text)
    if mp:
        return mp.group(1).strip()
    m = PATCH_REGEX.search(text)
    if m:
        return m.group(1).strip()
    iso = re.search(r"\b(202[4-7]-\d{2}-\d{2})\b", text)
    if iso and any(k in text.lower() for k in ("patch", "security", "sec")):
        return iso.group(1)
    return ""


def extract_matches(text: str, mapping: dict, default=None) -> list:
    lower = text.lower()
    found = [label for label, kws in mapping.items() if any(kw in lower for kw in kws)]
    return found if found else (default or [])


def extract_cpu(text: str) -> str:
    cpus = extract_matches(text, CPU_KEYWORDS)
    chips = sorted(set(c.upper() for c in CHIP_ID_REGEX.findall(text)))
    return ", ".join((cpus + chips)[:2])


def parse_hydra_device_item(title: str, note: str, brand_hint: str, post_url: str, source: dict, catalog: dict) -> list:
    title = " ".join(title.split()).strip()
    note = " ".join(note.split()).strip()
    if not title or len(title) < 3:
        return []
    low_title = title.lower()
    if low_title in ("load more", "supported devices", "supported models", "supported root models", "brand", "login"):
        return []

    paren_match = re.search(r"\(([^()]{2,55})\)\s*$", title)
    base_name = title
    codes = []

    if paren_match:
        inside = paren_match.group(1).strip()
        left = title[:paren_match.start()].strip()
        left_codes = MODEL_CODE_REGEX.findall(left)
        if left_codes and not MODEL_CODE_REGEX.findall(inside):
            codes = [c.upper() for c in left_codes]
            base_name = inside
        else:
            base_name = left or title
            parts = [p.strip() for p in re.split(r"[/,|]", inside) if p.strip()]
            filtered = [p for p in parts if p.lower() not in ("china", "global", "india", "4g", "5g", "nfc", "lte", "wifi")]
            if filtered:
                codes = [p.upper() for p in filtered]

    if not codes:
        found = MODEL_CODE_REGEX.findall(title)
        if found:
            codes = sorted(set(c.upper() for c in found))
        else:
            slug = re.sub(r"[^A-Z0-9]+", "-", base_name.upper()).strip("-")
            if len(slug) >= 4:
                codes = [slug[:32]]

    combined_text = title + " " + note
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ops = extract_matches(combined_text, OP_KEYWORDS, default=["FRP", "Factory Reset", "Flash"])
    bit = extract_bits(combined_text)
    os_ver = extract_os_versions(combined_text)
    patch = extract_patch(combined_text)
    modes = ", ".join(extract_matches(combined_text, MODE_KEYWORDS)[:3])
    cpu = extract_cpu(combined_text)

    results = []
    for code in codes:
        cat_brand, cat_name = lookup_device_info(code, combined_text, catalog)
        brand = normalize_brand(brand_hint) if brand_hint and brand_hint != "Other" else cat_brand
        if brand == "Other":
            brand = infer_brand(code, combined_text)
        model_name = base_name if base_name and base_name.upper() != code else cat_name
        results.append({
            "brand": brand,
            "model_name": model_name,
            "model_code": code,
            "bit": bit,
            "os_version": os_ver,
            "security_patch": patch,
            "mode": modes,
            "cpu": cpu,
            "tool": source["name"],
            "tool_id": source["id"],
            "tool_version": "",
            "operations": ops,
            "source_url": source.get("display_url") or "https://www.hydradongle.com/devices",
            "post_url": post_url,
            "updated_at": today
        })
    return results


def scrape_hydra_brand_page(brand_url: str, source: dict, catalog: dict, max_pages: int = 3):
    """Scrapes a Hydra Dongle /devices/brand/<id> page (and ?page=2..N if paginated)."""
    m_id = re.search(r"/devices/brand/(\d+)", brand_url)
    brand_hint = HYDRA_BRAND_HINTS.get(m_id.group(1), "") if m_id else ""
    all_records = []
    seen_model_urls = set()
    any_ok = False

    for page_num in range(1, max_pages + 1):
        page_url = brand_url if page_num == 1 else f"{brand_url}?page={page_num}"
        try:
            resp = requests.get(page_url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            any_ok = True
        except Exception as exc:
            if page_num == 1:
                print(f"  [WARN] Hydra brand {brand_url}: {type(exc).__name__}")
            break

        soup = BeautifulSoup(resp.text, "html.parser")
        if not brand_hint:
            h = soup.select_one("h1, h2, .breadcrumb .active")
            if h:
                htxt = h.get_text(" ", strip=True)
                if "supported" not in htxt.lower() and "brand" not in htxt.lower():
                    brand_hint = normalize_brand(htxt)

        links = soup.select('a[href*="/devices/brand/model/"]')
        page_new = 0
        for a in links:
            href = urljoin(brand_url, a.get("href", ""))
            if href in seen_model_urls:
                continue
            seen_model_urls.add(href)
            page_new += 1

            title = a.get_text(" ", strip=True)
            note = ""
            parent = a.parent
            if parent:
                full_parent = parent.get_text(" ", strip=True)
                if len(full_parent) > len(title) + 5:
                    note = full_parent.replace(title, "", 1).strip()

            all_records.extend(parse_hydra_device_item(title, note, brand_hint, href, source, catalog))

        if page_new == 0:
            break

    return all_records, any_ok


def scrape_hydra_devices_hub(hub_url: str, source: dict, catalog: dict):
    """Discovers /devices/brand/<id> links from https://www.hydradongle.com/devices and scrapes them."""
    brand_urls = []
    seen = set()
    try:
        resp = requests.get(hub_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.select('a[href*="/devices/brand/"]'):
            href = urljoin(hub_url, a.get("href", "")).split("?")[0].rstrip("/")
            if "/model/" in href:
                continue
            if re.search(r"/devices/brand/\d+$", href) and href not in seen:
                seen.add(href)
                brand_urls.append(href)
    except Exception as exc:
        print(f"  [WARN] Hydra hub ({hub_url}): {type(exc).__name__}")

    # Always ensure major brands are included even if the hub paginates via JS
    for bid in ("178", "118", "136", "257", "66", "154"):
        u = f"https://www.hydradongle.com/devices/brand/{bid}"
        if u not in seen:
            seen.add(u)
            brand_urls.append(u)

    all_records = []
    any_ok = False
    for burl in brand_urls[:20]:
        recs, ok = scrape_hydra_brand_page(burl, source, catalog, max_pages=2)
        all_records.extend(recs)
        if ok:
            any_ok = True

    return all_records, any_ok, ("Working" if any_ok else "Error (HydraFetch)")


def parse_entries(entries: list, source: dict, feed_url: str, catalog: dict) -> list:
    extracted = []
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for item in entries:
        text = item["text"]
        codes = sorted(set(MODEL_CODE_REGEX.findall(text)))
        if not codes:
            continue
        ops = extract_matches(text, OP_KEYWORDS, default=["FRP", "Factory Reset"])
        bit = extract_bits(text)
        os_ver = extract_os_versions(text)
        patch = extract_patch(text)
        modes = ", ".join(extract_matches(text, MODE_KEYWORDS)[:3])
        cpu = extract_cpu(text)
        tver = TOOL_VER_REGEX.search(text)
        tool_ver = "v" + tver.group(1) if tver else ""
        for code in codes:
            brand, marketing_name = lookup_device_info(code, text, catalog)
            extracted.append({
                "brand": brand,
                "model_name": marketing_name,
                "model_code": code.upper(),
                "bit": bit,
                "os_version": os_ver,
                "security_patch": patch,
                "mode": modes,
                "cpu": cpu,
                "tool": source["name"],
                "tool_id": source["id"],
                "tool_version": tool_ver,
                "operations": ops,
                "source_url": source.get("display_url") or source.get("url") or feed_url,
                "post_url": item.get("post_url") or feed_url,
                "updated_at": item.get("date") or today
            })
    return extracted


def scrape_feed(feed: dict, source: dict, catalog: dict):
    url = str(feed.get("url", "")).strip()
    ftype = feed.get("type", "changelog_html")
    if not url or ftype == "tg_or_url_needed":
        return [], False, "Pending"

    if ftype == "hydra_devices":
        return scrape_hydra_devices_hub(url, source, catalog)
    if ftype == "hydra_brand":
        recs, ok = scrape_hydra_brand_page(url, source, catalog, max_pages=3)
        return recs, ok, ("Working" if ok else "Error (HydraBrand)")

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        entries = []
        if ftype == "telegram_web":
            for msg in soup.select(".tgme_widget_message"):
                text_el = msg.select_one(".tgme_widget_message_text")
                if not text_el:
                    continue
                date_link = msg.select_one("a.tgme_widget_message_date")
                post_url = date_link["href"] if date_link and date_link.has_attr("href") else url
                time_el = date_link.select_one("time") if date_link else None
                post_date = time_el["datetime"][:10] if time_el and time_el.has_attr("datetime") else ""
                entries.append({
                    "text": text_el.get_text(" ", strip=True),
                    "post_url": post_url,
                    "date": post_date
                })
        elif ftype == "html_table":
            for row in soup.select("tr, li, .model-item, .device-card"):
                txt = row.get_text(" ", strip=True)
                if len(txt) > 4:
                    entries.append({"text": txt, "post_url": url, "date": ""})
        else:
            for post in soup.select("article, .post, .news-item, .update-item, p, li"):
                txt = post.get_text(" ", strip=True)
                if len(txt) > 10:
                    entries.append({"text": txt, "post_url": url, "date": ""})
        return parse_entries(entries, source, url, catalog), True, "Working"
    except Exception as exc:
        print(f"  [WARN] {source['name']} ({url}): {type(exc).__name__}")
        return [], False, "Error (" + type(exc).__name__ + ")"


def scrape_source(source: dict, catalog: dict):
    feeds = source.get("feeds")
    if not feeds:
        if source.get("url"):
            feeds = [{"type": source.get("type", "changelog_html"), "url": source.get("url", "")}]
        else:
            feeds = []
    all_recs = []
    any_ok = False
    last_err = "Pending"
    for feed in feeds:
        recs, ok, status = scrape_feed(feed, source, catalog)
        all_recs.extend(recs)
        if ok:
            any_ok = True
        else:
            last_err = status
    return all_recs, ("Working" if any_ok else last_err)


def merge_field(old_val: str, new_val: str) -> str:
    parts = []
    for raw in (old_val, new_val):
        for p in str(raw or "").split(","):
            p = p.strip()
            if p and p not in parts:
                parts.append(p)
    return ", ".join(parts[:4])


def backfill_marketing_names(existing_db: dict, catalog: dict) -> int:
    if not catalog:
        return 0
    upgraded = 0
    for code, entry in existing_db.items():
        if not isinstance(entry, dict):
            continue
        cur_name = str(entry.get("model_name") or "").strip()
        cur_brand = str(entry.get("brand") or "Other").strip()
        info = catalog.get(code.upper()) or catalog.get("CODENAME:" + code.upper())
        if not info:
            continue
        if (not cur_name or cur_name.upper() == code.upper()) and info["marketing_name"].upper() != code.upper():
            entry["model_name"] = info["marketing_name"]
            upgraded += 1
        if cur_brand == "Other" and info["brand"] != "Other":
            entry["brand"] = info["brand"]
    return upgraded


def merge_into_db(existing_db: dict, new_records: list):
    changelog = []
    tools_with_new_data = set()

    for rec in new_records:
        key = rec["model_code"].upper()
        is_new_model = key not in existing_db
        if is_new_model:
            existing_db[key] = {
                "brand": rec["brand"],
                "model_name": rec["model_name"],
                "model_code": key,
                "bit": rec["bit"],
                "os_version": rec["os_version"],
                "cpu": rec["cpu"],
                "mode": rec["mode"],
                "tools": {}
            }

        entry = existing_db[key]
        if (not entry.get("model_name") or entry["model_name"].upper() == key) and rec["model_name"].upper() != key:
            entry["model_name"] = rec["model_name"]
        if entry.get("brand") == "Other" and rec["brand"] != "Other":
            entry["brand"] = rec["brand"]

        entry["bit"] = merge_field(entry.get("bit", ""), rec["bit"])
        entry["os_version"] = merge_field(entry.get("os_version", ""), rec["os_version"])
        entry["cpu"] = merge_field(entry.get("cpu", ""), rec["cpu"])
        entry["mode"] = merge_field(entry.get("mode", ""), rec["mode"])

        tool_name = rec["tool"]
        prev = entry["tools"].get(tool_name, {})
        prev_ops = set(prev.get("operations", []))
        merged_ops = sorted(prev_ops.union(rec["operations"]))

        is_new_tool_link = tool_name not in entry["tools"]
        ops_changed = set(merged_ops) != prev_ops

        if is_new_model or is_new_tool_link or ops_changed:
            tools_with_new_data.add(tool_name)
            display_label = (
                f"{entry['model_name']} ({key})"
                if entry["model_name"].upper() != key
                else key
            )
            changelog.append({
                "date": rec["updated_at"],
                "type": "new_model" if is_new_model else "tool_update",
                "tool": tool_name,
                "model": display_label,
                "model_code": key,
                "bit": rec["bit"],
                "os_version": rec["os_version"],
                "mode": rec["mode"],
                "post_url": rec["post_url"],
                "ops": merged_ops
            })

        entry["tools"][tool_name] = {
            "operations": merged_ops,
            "bit": merge_field(prev.get("bit", ""), rec["bit"]),
            "os_version": merge_field(prev.get("os_version", ""), rec["os_version"]),
            "security_patch": rec["security_patch"] or prev.get("security_patch", ""),
            "mode": merge_field(prev.get("mode", ""), rec["mode"]),
            "tool_version": rec["tool_version"] or prev.get("tool_version", ""),
            "source_url": rec["source_url"],
            "post_url": rec["post_url"] or prev.get("post_url", ""),
            "updated_at": rec["updated_at"]
        }

    return existing_db, changelog, tools_with_new_data


def post_updates_to_channel(new_changes: list):
    bot_token = (os.environ.get("TG_BOT_TOKEN") or "").strip()
    channel_id = (os.environ.get("TG_CHANNEL_ID") or "").strip()
    web_url = (os.environ.get("WEB_APP_URL") or "").strip()
    if not bot_token or not channel_id or not new_changes:
        return
    lines = ["🔥 <b>NextGen GSM Auto-Update</b>\n"]
    for item in new_changes[:15]:
        ops = html.escape(", ".join(item.get("ops", [])))
        model_label = html.escape(str(item.get("model", "")))
        tool_label = html.escape(str(item.get("tool", "")))
        details = " | ".join(
            html.escape(x) for x in [item.get("bit"), item.get("os_version"), item.get("mode")] if x
        )
        extra = " [" + details + "]" if details else ""
        lines.append(f"• <code>{model_label}</code> — <b>{tool_label}</b> ({ops}){extra}")
    if len(new_changes) > 15:
        lines.append(f"\n<i>+ {len(new_changes) - 15} more models synced to the web database.</i>")
    payload = {"chat_id": channel_id, "text": "\n".join(lines), "parse_mode": "HTML"}
    if web_url:
        payload["reply_markup"] = {"inline_keyboard": [[{"text": "🔎 Search All Models", "url": web_url}]]}
    try:
        requests.post(
            "https://api.telegram.org/bot" + bot_token + "/sendMessage",
            json=payload,
            timeout=15
        )
    except Exception as exc:
        print("Telegram channel post failed:", exc)


def safe_load_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def main():
    os.makedirs("data", exist_ok=True)
    now_iso = datetime.now(timezone.utc).isoformat()

    catalog = load_play_device_catalog()

    sources_payload = safe_load_json("sources.json", {"sources": []})
    sources = sources_payload.get("sources", []) if isinstance(sources_payload, dict) else []

    db_path = "data/models.json"
    existing_payload = safe_load_json(db_path, {})
    existing_db = existing_payload.get("models", {}) if isinstance(existing_payload, dict) else {}
    prev_sources = {
        s["id"]: s for s in existing_payload.get("sources", [])
        if isinstance(s, dict) and "id" in s
    }

    upgraded_count = backfill_marketing_names(existing_db, catalog)
    if upgraded_count:
        print(f"[CATALOG] Backfilled marketing names for {upgraded_count} existing models.")

    all_records = []
    status_map = {}
    for src in sources:
        recs, status = scrape_source(src, catalog)
        all_records.extend(recs)
        status_map[src["id"]] = status
        print(f"[SYNC] {src['name']}: {status} ({len(recs)} records)")

    merged_db, new_changes, tools_with_new_data = merge_into_db(existing_db, all_records)

    tool_counts = {}
    for model in merged_db.values():
        for tname in model.get("tools", {}).keys():
            tool_counts[tname] = tool_counts.get(tname, 0) + 1

    source_statuses = []
    for src in sources:
        prev = prev_sources.get(src["id"], {})
        has_new = src["name"] in tools_with_new_data
        first_feed = (src.get("feeds") or [{}])[0].get("url", "")
        source_statuses.append({
            "id": src["id"],
            "name": src["name"],
            "status": status_map.get(src["id"], "Working"),
            "count": tool_counts.get(src["name"], 0),
            "source_label": src.get("source_label", "from its website"),
            "url": src.get("display_url") or src.get("url") or first_feed,
            "last_checked": now_iso,
            "last_new_data": now_iso if has_new else prev.get("last_new_data", "")
        })

    with open(db_path, "w", encoding="utf-8") as f:
        json.dump({
            "last_sync": now_iso,
            "refresh_interval_minutes": 30,
            "total_models": len(merged_db),
            "sources": source_statuses,
            "models": merged_db
        }, f, indent=2)

    cl_path = "data/changelog.json"
    old_cl = safe_load_json(cl_path, [])
    if not isinstance(old_cl, list):
        old_cl = []
    with open(cl_path, "w", encoding="utf-8") as f:
        json.dump((new_changes + old_cl)[:150], f, indent=2)

    post_updates_to_channel(new_changes)
    print(f"Sync complete: {len(merged_db)} total models, {len(new_changes)} new entries.")


if __name__ == "__main__":
    main()

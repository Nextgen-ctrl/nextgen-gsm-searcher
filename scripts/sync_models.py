import json
import os
import re
from datetime import datetime, timezone
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
}

# Standard GSM model codes across major brands
MODEL_CODE_REGEX = re.compile(
    r"\b("
    r"SM-[A-Z]\d{3,4}[A-Z0-9]{0,3}|"                                  # Samsung (SM-A155F, SM-S938U)
    r"CPH\d{4}|"                                                      # Oppo / OnePlus
    r"RMX\d{4}|"                                                      # Realme
    r"V\d{4}[A-Z]?|PD\d{4}[A-Z]?|"                                    # Vivo
    r"2[1-7]\d{4}[A-Z0-9]{2,4}|M\d{4}[A-Z]\d{1,2}[A-Z]|"              # Xiaomi / Redmi / Poco
    r"X\d{4}[A-Z]?|K[EFGJL]\d[a-z]?|BG\d[a-z]?|CK\d[a-z]?|CL\d[a-z]?|" # Infinix / Tecno
    r"XT\d{4}(?:-\d|[A-Z])?|"                                         # Motorola
    r"[A-Z]{3}-(?:LX|NX|AL|AN|TL|BD)[0-9A-Z]{1,2}"                    # Honor / Huawei (e.g. CLK-LX1)
    r")\b"
)

# BIT / Binary (supports numeric 1-16, ranges like 1-6, and Samsung hex BIT A-F / U1-U9)
BIT_REGEX = re.compile(
    r"\b(?:BIT|BINARY|BIN|REV)\s*[:\-]?\s*([1-9A-F](?:\s*[-/]\s*[1-9A-F])?|1[0-6])\b|\b(U[1-9A-F])\b",
    re.IGNORECASE
)

# Android version & OS skins (Android 11-17, HyperOS, OneUI, MIUI, ColorOS, FuntouchOS, MagicOS)
ANDROID_REGEX = re.compile(
    r"\bAndroid\s*(?:ver(?:sion)?\s*[:\-]?\s*)?(\d{2}(?:\s*[/\-&,]\s*\d{2})*)\b",
    re.IGNORECASE
)
OS_SKIN_REGEX = re.compile(
    r"\b((?:HyperOS|One\s?UI|MIUI|ColorOS|Funtouch\s?OS|MagicOS|HiOS|XOS)\s*\d*(?:\.\d+)?(?:\s*[/\-]\s*\d+)*)\b",
    re.IGNORECASE
)

# Security patch dates (e.g., 2026-02-01, 2025/12, January 2026 Patch)
PATCH_REGEX = re.compile(
    r"(?:patch|security(?:\s*patch)?)\s*[:\-]?\s*"
    r"(202[3-7][-/]\d{1,2}(?:[-/]\d{1,2})?|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s*202[3-7]?)",
    re.IGNORECASE
)

# Tool software version (e.g., v4.3.8, v2.9.9)
TOOL_VER_REGEX = re.compile(r"\bv\.?\s*(\d+\.\d+(?:\.\d+){0,2})\b", re.IGNORECASE)

# Specific chipset IDs (e.g., MT6878, SM6125, SDM680, T606)
CHIP_ID_REGEX = re.compile(r"\b(MT\d{4}[A-Z]?|SM\d{4}|SDM\d{3}|MSM\d{4}|T\d{3,4})\b", re.IGNORECASE)

OP_KEYWORDS = {
    "FRP": ["frp", "google account", "remove frp", "reset frp", "frp bypass"],
    "Factory Reset": ["factory reset", "format", "wipe data", "safe format"],
    "Flash": ["flash", "firmware", "write flash", "unbrick"],
    "MDM/KG": ["mdm", "kg lock", "knox", "payjoy", "it admin", "demo", "carrier relock"],
    "Bootloader": ["bootloader", "ubl", "unlock bl", "relock"],
    "IMEI": ["imei", "repair network", "patch cert", "nvram", "efs"],
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

def infer_brand(code: str, context: str) -> str:
    c = code.upper()
    if c.startswith("SM-"): return "Samsung"
    if c.startswith("CPH"): return "Oppo"
    if c.startswith("RMX"): return "Realme"
    if c.startswith(("V", "PD")): return "Vivo"
    if c.startswith("XT"): return "Motorola"
    if c.startswith("X"): return "Infinix"
    if re.match(r"^(K[EFGJL]|BG|CK|CL)\d", c): return "Tecno"
    if re.match(r"^(2[1-7]\d{4}|M\d{4})", c): return "Xiaomi"
    for b in ["Samsung", "Xiaomi", "Redmi", "Poco", "Vivo", "Oppo", "Realme", "Tecno", "Infinix", "Motorola", "Honor", "Huawei", "OnePlus", "Nokia", "Google", "Itel", "Lenovo", "Nothing"]:
        if b.lower() in context.lower():
            return "Xiaomi" if b in ("Redmi", "Poco") else b
    return "Other"

def extract_bits(text: str) -> str:
    found = []
    for m in BIT_REGEX.finditer(text):
        val = (m.group(1) or m.group(2) or "").upper().replace(" ", "")
        if val:
            label = val if val.startswith("U") else f"BIT {val}"
            if label not in found:
                found.append(label)
    return ", ".join(found[:4])

def extract_os_versions(text: str) -> str:
    found = []
    for m in ANDROID_REGEX.findall(text):
        val = f"Android {re.sub(r'\\s+', '', m)}"
        if val not in found:
            found.append(val)
    for skin in OS_SKIN_REGEX.findall(text):
        clean = " ".join(skin.split())
        if clean not in found:
            found.append(clean)
    return ", ".join(found[:3])

def extract_patch(text: str) -> str:
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
    combined = cpus + chips
    return ", ".join(combined[:2])

def parse_entries(entries: list, source: dict) -> list:
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
        tver_match = TOOL_VER_REGEX.search(text)
        tool_ver = f"v{tver_match.group(1)}" if tver_match else ""

        for code in codes:
            extracted.append({
                "brand": infer_brand(code, text),
                "model_name": code,
                "model_code": code,
                "bit": bit,
                "os_version": os_ver,
                "security_patch": patch,
                "mode": modes,
                "cpu": cpu,
                "tool": source["name"],
                "tool_id": source["id"],
                "tool_version": tool_ver,
                "operations": ops,
                "source_url": source["url"],
                "post_url": item.get("post_url") or source["url"],
                "updated_at": item.get("date") or today
            })
    return extracted

def scrape_source(source: dict):
    if not source.get("url") or source["type"] == "tg_or_url_needed":
        return [], {
            "id": source["id"], "name": source["name"], "url": source.get("url", ""),
            "status": "pending_url", "count": 0, "last_checked": datetime.now(timezone.utc).isoformat()
        }

    try:
        resp = requests.get(source["url"], headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        entries = []

        if source["type"] == "telegram_web":
            for msg in soup.select(".tgme_widget_message"):
                text_el = msg.select_one(".tgme_widget_message_text")
                if not text_el:
                    continue
                date_link = msg.select_one("a.tgme_widget_message_date")
                post_url = date_link["href"] if date_link and date_link.has_attr("href") else source["url"]
                time_el = date_link.select_one("time") if date_link else None
                post_date = time_el["datetime"][:10] if time_el and time_el.has_attr("datetime") else ""
                entries.append({
                    "text": text_el.get_text(" ", strip=True),
                    "post_url": post_url,
                    "date": post_date
                })
        elif source["type"] == "html_table":
            for row in soup.select("tr, li, .model-item, .device-card"):
                txt = row.get_text(" ", strip=True)
                if len(txt) > 4:
                    entries.append({"text": txt, "post_url": source["url"], "date": ""})
        else:
            for post in soup.select("article, .post, .news-item, .update-item, p, li"):
                txt = post.get_text(" ", strip=True)
                if len(txt) > 10:
                    entries.append({"text": txt, "post_url": source["url"], "date": ""})

        records = parse_entries(entries, source)
        return records, {
            "id": source["id"], "name": source["name"], "url": source["url"],
            "status": "online", "count": len(records), "last_checked": datetime.now(timezone.utc).isoformat()
        }
    except Exception as exc:
        return [], {
            "id": source["id"], "name": source["name"], "url": source["url"],
            "status": f"error: {type(exc).__name__}", "count": 0, "last_checked": datetime.now(timezone.utc).isoformat()
        }

def merge_field(old_val: str, new_val: str) -> str:
    parts = []
    for raw in (old_val, new_val):
        for p in str(raw or "").split(","):
            p = p.strip()
            if p and p not in parts:
                parts.append(p)
    return ", ".join(parts[:4])

def merge_into_db(existing_db: dict, new_records: list):
    changelog = []
    for rec in new_records:
        key = rec["model_code"].upper()
        if key not in existing_db:
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
            changelog.append({
                "date": rec["updated_at"],
                "type": "new_model",
                "tool": rec["tool"],
                "model": key,
                "bit": rec["bit"],
                "os_version": rec["os_version"],
                "mode": rec["mode"],
                "post_url": rec["post_url"],
                "ops": rec["operations"]
            })

        entry = existing_db[key]
        entry["bit"] = merge_field(entry.get("bit", ""), rec["bit"])
        entry["os_version"] = merge_field(entry.get("os_version", ""), rec["os_version"])
        entry["cpu"] = merge_field(entry.get("cpu", ""), rec["cpu"])
        entry["mode"] = merge_field(entry.get("mode", ""), rec["mode"])

        tool_name = rec["tool"]
        prev = entry["tools"].get(tool_name, {})
        prev_ops = set(prev.get("operations", []))
        merged_ops = sorted(prev_ops.union(rec["operations"]))

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

    return existing_db, changelog

def post_updates_to_channel(new_changes: list):
    bot_token = os.environ.get("TG_BOT_TOKEN")
    channel_id = os.environ.get("TG_CHANNEL_ID")
    web_url = os.environ.get("WEB_APP_URL", "")
    if not bot_token or not channel_id or not new_changes:
        return

    lines = ["🔥 <b>NextGen GSM Auto-Update</b>\n"]
    for item in new_changes[:15]:
        ops = ", ".join(item.get("ops", []))
        details = " | ".join(x for x in [item.get("bit"), item.get("os_version"), item.get("mode")] if x)
        extra = f" [{details}]" if details else ""
        lines.append(f"• <code>{item['model']}</code> — <b>{item['tool']}</b> ({ops}){extra}")

    if len(new_changes) > 15:
        lines.append(f"\n<i>+ {len(new_changes) - 15} more models synced to the web database.</i>")

    payload = {"chat_id": channel_id, "text": "\n".join(lines), "parse_mode": "HTML"}
    if web_url:
        payload["reply_markup"] = {"inline_keyboard": [[{"text": "🔎 Search All Models", "url": web_url}]]}

    try:
        requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json=payload, timeout=15)
    except Exception as exc:
        print(f"Telegram channel post failed: {exc}")

def main():
    os.makedirs("data", exist_ok=True)
    with open("sources.json", "r", encoding="utf-8") as f:
        sources = json.load(f)["sources"]

    db_path = "data/models.json"
    existing_db = json.load(open(db_path, "r", encoding="utf-8")).get("models", {}) if os.path.exists(db_path) else {}

    all_records, source_statuses = [], []
    for src in sources:
        recs, status = scrape_source(src)
        all_records.extend(recs)
        source_statuses.append(status)

    merged_db, new_changes = merge_into_db(existing_db, all_records)

    with open(db_path, "w", encoding="utf-8") as f:
        json.dump({
            "last_sync": datetime.now(timezone.utc).isoformat(),
            "total_models": len(merged_db),
            "sources": source_statuses,
            "models": merged_db
        }, f, indent=2)

    cl_path = "data/changelog.json"
    old_cl = json.load(open(cl_path, "r", encoding="utf-8")) if os.path.exists(cl_path) else []
    with open(cl_path, "w", encoding="utf-8") as f:
        json.dump((new_changes + old_cl)[:100], f, indent=2)

    post_updates_to_channel(new_changes)
    print(f"Sync complete: {len(merged_db)} total models, {len(new_changes)} new entries.")

if __name__ == "__main__":
    main()

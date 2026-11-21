import json
import os
import re
from datetime import datetime, timezone
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
}

MODEL_CODE_REGEX = re.compile(
    r"\b("
    r"SM-[A-Z]\d{3,4}[A-Z0-9]{0,3}|"
    r"CPH\d{4}|"
    r"RMX\d{4}|"
    r"V\d{4}[A-Z]?|PD\d{4}[A-Z]?|"
    r"2[1-6]\d{4}[A-Z0-9]{2,4}|"
    r"X\d{3,4}[A-Z]?|KF\d[a-z]?|KG\d[a-z]?|KJ\d[a-z]?|"
    r"XT\d{4}-\d|"
    r"M\d{4}[A-Z]\d{1,2}[A-Z]"
    r")\b"
)

BIT_REGEX = re.compile(r"\b(?:BIT|BINARY|U|S)\s*[:\-]?\s*([1-9]|1[0-6])\b", re.IGNORECASE)

OP_KEYWORDS = {
    "FRP": ["frp", "google account", "remove frp", "reset frp"],
    "Factory Reset": ["factory reset", "format", "wipe data", "safe format"],
    "Flash": ["flash", "firmware", "write flash", "unbrick"],
    "MDM/KG": ["mdm", "kg lock", "knox", "payjoy", "it admin", "demo"],
    "Bootloader": ["bootloader", "ubl", "unlock bl", "relock"],
    "IMEI": ["imei", "repair network", "patch cert", "nvram", "efs"],
    "Screen Lock": ["screen lock", "pin", "pattern", "passcode", "mi account", "heytap"]
}

def infer_brand(code: str, context: str) -> str:
    c = code.upper()
    if c.startswith("SM-"):
        return "Samsung"
    if c.startswith("CPH"):
        return "Oppo"
    if c.startswith("RMX"):
        return "Realme"
    if c.startswith(("V", "PD")):
        return "Vivo"
    if c.startswith("XT"):
        return "Motorola"
    if c.startswith("X"):
        return "Infinix"
    if c.startswith(("KF", "KG", "KJ")):
        return "Tecno"
    if re.match(r"^(2[1-6]\d{4}|M\d{4})", c):
        return "Xiaomi"
    for b in [
        "Samsung", "Xiaomi", "Redmi", "Poco", "Vivo", "Oppo", "Realme",
        "Tecno", "Infinix", "Motorola", "Honor", "Huawei", "OnePlus",
        "Nokia", "Google", "Itel", "Lenovo"
    ]:
        if b.lower() in context.lower():
            return "Xiaomi" if b in ("Redmi", "Poco") else b
    return "Other"

def extract_operations(text: str) -> list:
    lower = text.lower()
    found = [op for op, kws in OP_KEYWORDS.items() if any(kw in lower for kw in kws)]
    return found or ["FRP", "Factory Reset"]

def parse_text_blocks(blocks: list, source: dict) -> list:
    extracted = []
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for text in blocks:
        codes = sorted(set(MODEL_CODE_REGEX.findall(text)))
        if not codes:
            continue
        ops = extract_operations(text)
        bits = sorted(set(BIT_REGEX.findall(text)))
        for code in codes:
            extracted.append({
                "brand": infer_brand(code, text),
                "model_name": code,
                "model_code": code,
                "bit": f"BIT {', '.join(bits)}" if bits else "",
                "tool": source["name"],
                "tool_id": source["id"],
                "operations": ops,
                "source_url": source["url"],
                "updated_at": today
            })
    return extracted

def scrape_source(source: dict):
    if not source.get("url") or source["type"] == "tg_or_url_needed":
        return [], {
            "id": source["id"],
            "name": source["name"],
            "url": source.get("url", ""),
            "status": "pending_url",
            "count": 0,
            "last_checked": datetime.now(timezone.utc).isoformat()
        }

    try:
        resp = requests.get(source["url"], headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        blocks = []
        if source["type"] == "telegram_web":
            for msg in soup.select(".tgme_widget_message_text"):
                blocks.append(msg.get_text(" ", strip=True))
        elif source["type"] == "html_table":
            for row in soup.select("tr, li, .model-item, .device-card"):
                txt = row.get_text(" ", strip=True)
                if len(txt) > 4:
                    blocks.append(txt)
        else:
            for post in soup.select("article, .post, .news-item, .update-item, p, li"):
                txt = post.get_text(" ", strip=True)
                if len(txt) > 10:
                    blocks.append(txt)

        records = parse_text_blocks(blocks, source)
        return records, {
            "id": source["id"],
            "name": source["name"],
            "url": source["url"],
            "status": "online",
            "count": len(records),
            "last_checked": datetime.now(timezone.utc).isoformat()
        }
    except Exception as exc:
        return [], {
            "id": source["id"],
            "name": source["name"],
            "url": source["url"],
            "status": f"error: {type(exc).__name__}",
            "count": 0,
            "last_checked": datetime.now(timezone.utc).isoformat()
        }

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
                "tools": {}
            }
            changelog.append({
                "date": rec["updated_at"],
                "type": "new_model",
                "tool": rec["tool"],
                "model": key,
                "ops": rec["operations"]
            })

        entry = existing_db[key]
        if rec["bit"] and not entry.get("bit"):
            entry["bit"] = rec["bit"]

        tool_name = rec["tool"]
        prev_ops = set(entry["tools"].get(tool_name, {}).get("operations", []))
        merged_ops = sorted(prev_ops.union(rec["operations"]))
        if set(merged_ops) != prev_ops:
            entry["tools"][tool_name] = {
                "operations": merged_ops,
                "source_url": rec["source_url"],
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
        lines.append(f"• <code>{item['model']}</code> — <b>{item['tool']}</b> ({ops})")

    if len(new_changes) > 15:
        lines.append(f"\n<i>+ {len(new_changes) - 15} more models synced to the web database.</i>")

    payload = {
        "chat_id": channel_id,
        "text": "\n".join(lines),
        "parse_mode": "HTML",
    }
    if web_url:
        payload["reply_markup"] = {
            "inline_keyboard": [[{"text": "🔎 Search All Models", "url": web_url}]]
        }

    try:
        requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json=payload,
            timeout=15,
        )
    except Exception as exc:
        print(f"Telegram channel post failed: {exc}")

def main():
    os.makedirs("data", exist_ok=True)
    with open("sources.json", "r", encoding="utf-8") as f:
        sources = json.load(f)["sources"]

    db_path = "data/models.json"
    existing_db = {}
    if os.path.exists(db_path):
        with open(db_path, "r", encoding="utf-8") as f:
            existing_db = json.load(f).get("models", {})

    all_records = []
    source_statuses = []
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
    old_cl = []
    if os.path.exists(cl_path):
        with open(cl_path, "r", encoding="utf-8") as f:
            old_cl = json.load(f)

    with open(cl_path, "w", encoding="utf-8") as f:
        json.dump((new_changes + old_cl)[:100], f, indent=2)

    post_updates_to_channel(new_changes)
    print(f"Sync complete: {len(merged_db)} total models, {len(new_changes)} new entries.")

if __name__ == "__main__":
    main()

import os, json, re
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import anthropic
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import httpx

app = FastAPI()

# ── 環境變數 ──────────────────────────────────────────────────
ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
GOOGLE_SHEET_ID    = os.environ["GOOGLE_SHEET_ID"]
TELEGRAM_TOKEN     = os.environ["TELEGRAM_TOKEN"]

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ── 使用者狀態（記憶體） ───────────────────────────────────────
user_lang  = {}   # uid -> "zh" | "th" | "en"
user_state = {}   # uid -> dict (用於多步驟流程，如組合成品)

# ── 多語言文字 ────────────────────────────────────────────────
T = {
    "welcome": {
        "zh": "🏢 SUPER INTER GROUP (1997)\n歡迎使用 ERP 系統！😊\n\n請選擇語言：\n1️⃣ 繁體中文\n2️⃣ ภาษาไทย\n3️⃣ English",
        "th": "🏢 SUPER INTER GROUP (1997)\nยินดีต้อนรับสู่ระบบ ERP! 😊",
        "en": "🏢 SUPER INTER GROUP (1997)\nWelcome to ERP System! 😊",
    },
    "lang_set": {
        "zh": "✅ 語言已設定：繁體中文",
        "th": "✅ ตั้งค่าภาษาไทยแล้ว",
        "en": "✅ Language set to English",
    },
    "help": {
        "zh": (
            "📋 指令說明\n"
            "══════════════════\n"
            "📦 庫存管理\n"
            "  • 查 [零件名稱] — 查詢庫存\n"
            "  • 進 [零件名稱] [數量] — 進貨\n"
            "  • 出 [零件名稱] [數量] — 出貨\n"
            "  • 缺貨 — 缺貨/偏低清單\n"
            "  • 總覽 — 庫存總覽\n\n"
            "🔧 成品組合\n"
            "  • 組合 — 開始組合成品\n"
            "  • BOM — 查看成品清單\n\n"
            "📊 報表\n"
            "  • 報表 — 本月進出貨統計\n"
            "  • 銷售 — 本月銷售記錄\n\n"
            "⚙️ 其他\n"
            "  • 切換語言 — 更換語言\n"
            "  • myid — 查看我的 ID\n"
            "  • 幫助 — 顯示此說明"
        ),
        "th": (
            "📋 คำสั่งที่ใช้ได้\n"
            "══════════════════\n"
            "📦 จัดการสต็อก\n"
            "  • ค้นหา [ชื่อชิ้นส่วน] — ตรวจสอบสต็อก\n"
            "  • รับเข้า [ชื่อ] [จำนวน] — รับสินค้าเข้า\n"
            "  • จ่ายออก [ชื่อ] [จำนวน] — จ่ายสินค้าออก\n"
            "  • ขาดสต็อก — รายการขาด/ใกล้หมด\n"
            "  • ภาพรวม — ภาพรวมสต็อก\n\n"
            "🔧 ประกอบสินค้า\n"
            "  • ประกอบ — เริ่มประกอบสินค้า\n"
            "  • BOM — ดูรายการสินค้าสำเร็จ\n\n"
            "📊 รายงาน\n"
            "  • รายงาน — สรุปเดือนนี้\n\n"
            "⚙️ อื่นๆ\n"
            "  • เปลี่ยนภาษา — เปลี่ยนภาษา\n"
            "  • myid — ดู ID ของฉัน\n"
            "  • ช่วยเหลือ — แสดงคำสั่ง"
        ),
        "en": (
            "📋 Available Commands\n"
            "══════════════════\n"
            "📦 Inventory\n"
            "  • check [part name] — Check stock\n"
            "  • in [part name] [qty] — Receive stock\n"
            "  • out [part name] [qty] — Issue stock\n"
            "  • shortage — Low/out of stock list\n"
            "  • overview — Inventory summary\n\n"
            "🔧 Assembly\n"
            "  • assemble — Start product assembly\n"
            "  • BOM — View product list\n\n"
            "📊 Reports\n"
            "  • report — Monthly summary\n"
            "  • sales — Monthly sales\n\n"
            "⚙️ Other\n"
            "  • language — Change language\n"
            "  • myid — View my ID\n"
            "  • help — Show this guide"
        ),
    },
    "not_found": {
        "zh": "😅 找不到「{item}」，請確認零件名稱",
        "th": "😅 ไม่พบ「{item}」กรุณาตรวจสอบชื่อชิ้นส่วน",
        "en": "😅 Cannot find「{item}」, please check the part name",
    },
    "stock_status": {
        "zh": "🔍 {name}\n{'─'*18}\n📊 庫存：{stock} 個\n🛡️ 安全庫存：{safe} 個\n💡 狀態：{status}",
        "th": "🔍 {name}\n{'─'*18}\n📊 สต็อก：{stock} ชิ้น\n🛡️ สต็อกปลอดภัย：{safe} ชิ้น\n💡 สถานะ：{status}",
        "en": "🔍 {name}\n{'─'*18}\n📊 Stock: {stock} pcs\n🛡️ Safe stock: {safe} pcs\n💡 Status: {status}",
    },
    "in_ok": {
        "zh": "✅ 進貨成功\n{'─'*18}\n📦 {name}\n➕ +{qty} 個\n📊 {before} → {after} 個\n💡 {status}\n🕐 {now}",
        "th": "✅ รับเข้าสำเร็จ\n{'─'*18}\n📦 {name}\n➕ +{qty} ชิ้น\n📊 {before} → {after} ชิ้น\n💡 {status}\n🕐 {now}",
        "en": "✅ Stock received\n{'─'*18}\n📦 {name}\n➕ +{qty} pcs\n📊 {before} → {after} pcs\n💡 {status}\n🕐 {now}",
    },
    "out_ok": {
        "zh": "📤 出貨成功\n{'─'*18}\n📦 {name}\n➖ -{qty} 個\n📊 {before} → {after} 個\n💡 {status}\n🕐 {now}",
        "th": "📤 จ่ายออกสำเร็จ\n{'─'*18}\n📦 {name}\n➖ -{qty} ชิ้น\n📊 {before} → {after} ชิ้น\n💡 {status}\n🕐 {now}",
        "en": "📤 Stock issued\n{'─'*18}\n📦 {name}\n➖ -{qty} pcs\n📊 {before} → {after} pcs\n💡 {status}\n🕐 {now}",
    },
    "insufficient": {
        "zh": "⚠️ 庫存不足！\n「{name}」只剩 {stock} 個，無法出貨 {qty} 個",
        "th": "⚠️ สต็อกไม่เพียงพอ!\n「{name}」เหลือ {stock} ชิ้น ไม่สามารถจ่าย {qty} ชิ้น",
        "en": "⚠️ Insufficient stock!\n「{name}」only has {stock} pcs, cannot issue {qty} pcs",
    },
    "inv_status_label": {
        "out":  {"zh": "🔴 缺貨",      "th": "🔴 หมดสต็อก",    "en": "🔴 Out of Stock"},
        "low":  {"zh": "🟡 偏低",      "th": "🟡 ใกล้หมด",     "en": "🟡 Low Stock"},
        "ok":   {"zh": "🟢 充足",      "th": "🟢 เพียงพอ",     "en": "🟢 In Stock"},
    },
    "assemble_start": {
        "zh": "🔧 開始組合成品\n請輸入成品名稱（例如：捲廉門套件300kg）\n或輸入「取消」放棄",
        "th": "🔧 เริ่มประกอบสินค้า\nกรุณาพิมพ์ชื่อสินค้าสำเร็จ\nหรือพิมพ์「ยกเลิก」เพื่อยกเลิก",
        "en": "🔧 Start product assembly\nPlease enter the product name\nor type「cancel」to abort",
    },
    "assemble_qty": {
        "zh": "📦 組合成品：{name}\n要組合幾套？（輸入數字）",
        "th": "📦 ประกอบ：{name}\nจะประกอบกี่ชุด？（กรุณาพิมพ์จำนวน）",
        "en": "📦 Assembling: {name}\nHow many units? (enter number)",
    },
    "assemble_confirm": {
        "zh": "📋 確認組合清單\n{'─'*18}\n成品：{name} × {qty} 套\n\n所需零件：\n{parts}\n\n輸入「確認」執行 / 「取消」放棄",
        "th": "📋 ยืนยันรายการประกอบ\n{'─'*18}\nสินค้า：{name} × {qty} ชุด\n\nชิ้นส่วนที่ต้องการ：\n{parts}\n\nพิมพ์「ยืนยัน」เพื่อดำเนินการ / 「ยกเลิก」เพื่อยกเลิก",
        "en": "📋 Assembly confirmation\n{'─'*18}\nProduct: {name} × {qty} units\n\nParts required:\n{parts}\n\nType「confirm」to proceed / 「cancel」to abort",
    },
    "assemble_ok": {
        "zh": "✅ 組合完成！\n{'─'*18}\n🏭 {name} × {qty} 套\n已扣除所有零件庫存\n🕐 {now}",
        "th": "✅ ประกอบสำเร็จ！\n{'─'*18}\n🏭 {name} × {qty} ชุด\nหักสต็อกชิ้นส่วนทั้งหมดแล้ว\n🕐 {now}",
        "en": "✅ Assembly complete!\n{'─'*18}\n🏭 {name} × {qty} units\nAll parts deducted from stock\n🕐 {now}",
    },
    "assemble_fail": {
        "zh": "❌ 組合失敗！零件庫存不足：\n{errors}",
        "th": "❌ ประกอบล้มเหลว! ชิ้นส่วนไม่เพียงพอ:\n{errors}",
        "en": "❌ Assembly failed! Insufficient parts:\n{errors}",
    },
    "cancel": {
        "zh": "❌ 已取消",
        "th": "❌ ยกเลิกแล้ว",
        "en": "❌ Cancelled",
    },
    "error": {
        "zh": "⚠️ 發生錯誤：{err}",
        "th": "⚠️ เกิดข้อผิดพลาด：{err}",
        "en": "⚠️ Error: {err}",
    },
}

def t(key, lang, **kwargs):
    """取得多語言文字並填入變數"""
    tmpl = T.get(key, {}).get(lang, T.get(key, {}).get("zh", ""))
    return tmpl.format(**kwargs) if kwargs else tmpl

def inv_status_label(stock, safe, lang):
    if stock == 0:
        return T["inv_status_label"]["out"][lang]
    if stock < safe:
        return T["inv_status_label"]["low"][lang]
    return T["inv_status_label"]["ok"][lang]


# ── Google Sheets ─────────────────────────────────────────────
def get_sheet():
    creds_json = json.loads(os.environ["GOOGLE_CREDENTIALS_JSON"])
    creds = Credentials.from_service_account_info(
        creds_json, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    gc = gspread.authorize(creds)
    return gc.open_by_key(GOOGLE_SHEET_ID)

def get_ws(name):
    return get_sheet().worksheet(name)

def get_inventory():
    return get_ws("零件庫存").get_all_records()

def find_item(name):
    """模糊搜尋零件，回傳 (row_index, record)"""
    records = get_inventory()
    name_c = name.strip().lower().replace(" ", "")
    search_cols = ["零件名稱_300kg", "零件名稱_550kg", "零件名稱_700kg", "泰文名稱", "英文名稱"]
    # 完全匹配
    for i, r in enumerate(records):
        for col in search_cols:
            if name_c == str(r.get(col, "")).lower().replace(" ", ""):
                return i + 2, r
    # 模糊匹配
    for i, r in enumerate(records):
        for col in search_cols:
            val = str(r.get(col, "")).lower().replace(" ", "")
            if val and (name_c in val or (len(name_c) >= 2 and name_c[:2] in val)):
                return i + 2, r
    return None, None

def update_stock(row, stock):
    get_ws("零件庫存").update_cell(row, 8, stock)

def log_tx(name, action, qty, before, after, uid, lang, platform="Telegram"):
    sh = get_sheet()
    try:
        ws = sh.worksheet("進出貨記錄")
    except Exception:
        ws = sh.add_worksheet("進出貨記錄", 5000, 10)
        ws.append_row(["日期", "月份", "類型", "品項", "數量", "更新前", "更新後", "操作者", "語言", "平台"])
    now = datetime.now()
    ws.append_row([now.strftime("%Y-%m-%d"), now.strftime("%Y-%m"),
                   action, name, qty, before, after, uid, lang, platform])

def log_assembly(product_name, qty, parts_used, uid, lang):
    sh = get_sheet()
    try:
        ws = sh.worksheet("組合記錄")
    except Exception:
        ws = sh.add_worksheet("組合記錄", 5000, 8)
        ws.append_row(["日期", "月份", "成品名稱", "組合數量", "使用零件", "操作者", "語言", "平台"])
    now = datetime.now()
    parts_str = "; ".join([f"{p['name']}×{p['qty']}" for p in parts_used])
    ws.append_row([now.strftime("%Y-%m-%d"), now.strftime("%Y-%m"),
                   product_name, qty, parts_str, uid, lang, "Telegram"])

def get_bom_list():
    """取得成品BOM表"""
    try:
        records = get_ws("成品BOM").get_all_records()
        return records
    except Exception:
        return []

def get_bom_by_name(product_name):
    """根據成品名稱取得BOM"""
    records = get_bom_list()
    name_c = product_name.strip().lower().replace(" ", "")
    result = []
    for r in records:
        pname = str(r.get("成品名稱", "")).lower().replace(" ", "")
        if name_c in pname or pname in name_c:
            result.append(r)
    return result

def get_monthly_report(lang):
    """取得本月進出貨報表"""
    try:
        records = get_ws("進出貨記錄").get_all_records()
    except Exception:
        return {"zh": "📊 尚無記錄", "th": "📊 ไม่มีข้อมูล", "en": "📊 No records yet"}.get(lang)

    month = datetime.now().strftime("%Y-%m")
    in_count = 0
    out_count = 0
    in_items = {}
    out_items = {}

    for r in records:
        if str(r.get("月份", "")) != month:
            continue
        action = str(r.get("類型", ""))
        item = str(r.get("品項", ""))
        qty = int(r.get("數量", 0) or 0)
        if action in ("進貨", "in", "รับเข้า"):
            in_count += qty
            in_items[item] = in_items.get(item, 0) + qty
        elif action in ("出貨", "out", "จ่ายออก"):
            out_count += qty
            out_items[item] = out_items.get(item, 0) + qty

    div = "─" * 18
    now_str = datetime.now().strftime("%Y/%m")

    if lang == "th":
        report = f"📊 รายงานประจำเดือน {now_str}\n{div}\n"
        report += f"📥 รับเข้าทั้งหมด：{in_count} ชิ้น\n"
        for k, v in list(in_items.items())[:5]:
            report += f"  • {k}：{v}\n"
        report += f"\n📤 จ่ายออกทั้งหมด：{out_count} ชิ้น\n"
        for k, v in list(out_items.items())[:5]:
            report += f"  • {k}：{v}\n"
    elif lang == "en":
        report = f"📊 Monthly Report {now_str}\n{div}\n"
        report += f"📥 Total received：{in_count} pcs\n"
        for k, v in list(in_items.items())[:5]:
            report += f"  • {k}：{v}\n"
        report += f"\n📤 Total issued：{out_count} pcs\n"
        for k, v in list(out_items.items())[:5]:
            report += f"  • {k}：{v}\n"
    else:
        report = f"📊 本月報表 {now_str}\n{div}\n"
        report += f"📥 進貨合計：{in_count} 個\n"
        for k, v in list(in_items.items())[:5]:
            report += f"  • {k}：{v}\n"
        report += f"\n📤 出貨合計：{out_count} 個\n"
        for k, v in list(out_items.items())[:5]:
            report += f"  • {k}：{v}\n"

    return report.strip()


# ── AI 解析指令 ───────────────────────────────────────────────
def parse_cmd(text, lang):
    lang_hint = {"zh": "繁體中文", "th": "ภาษาไทย", "en": "English"}.get(lang, "繁體中文")
    prompt = f"""Parse this inventory ERP command to JSON only. User speaks {lang_hint}.
Message: {text}

Return ONLY one JSON (no markdown):
{{"action":"in","item":"name","qty":N}}
{{"action":"out","item":"name","qty":N}}
{{"action":"query","item":"name"}}
{{"action":"shortage"}}
{{"action":"summary"}}
{{"action":"report"}}
{{"action":"bom"}}
{{"action":"assemble"}}
{{"action":"help"}}
{{"action":"change_lang"}}
{{"action":"unknown"}}"""

    resp = claude.messages.create(
        model="claude-sonnet-4-20250514", max_tokens=100,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = re.sub(r"```json?\n?|```", "", resp.content[0].text).strip()
    return json.loads(raw)


# ── 主要指令處理 ──────────────────────────────────────────────
def process_cmd(uid, text, lang):
    now = datetime.now().strftime("%m/%d %H:%M")
    div = "─" * 18

    # ── 多步驟狀態：組合成品流程 ──
    state = user_state.get(uid, {})

    # 取消指令
    cancel_words = {"取消", "cancel", "ยกเลิก"}
    if text.strip().lower() in cancel_words and state:
        user_state.pop(uid, None)
        return t("cancel", lang)

    # 組合流程 step1：等待成品名稱
    if state.get("step") == "assemble_name":
        product_name = text.strip()
        user_state[uid] = {"step": "assemble_qty", "product": product_name}
        return t("assemble_qty", lang, name=product_name)

    # 組合流程 step2：等待數量
    if state.get("step") == "assemble_qty":
        try:
            qty = int(text.strip())
        except ValueError:
            return {"zh": "⚠️ 請輸入數字", "th": "⚠️ กรุณาพิมพ์ตัวเลข", "en": "⚠️ Please enter a number"}.get(lang)

        product_name = state["product"]
        bom = get_bom_by_name(product_name)

        if not bom:
            # 無預設BOM，讓使用者自由輸入零件
            user_state[uid] = {
                "step": "assemble_free",
                "product": product_name,
                "qty": qty,
                "parts": []
            }
            if lang == "th":
                return f"📝 ไม่พบ BOM สำหรับ「{product_name}」\nกรุณาพิมพ์ชิ้นส่วน เช่น：\nสปริง 10\nแบริ่ง 4\nพิมพ์「เสร็จแล้ว」เมื่อเพิ่มครบ"
            elif lang == "en":
                return f"📝 No BOM found for「{product_name}」\nPlease enter parts, e.g.:\nSpring 10\nBearing 4\nType「done」when finished"
            else:
                return f"📝 找不到「{product_name}」的BOM\n請逐一輸入零件，例如：\n彈簧 10\n軸承 4\n輸入「完成」結束"

        # 有BOM，顯示確認清單
        parts_lines = []
        for row in bom:
            part = row.get("零件名稱", "")
            need = int(row.get("數量", 1) or 1) * qty
            parts_lines.append(f"  • {part} × {need} 個")
        parts_str = "\n".join(parts_lines)

        user_state[uid] = {
            "step": "assemble_confirm",
            "product": product_name,
            "qty": qty,
            "bom": bom
        }
        return t("assemble_confirm", lang, name=product_name, qty=qty, parts=parts_str)

    # 組合流程 step2b：自由輸入零件
    if state.get("step") == "assemble_free":
        done_words = {"完成", "done", "เสร็จแล้ว"}
        if text.strip().lower() in done_words:
            parts = state.get("parts", [])
            if not parts:
                return {"zh": "⚠️ 尚未加入任何零件", "th": "⚠️ ยังไม่ได้เพิ่มชิ้นส่วน", "en": "⚠️ No parts added yet"}.get(lang)
            product_name = state["product"]
            qty = state["qty"]
            parts_lines = [f"  • {p['name']} × {p['qty']} 個" for p in parts]
            parts_str = "\n".join(parts_lines)
            user_state[uid] = {
                "step": "assemble_confirm",
                "product": product_name,
                "qty": qty,
                "free_parts": parts
            }
            return t("assemble_confirm", lang, name=product_name, qty=qty, parts=parts_str)
        else:
            # 解析 "零件名稱 數量"
            tokens = text.strip().rsplit(None, 1)
            if len(tokens) == 2:
                try:
                    part_name = tokens[0]
                    part_qty = int(tokens[1])
                    state["parts"].append({"name": part_name, "qty": part_qty})
                    user_state[uid] = state
                    added = {"zh": f"✅ 已加入：{part_name} × {part_qty}",
                             "th": f"✅ เพิ่มแล้ว：{part_name} × {part_qty}",
                             "en": f"✅ Added: {part_name} × {part_qty}"}.get(lang)
                    more = {"zh": "繼續輸入零件，或輸入「完成」",
                            "th": "พิมพ์ชิ้นส่วนต่อไป หรือ「เสร็จแล้ว」",
                            "en": "Add more parts or type「done」"}.get(lang)
                    return f"{added}\n{more}"
                except ValueError:
                    pass
            return {"zh": "⚠️ 格式：零件名稱 數量，例如：彈簧 10",
                    "th": "⚠️ รูปแบบ：ชื่อชิ้นส่วน จำนวน เช่น：สปริง 10",
                    "en": "⚠️ Format: part name qty, e.g.: Spring 10"}.get(lang)

    # 組合流程 step3：確認執行
    if state.get("step") == "assemble_confirm":
        confirm_words = {"確認", "confirm", "ยืนยัน"}
        if text.strip().lower() not in confirm_words:
            user_state.pop(uid, None)
            return t("cancel", lang)

        product_name = state["product"]
        qty = state["qty"]
        bom = state.get("bom")
        free_parts = state.get("free_parts")

        errors = []
        parts_to_deduct = []

        if bom:
            for row in bom:
                part_name = row.get("零件名稱", "")
                need = int(row.get("數量", 1) or 1) * qty
                row_idx, rec = find_item(part_name)
                if not rec:
                    errors.append(f"找不到零件：{part_name}")
                    continue
                stock = int(rec.get("現存庫存", 0) or 0)
                if stock < need:
                    errors.append(f"{part_name}：需要{need}，只有{stock}")
                else:
                    parts_to_deduct.append({"row": row_idx, "rec": rec, "name": part_name, "need": need})
        elif free_parts:
            for p in free_parts:
                need = p["qty"] * qty
                row_idx, rec = find_item(p["name"])
                if not rec:
                    errors.append(f"找不到零件：{p['name']}")
                    continue
                stock = int(rec.get("現存庫存", 0) or 0)
                if stock < need:
                    errors.append(f"{p['name']}：需要{need}，只有{stock}")
                else:
                    parts_to_deduct.append({"row": row_idx, "rec": rec, "name": p["name"], "need": need})

        if errors:
            user_state.pop(uid, None)
            err_str = "\n".join(f"  • {e}" for e in errors)
            return t("assemble_fail", lang, errors=err_str)

        # 全部庫存充足，執行扣庫存
        parts_used = []
        for p in parts_to_deduct:
            before = int(p["rec"].get("現存庫存", 0) or 0)
            after = before - p["need"]
            update_stock(p["row"], after)
            log_tx(p["name"], "組合扣料", p["need"], before, after, uid, lang)
            parts_used.append({"name": p["name"], "qty": p["need"]})

        log_assembly(product_name, qty, parts_used, uid, lang)
        user_state.pop(uid, None)
        return t("assemble_ok", lang, name=product_name, qty=qty, now=now)

    # ── 一般指令解析 ──
    try:
        cmd = parse_cmd(text, lang)
    except Exception:
        return t("help", lang)

    action = cmd.get("action", "unknown")

    try:
        # 查庫存
        if action == "query":
            row, rec = find_item(cmd.get("item", ""))
            if not rec:
                return t("not_found", lang, item=cmd.get("item", ""))
            name = rec.get("零件名稱_300kg", "") or rec.get("零件名稱_550kg", "")
            stock = int(rec.get("現存庫存", 0) or 0)
            safe = int(rec.get("安全庫存", 20) or 20)
            status = inv_status_label(stock, safe, lang)
            return f"🔍 {name}\n{div}\n📊 {stock} {'個' if lang=='zh' else 'ชิ้น' if lang=='th' else 'pcs'}\n🛡️ {safe} {'個' if lang=='zh' else 'ชิ้น' if lang=='th' else 'pcs'}\n💡 {status}"

        # 進貨
        elif action == "in":
            row, rec = find_item(cmd.get("item", ""))
            if not rec:
                return t("not_found", lang, item=cmd.get("item", ""))
            name = rec.get("零件名稱_300kg", "") or rec.get("零件名稱_550kg", "")
            before = int(rec.get("現存庫存", 0) or 0)
            qty = int(cmd.get("qty", 1))
            after = before + qty
            update_stock(row, after)
            log_tx(name, "進貨", qty, before, after, uid, lang)
            safe = int(rec.get("安全庫存", 20) or 20)
            status = inv_status_label(after, safe, lang)
            unit = "個" if lang == "zh" else "ชิ้น" if lang == "th" else "pcs"
            return f"✅ {'進貨成功' if lang=='zh' else 'รับเข้าสำเร็จ' if lang=='th' else 'Stock received'}\n{div}\n📦 {name}\n➕ +{qty} {unit}\n📊 {before} → {after} {unit}\n💡 {status}\n🕐 {now}"

        # 出貨
        elif action == "out":
            row, rec = find_item(cmd.get("item", ""))
            if not rec:
                return t("not_found", lang, item=cmd.get("item", ""))
            name = rec.get("零件名稱_300kg", "") or rec.get("零件名稱_550kg", "")
            before = int(rec.get("現存庫存", 0) or 0)
            qty = int(cmd.get("qty", 1))
            safe = int(rec.get("安全庫存", 20) or 20)
            if before < qty:
                return t("insufficient", lang, name=name, stock=before, qty=qty)
            after = before - qty
            update_stock(row, after)
            log_tx(name, "出貨", qty, before, after, uid, lang)
            status = inv_status_label(after, safe, lang)
            unit = "個" if lang == "zh" else "ชิ้น" if lang == "th" else "pcs"
            return f"📤 {'出貨成功' if lang=='zh' else 'จ่ายออกสำเร็จ' if lang=='th' else 'Stock issued'}\n{div}\n📦 {name}\n➖ -{qty} {unit}\n📊 {before} → {after} {unit}\n💡 {status}\n🕐 {now}"

        # 缺貨報告
        elif action == "shortage":
            records = get_inventory()
            out_list, low_list = [], []
            for r in records:
                n = r.get("零件名稱_300kg", "") or r.get("零件名稱_550kg", "")
                if not n:
                    continue
                s = int(r.get("現存庫存", 0) or 0)
                sf = int(r.get("安全庫存", 20) or 20)
                if s == 0:
                    out_list.append(n)
                elif s < sf:
                    low_list.append(f"{n}({s}/{sf})")
            date_str = datetime.now().strftime("%m/%d %H:%M")
            if lang == "th":
                result = f"🚨 รายงานสต็อก {date_str}\n{div}"
                result += f"\n🔴 หมดสต็อก ({len(out_list)} รายการ)\n" + "\n".join(f"  • {x}" for x in out_list)
                result += f"\n\n🟡 ใกล้หมด ({len(low_list)} รายการ)\n" + "\n".join(f"  • {x}" for x in low_list)
            elif lang == "en":
                result = f"🚨 Stock Alert {date_str}\n{div}"
                result += f"\n🔴 Out of Stock ({len(out_list)} items)\n" + "\n".join(f"  • {x}" for x in out_list)
                result += f"\n\n🟡 Low Stock ({len(low_list)} items)\n" + "\n".join(f"  • {x}" for x in low_list)
            else:
                result = f"🚨 缺貨報告 {date_str}\n{div}"
                result += f"\n🔴 缺貨 ({len(out_list)} 項)\n" + "\n".join(f"  • {x}" for x in out_list)
                result += f"\n\n🟡 偏低 ({len(low_list)} 項)\n" + "\n".join(f"  • {x}" for x in low_list)
            return result

        # 總覽
        elif action == "summary":
            records = get_inventory()
            total = ok_ = low_ = out_ = 0
            for r in records:
                n = r.get("零件名稱_300kg", "") or r.get("零件名稱_550kg", "")
                if not n:
                    continue
                total += 1
                s = int(r.get("現存庫存", 0) or 0)
                sf = int(r.get("安全庫存", 20) or 20)
                if s == 0:
                    out_ += 1
                elif s < sf:
                    low_ += 1
                else:
                    ok_ += 1
            if lang == "th":
                return f"📊 ภาพรวมสต็อก\n{div}\n🔴 หมด：{out_} รายการ\n🟡 ใกล้หมด：{low_} รายการ\n🟢 เพียงพอ：{ok_} รายการ\n📦 รวม：{total} รายการ"
            elif lang == "en":
                return f"📊 Inventory Overview\n{div}\n🔴 Out of stock：{out_} items\n🟡 Low stock：{low_} items\n🟢 In stock：{ok_} items\n📦 Total：{total} items"
            else:
                return f"📊 庫存總覽\n{div}\n🔴 缺貨：{out_} 種\n🟡 偏低：{low_} 種\n🟢 充足：{ok_} 種\n📦 合計：{total} 種"

        # 報表
        elif action == "report":
            return get_monthly_report(lang)

        # BOM 清單
        elif action == "bom":
            bom = get_bom_list()
            if not bom:
                return {"zh": "📋 尚無成品BOM資料", "th": "📋 ไม่มีข้อมูล BOM", "en": "📋 No BOM data yet"}.get(lang)
            products = {}
            for row in bom:
                p = row.get("成品名稱", "")
                if p not in products:
                    products[p] = []
                products[p].append(f"  • {row.get('零件名稱','')} × {row.get('數量','')}")
            lines = []
            for p, parts in products.items():
                lines.append(f"🏭 {p}")
                lines.extend(parts)
                lines.append("")
            title = {"zh": "📋 成品BOM清單", "th": "📋 รายการ BOM สินค้า", "en": "📋 Product BOM List"}.get(lang)
            return f"{title}\n{div}\n" + "\n".join(lines).strip()

        # 開始組合
        elif action == "assemble":
            user_state[uid] = {"step": "assemble_name"}
            return t("assemble_start", lang)

        # 說明
        elif action == "help":
            return t("help", lang)

        # 切換語言
        elif action == "change_lang":
            user_lang.pop(uid, None)
            return "🌐 Select language / 選擇語言 / เลือกภาษา:\n\n1️⃣ 繁體中文\n2️⃣ ภาษาไทย\n3️⃣ English"

        else:
            return t("help", lang)

    except Exception as e:
        return t("error", lang, err=str(e)[:60])


# ── Telegram Webhook ──────────────────────────────────────────
@app.post("/telegram")
async def telegram_webhook(request: Request):
    data = await request.json()
    msg = data.get("message") or data.get("edited_message")
    if not msg:
        return JSONResponse({"ok": True})

    chat_id = msg["chat"]["id"]
    uid = str(msg["from"]["id"])
    text = msg.get("text", "").strip()
    if not text:
        return JSONResponse({"ok": True})

    # myid 指令
    if text.lower() in ("/myid", "myid"):
        await tg_send(chat_id, f"🆔 Your Telegram ID:\n{uid}")
        return JSONResponse({"ok": True})

    # 語言未設定
    lang = user_lang.get(uid)
    if lang is None:
        if text in ("1", "繁體中文", "zh", "中文"):
            user_lang[uid] = "zh"
            await tg_send(chat_id, "✅ 語言：繁體中文\n\n" + t("help", "zh"))
        elif text in ("2", "ภาษาไทย", "th", "ไทย"):
            user_lang[uid] = "th"
            await tg_send(chat_id, "✅ ภาษาไทย\n\n" + t("help", "th"))
        elif text in ("3", "English", "en"):
            user_lang[uid] = "en"
            await tg_send(chat_id, "✅ English\n\n" + t("help", "en"))
        else:
            await tg_send(chat_id, T["welcome"]["zh"])
        return JSONResponse({"ok": True})

    # 語言切換
    if text in ("1", "繁體中文", "zh"):
        user_lang[uid] = "zh"
        await tg_send(chat_id, t("lang_set", "zh"))
        return JSONResponse({"ok": True})
    if text in ("2", "ภาษาไทย", "th"):
        user_lang[uid] = "th"
        await tg_send(chat_id, t("lang_set", "th"))
        return JSONResponse({"ok": True})
    if text in ("3", "English", "en"):
        user_lang[uid] = "en"
        await tg_send(chat_id, t("lang_set", "en"))
        return JSONResponse({"ok": True})

    # 處理指令
    reply = process_cmd(uid, text, lang)
    await tg_send(chat_id, reply)
    return JSONResponse({"ok": True})


async def tg_send(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    async with httpx.AsyncClient() as client:
        await client.post(url, json={"chat_id": chat_id, "text": text})


# ── Health ────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "version": "ERP-v1", "company": "SUPER INTER GROUP (1997)"}

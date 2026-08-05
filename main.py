import asyncio
import json
import os
import re
from datetime import datetime
from typing import Dict, Any, List

import phonenumbers
import requests
from phonenumbers import geocoder
from telegram import (
    __version__ as PTB_VERSION,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    ChatMember,
)
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ChatMemberHandler,
)
from telegram.error import BadRequest, Forbidden

BOT_TOKEN = "8715229700:AAGA1mtLxD0whIMoZGGvzjLp83ghmjz_CVI"
BOT_USERNAME = "zerotimeotp_bot"
DATA_DIR = "data"
LOGS_DIR = os.path.join(DATA_DIR, "logs")
STATES_DIR = os.path.join(DATA_DIR, "states")

APIS_FILE = os.path.join(DATA_DIR, "apis.json")
CHATS_FILE = os.path.join(DATA_DIR, "chats.json")
OWNERS_FILE = os.path.join(DATA_DIR, "owners.json")

DEFAULT_OWNERS = [8927512671]
FETCH_INTERVAL = 3

FIXED_BUTTON_3_NAME = "👑 Owner"
FIXED_BUTTON_3_URL = "https://t.me/zeronumbars"

FIXED_BUTTON_4_NAME = "🪀 Whatsapp"
FIXED_BUTTON_4_URL = "https://chat.whatsapp.com/LwPIdOAbtmnBUhSr0qbNxg?mode=wwt"

DEFAULT_BUTTON_1_NAME = "🔢 Numbers"
DEFAULT_BUTTON_1_URL = "https://t.me/zeronumbars"

DEFAULT_BUTTON_2_NAME = "ZeroTraceNums"
DEFAULT_BUTTON_2_URL = "https://t.me/zeronumbars1"

OWNER_STATE_API_URL = 1
OWNER_STATE_ADD_OWNER = 2
OWNER_STATE_ACTIVATE_GROUP = 4
OWNER_STATE_DEACTIVATE_GROUP = 5
OWNER_STATE_MANAGE_BUTTONS_ID = 6
OWNER_STATE_MANAGE_BUTTONS_1_NAME = 7
OWNER_STATE_MANAGE_BUTTONS_1_URL = 8
OWNER_STATE_MANAGE_BUTTONS_2_NAME = 9
OWNER_STATE_MANAGE_BUTTONS_2_URL = 10

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(STATES_DIR, exist_ok=True)

json_lock = asyncio.Lock()

def safe_load_json(path, default):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default, f, indent=2)
        return default
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except:
            return default

apis = safe_load_json(APIS_FILE, [])
chats = {k: v for k, v in safe_load_json(CHATS_FILE, {}).items() if v.get("type") == "group"}
owners = safe_load_json(OWNERS_FILE, DEFAULT_OWNERS)

api_tasks: Dict[int, asyncio.Task] = {}

async def write_json(path, data):
    async with json_lock:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)

async def save_apis():
    await write_json(APIS_FILE, apis)

async def save_chats():
    groups_only = {k: v for k, v in chats.items() if v.get("type") == "group"}
    await write_json(CHATS_FILE, groups_only)

async def save_owners():
    await write_json(OWNERS_FILE, owners)

def get_api_seen_file(api_id):
    """File that stores the list of unique signatures (hashes) of processed OTPs."""
    return os.path.join(STATES_DIR, f"api_{api_id}_seen.json")

def get_api_log_file(api_id):
    """Human readable log file."""
    return os.path.join(LOGS_DIR, f"api_{api_id}_history.txt")

def load_seen_signatures(api_id) -> List[str]:
    """Loads the list of already processed message signatures from file."""
    path = get_api_seen_file(api_id)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            return []
    except:
        return []

def save_seen_signatures(api_id, signatures: List[str]):
    """Saves the updated list of signatures to file."""
    path = get_api_seen_file(api_id)
    
    if len(signatures) > 1000:
        signatures = signatures[-1000:]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(signatures, f, indent=2, ensure_ascii=False)

def append_to_api_log(api_id, record):
    """Appends the message to a text file log."""
    path = get_api_log_file(api_id)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = (
        f"[{timestamp}] Time: {record.get('time')} | "
        f"Num: {record.get('number')} | "
        f"Msg: {record.get('message')}\n"
        f"{'-'*40}\n"
    )
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(log_entry)
    except Exception as e:
        print(f"Failed to write log for API {api_id}: {e}")

def create_signature(record: dict) -> str:
    """Creates a unique string for a message to detect duplicates."""
    
    return f"{record.get('time')}|{record.get('number')}|{record.get('message')}"

def extract_otp(message: str) -> str:
    for pat in [r'\d{3}-\d{3}', r'\d{6}', r'\d{4}']:
        m = re.search(pat, message)
        if m:
            return m.group(0)
    return "N/A"

def mask_number(number_str: str) -> str:
    try:
        if not number_str.startswith("+"):
            number_str = f"+{number_str}"
        length = len(number_str)
        if length < 10:
            show_first = 4
            show_last = 2
        else:
            show_first = 5
            show_last = 4
        stars_len = length - show_first - show_last
        if stars_len < 0:
            return number_str
        stars = '*' * stars_len
        return f"{number_str[:show_first]}{stars}{number_str[-show_last:]}"
    except:
        return number_str

def get_country_info_from_number(number_str: str):
    try:
        if not number_str.startswith("+"):
            number_str = f"+{number_str}"
        parsed = phonenumbers.parse(number_str)
        country_name = geocoder.description_for_number(parsed, "en")
        region_code = phonenumbers.region_code_for_number(parsed)
        flag = "🌍"
        if region_code and len(region_code) == 2 and region_code.isalpha():
            base = 127462 - ord("A")
            flag_char1 = chr(base + ord(region_code[0].upper()))
            flag_char2 = chr(base + ord(region_code[1].upper()))
            flag = flag_char1 + flag_char2
        display_name = country_name if country_name else (region_code or "Unknown")
        return display_name, flag
    except Exception:
        return "Unknown", "🌍"

def create_message_markup(chat_id_str: str) -> InlineKeyboardMarkup:
    chat_meta = chats.get(chat_id_str, {})
    custom_buttons = chat_meta.get("buttons", [])
    
    kb_row1 = []
    
    btn1_name = custom_buttons[0].get("name", DEFAULT_BUTTON_1_NAME) if len(custom_buttons) > 0 else DEFAULT_BUTTON_1_NAME
    btn1_url = custom_buttons[0].get("url", DEFAULT_BUTTON_1_URL) if len(custom_buttons) > 0 else DEFAULT_BUTTON_1_URL
    kb_row1.append(InlineKeyboardButton(btn1_name, url=btn1_url))

    btn2_name = custom_buttons[1].get("name", DEFAULT_BUTTON_2_NAME) if len(custom_buttons) > 1 else DEFAULT_BUTTON_2_NAME
    btn2_url = custom_buttons[1].get("url", DEFAULT_BUTTON_2_URL) if len(custom_buttons) > 1 else DEFAULT_BUTTON_2_URL
    kb_row1.append(InlineKeyboardButton(btn2_name, url=btn2_url))

    kb_row2 = [
        InlineKeyboardButton(FIXED_BUTTON_3_NAME, url=FIXED_BUTTON_3_URL),
        InlineKeyboardButton(FIXED_BUTTON_4_NAME, url=FIXED_BUTTON_4_URL),
    ]

    return InlineKeyboardMarkup([kb_row1, kb_row2])

def format_message(record: dict, source_id: int, chat_id_str: str):
    raw = record.get("message", "")
    otp = extract_otp(raw)
    msg = raw.replace("<", "&lt;").replace(">", "&gt;")

    country_name, flag = get_country_info_from_number(record.get("number", ""))
    formatted_number = mask_number(record.get("number", ""))

    service_icon = "📱"
    s = (record.get("service") or "").lower()
    if "whatsapp" in s:
        service_icon = "🟢"
    elif "telegram" in s:
        service_icon = "🔵"
    elif "facebook" in s:
        service_icon = "📘"

    text = f"""
<b>{source_id} {flag} New {country_name} {record.get('service','Service')} OTP!</b>

<blockquote>🕰 Time: {record.get('time','')}</blockquote>
<blockquote>{flag} Country: {country_name}</blockquote>
<blockquote>{service_icon} Service: {record.get('service','')}</blockquote>
<blockquote>📞 Number: {formatted_number}</blockquote>
<blockquote>🔑 OTP: <code>{otp}</code></blockquote>

<blockquote>📩 Full Message:</blockquote>
<pre>{msg}</pre>

<b>Powered By Kami_Broken😈
Owner By ᴢᴇʀᴏᴛʀᴀᴄᴇɴᴜᴍs</b>
"""
    return text, create_message_markup(chat_id_str)

def fetch_valid_otps_sync(api_url: str) -> List[dict]:
    """Fetches all valid records from the API, returns list of dicts."""
    try:
        resp = requests.get(api_url, timeout=10)
        data = resp.json()
        records = data.get("aaData", [])
        
        valid_records = []
        for r in records:
            
            if isinstance(r, list) and len(r) >= 5 and isinstance(r[0], str) and ":" in r[0]:
                valid_records.append({
                    "time": r[0],
                    "country": r[1],
                    "number": r[2],
                    "service": r[3],
                    "message": r[4],
                })
        
        return valid_records
    except Exception as e:
        print(f"fetch error {api_url}: {e}")
        return []

async def api_worker(app: Application, api_obj: dict):
    api_id = api_obj["id"]
    url = api_obj["url"]
    
    
    seen_signatures = load_seen_signatures(api_id)
    
    print(f"[WORKER STARTED] API-{api_id} -> {url}")
    
    while True:
        
        current_api_state = next((a for a in apis if a["id"] == api_id), None)
        if not current_api_state or not current_api_state.get("active", True):
            await asyncio.sleep(FETCH_INTERVAL)
            continue
            
        loop = asyncio.get_running_loop()
        
        records = await loop.run_in_executor(None, fetch_valid_otps_sync, url)
        
        
        new_items_found = False
        
        
        for record in reversed(records):
            sig = create_signature(record)
            
            
            if sig not in seen_signatures:
                for chat_id_str, meta in list(chats.items()):
                    try:
                        chat_id = int(chat_id_str)
                    except:
                        continue
                    
                    if not meta.get("active", True) or meta.get("type") != "group":
                        continue
                    
                    text, markup = format_message(record, api_id, chat_id_str)
                    
                    
                    max_retries = 3
                    for attempt in range(max_retries):
                        try:
                            await app.bot.send_message(
                                chat_id=chat_id,
                                text=text,
                                reply_markup=markup,
                                parse_mode="HTML",
                                read_timeout=20,
                                write_timeout=20,
                            )
                            break
                        except asyncio.TimeoutError:
                            if attempt < max_retries - 1:
                                await asyncio.sleep(2)
                            else:
                                print(f"Failed to send to {chat_id}: Timeout")
                        except Exception as e:
                            print(f"Failed to send to {chat_id}: {e}")
                            break

                
                seen_signatures.append(sig)
                
                
                append_to_api_log(api_id, record)
                
                new_items_found = True
                print(f"[{datetime.now()}] API-{api_id} sent NEW OTP: {record.get('number')}")

        
        if new_items_found:
            save_seen_signatures(api_id, seen_signatures)

        await asyncio.sleep(FETCH_INTERVAL)

async def ensure_workers(app: Application):
    for api_obj in apis:
        api_id = api_obj["id"]
        
        if api_id in api_tasks and api_tasks[api_id].done():
            api_tasks[api_id].cancel()
            del api_tasks[api_id]
        
        if api_id not in api_tasks:
            api_tasks[api_id] = asyncio.create_task(api_worker(app, api_obj))

def main_keyboard():
    kb = [
        [InlineKeyboardButton("🔑 Manage OTPs", callback_data="manage_otps")],
        [InlineKeyboardButton("🛠 Manage Buttons", callback_data="manage_buttons")],
        [InlineKeyboardButton("🔧 Owner Panel", callback_data="owner_panel")],
    ]
    return InlineKeyboardMarkup(kb)

def manage_otps_keyboard():
    kb = [
        [InlineKeyboardButton("🟢 Activate OTPs", callback_data="otps_activate_start")],
        [InlineKeyboardButton("🔴 Deactivate OTPs", callback_data="otps_deactivate_start")],
        [InlineKeyboardButton("⬅️ Back", callback_data="back_main")],
    ]
    return InlineKeyboardMarkup(kb)

def owner_panel_keyboard():
    kb = [
        [InlineKeyboardButton("➕ Add New API", callback_data="owner_add_api")],
        
        [InlineKeyboardButton("➕ Add New Owner", callback_data="owner_add_owner")],
        [InlineKeyboardButton("🔁 List APIs", callback_data="owner_list_apis")],
        [InlineKeyboardButton("🗂 Manage Groups", callback_data="owner_list_chats")],
        [InlineKeyboardButton("❌ Close", callback_data="close")],
    ]
    return InlineKeyboardMarkup(kb)

async def owner_chats_list_markup(bot_obj) -> InlineKeyboardMarkup:
    kb = []
    for chat_id_str, meta in list(chats.items()):
        try:
            chat_id = int(chat_id_str)
            chat = await bot_obj.get_chat(chat_id)
            title = chat.title or f"Chat ID: {chat_id}"
            active = meta.get("active", True)
            label = f"{title} ({'🟢' if active else '🔴'})"
            kb.append([InlineKeyboardButton(label, callback_data=f"owner_chat_details|{chat_id_str}")])
        except (BadRequest, Forbidden):
            continue
        except Exception:
            continue
            
    if not kb:
        kb = [[InlineKeyboardButton("No groups are being managed.", callback_data="noop")]]
        
    kb.append([InlineKeyboardButton("⬅️ Back", callback_data="owner_panel")])
    return InlineKeyboardMarkup(kb)

async def owner_chat_details_markup(chat_id_str: str, bot_obj):
    chat_id = int(chat_id_str)
    try:
        chat_info = await bot_obj.get_chat(chat_id)
        chat_title = chat_info.title
    except Exception:
        chat_title = "Unknown Group (ID Only)"
        
    meta = chats.get(chat_id_str, {"active": False})
    status = meta.get("active", False)
    
    kb = [
        [InlineKeyboardButton(f"{'Deactivate 🔴' if status else 'Activate 🟢'}", 
                              callback_data=f"owner_chat_action|{chat_id_str}|{'deactivate' if status else 'activate'}")],
        [InlineKeyboardButton("🗑 Delete Group", callback_data=f"owner_chat_action|{chat_id_str}|delete")],
        [InlineKeyboardButton("⬅️ Back to List", callback_data="owner_list_chats")],
    ]
    
    status_text = f"Group: <b>{chat_title}</b>\nID: <code>{chat_id_str}</code>\nStatus: {'🟢 Active' if status else '🔴 Deactivated'}"
    
    return InlineKeyboardMarkup(kb), status_text

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"[DEBUG-HANDLER] /start received from User ID: {update.effective_user.id}")
    await ensure_workers(context.application)
    await update.effective_chat.send_message("Welcome — choose an action:", reply_markup=main_keyboard())

async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    
    global apis 

    query = update.callback_query
    await query.answer()
    data = query.data or ""
    user = query.from_user

    print(f"[DEBUG-HANDLER] Callback received: {data} from User ID: {user.id}")

    context.user_data.pop("conv_state", None)

    if data == "manage_buttons":
        if user.id not in owners:
            await query.edit_message_text("Access denied. Only owners can manage buttons.")
            return

        context.user_data["conv_state"] = OWNER_STATE_MANAGE_BUTTONS_ID
        await query.edit_message_text(
            "<b>🛠 Button Management:</b>\n\n"
            "Please send the <b>Group Chat ID</b> (e.g., <code>-1001234567890</code>) to manage its custom buttons (Button 1 & 2).\n"
            "<b>Note:</b> You must be an <b>Owner</b> or <b>Admin</b> in the group, and the bot must be an <b>Admin</b> there too."
            , parse_mode='HTML'
        )
        return

    if data == "manage_otps":
        if user.id not in owners:
            await query.edit_message_text("Access denied. Only owners can manage OTP settings.")
            return
        await query.edit_message_text("Manage OTP Status:", reply_markup=manage_otps_keyboard())
        return

    if data == "otps_activate_start":
        if user.id not in owners:
            await query.edit_message_text("Access denied. Only owners can manage OTP settings.")
            return
        context.user_data["conv_state"] = OWNER_STATE_ACTIVATE_GROUP
        await query.edit_message_text(
            "<b>🟢 Activation Mode:</b>\n\n"
            "Please send the <b>Group Chat ID</b> (e.g., <code>-1001234567890</code>) where you want to <b>Activate</b> OTP forwarding. "
            "Ensure the bot is already an <b>Admin</b> in that group.",
            parse_mode='HTML'
        )
        return

    if data == "otps_deactivate_start":
        if user.id not in owners:
            await query.edit_message_text("Access denied. Only owners can manage OTP settings.")
            return
        context.user_data["conv_state"] = OWNER_STATE_DEACTIVATE_GROUP
        await query.edit_message_text(
            "<b>🔴 Deactivation Mode:</b>\n\n"
            "Please send the <b>Group Chat ID</b> (e.g., <code>-1001234567890</code>) where you want to <b>Deactivate</b> OTP forwarding.",
            parse_mode='HTML'
        )
        return

    if data == "owner_panel":
        if user.id not in owners:
            await query.edit_message_text("Owner Panel — Access denied. You are not an owner.")
            return
        await query.edit_message_text("Owner Panel — choose:", reply_markup=owner_panel_keyboard())
        return
        
    if data == "owner_list_chats":
        if user.id not in owners: await query.edit_message_text("Access denied."); return
        markup = await owner_chats_list_markup(context.bot)
        await query.edit_message_text("All Managed Groups (Owner only):", reply_markup=markup)
        return

    if data.startswith("owner_chat_details|"):
        if user.id not in owners: await query.edit_message_text("Access denied."); return
        _, chat_id_str = data.split("|", 1)
        if chat_id_str not in chats:
            await query.edit_message_text("Error: Group not found.", reply_markup=await owner_chats_list_markup(context.bot))
            return
            
        markup, status_text = await owner_chat_details_markup(chat_id_str, context.bot)
        await query.edit_message_text(status_text, parse_mode='HTML', reply_markup=markup)
        return

    if data.startswith("owner_chat_action|"):
        if user.id not in owners: await query.edit_message_text("Access denied."); return
        _, chat_id_str, action = data.split("|", 2)
        
        if chat_id_str not in chats:
            await query.edit_message_text("Group not found.", reply_markup=await owner_chats_list_markup(context.bot))
            return
            
        if action == 'delete':
            del chats[chat_id_str]
            await save_chats()
            await query.edit_message_text(f"Group ID <code>{chat_id_str}</code> has been <b>deleted</b> from management.", parse_mode='HTML', reply_markup=await owner_chats_list_markup(context.bot))
            return
            
        elif action in ('activate', 'deactivate'):
            chats[chat_id_str]["active"] = (action == 'activate')
            await save_chats()
            
            markup, status_text = await owner_chat_details_markup(chat_id_str, context.bot)
            status_update = "Active" if action == 'activate' else "Deactivated"
            await query.edit_message_text(f"Status changed to <b>{status_update}</b>.\n\n{status_text}", parse_mode='HTML', reply_markup=markup)
            return
    
    if data == "owner_add_api":
        if user.id not in owners: await query.edit_message_text("Access denied."); return
        context.user_data["conv_state"] = OWNER_STATE_API_URL
        await query.edit_message_text("Send me the API URL (JSON endpoint). Example:\n<code>https://domain.tld/api/sms?type=sms</code>\n\nSend as plain text in chat.", parse_mode='HTML')
        return
        
    if data == "owner_add_owner":
        if user.id not in owners: await query.edit_message_text("Access denied."); return
        context.user_data["conv_state"] = OWNER_STATE_ADD_OWNER
        await query.edit_message_text("Send me the <b>numeric ID</b> of the new owner.", parse_mode='HTML')
        return

    if data == "owner_list_apis":
        if user.id not in owners: await query.edit_message_text("Access denied."); return
        await query.edit_message_text("APIs:", reply_markup=apis_list_markup())
        return
        
    if data.startswith("api_details|"):
        if user.id not in owners: await query.edit_message_text("Access denied."); return
        _, sid_str = data.split("|", 1)
        sid = int(sid_str)
        api_obj = next((a for a in apis if a["id"] == sid), None)
        if not api_obj:
             await query.edit_message_text("API not found.", reply_markup=owner_panel_keyboard())
             return
        
        status_text = "🟢 Active" if api_obj.get("active", True) else "🔴 Deactivated"
        await query.edit_message_text(f"API-{sid} Details:\nURL: <code>{api_obj['url']}</code>\nStatus: {status_text}", parse_mode='HTML', reply_markup=api_details_markup(sid))
        return

    if data.startswith("api_toggle|"):
        if user.id not in owners: await query.edit_message_text("Access denied."); return
        _, sid_str, action = data.split("|", 2)
        sid = int(sid_str)
        changed = False
        for a in apis:
            if a["id"] == sid:
                a["active"] = (action == 'activate')
                changed = True
                break
        if changed:
            await save_apis()
            await ensure_workers(context.application) 
            api_obj = next((a for a in apis if a["id"] == sid), None)
            status_text = "🟢 Active" if api_obj.get("active", True) else "🔴 Deactivated"
            await query.edit_message_text(f"Toggled API-{sid}. New Status: {status_text}", reply_markup=api_details_markup(sid))
        else:
            await query.edit_message_text("API not found.", reply_markup=owner_panel_keyboard())
        return

    
    if data.startswith("api_delete|"):
        if user.id not in owners:
            await query.edit_message_text("Access denied.")
            return
        
        _, sid_str = data.split("|", 1)
        sid = int(sid_str)
        
        
        new_list = [a for a in apis if a["id"] != sid]
        
        if len(new_list) == len(apis):
             await query.edit_message_text(f"API-{sid} not found to delete.", reply_markup=apis_list_markup())
             return

        apis = new_list
        await save_apis()
        
        
        if sid in api_tasks:
            api_tasks[sid].cancel()
            del api_tasks[sid]
            
        await query.edit_message_text(f"✅ API-{sid} has been deleted successfully.", reply_markup=apis_list_markup())
        return
    

    if data == "owner_panel_back" or data == "back_main":
        await query.edit_message_text("Back to main menu:", reply_markup=main_keyboard())
        return

    if data == "close":
        await query.edit_message_text("Menu closed. Choose an action:", reply_markup=main_keyboard())
        return

    if data == "noop":
        await query.answer("—")
        return

    await query.edit_message_text("Unknown action.", reply_markup=main_keyboard())


async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    
    global apis, chats, owners
    

    user = update.effective_user
    txt = (update.message.text or "").strip()
    conv_state = context.user_data.get("conv_state")
    
    print(f"[DEBUG-HANDLER] Text message received: '{txt}' from User ID: {user.id}. Conv State: {conv_state}")

    if conv_state and user.id in owners:
        
        if conv_state == OWNER_STATE_API_URL:
            if not (txt.startswith("http://") or txt.startswith("https://")):
                await update.message.reply_text("Please send a valid http(s) URL.")
                return
            new_id = max([a["id"] for a in apis], default=0) + 1
            api_obj = {"id": new_id, "url": txt, "active": True}
            apis.append(api_obj)
            await save_apis()
            context.user_data.pop("conv_state")
            await ensure_workers(context.application)
            await update.message.reply_text(f"Added API-{new_id}: <code>{txt}</code>\nWorker started.", parse_mode='HTML', reply_markup=owner_panel_keyboard())
            return
            
        elif conv_state == OWNER_STATE_ADD_OWNER:
            try:
                new_owner_id = int(txt)
                if new_owner_id in owners:
                    await update.message.reply_text("This ID is already an owner.")
                else:
                    owners.append(new_owner_id)
                    await save_owners()
                    await update.message.reply_text(f"Added new owner with ID: <code>{new_owner_id}</code>.", parse_mode='HTML', reply_markup=owner_panel_keyboard())
            except ValueError:
                await update.message.reply_text("Invalid ID. Please send a numeric User ID.")
            
            context.user_data.pop("conv_state")
            return
            
        elif conv_state == OWNER_STATE_MANAGE_BUTTONS_ID:
            try:
                group_id = int(txt)
                group_id_str = str(group_id)
                
                if group_id >= 0:
                    await update.message.reply_text("Invalid Group ID. Group IDs are typically negative.")
                    context.user_data.pop("conv_state")
                    return
                
                bot_member: ChatMember = await context.bot.get_chat_member(group_id, context.bot.id)
                if bot_member.status not in ("administrator", "creator"):
                    await update.message.reply_text("Error: Please make me <b>Admin</b> first in this group.", parse_mode='HTML')
                    context.user_data.pop("conv_state")
                    return

                is_user_owner = user.id in owners
                is_user_admin = False
                if not is_user_owner:
                    user_member: ChatMember = await context.bot.get_chat_member(group_id, user.id)
                    is_user_admin = user_member.status in ("administrator", "creator")
                
                if not is_user_owner and not is_user_admin:
                    await update.message.reply_text("Error: Only <b>Owner</b> or <b>Group Admins</b> can use this function.", parse_mode='HTML')
                    context.user_data.pop("conv_state")
                    return
                
                context.user_data["current_group_id"] = group_id_str
                context.user_data["conv_state"] = OWNER_STATE_MANAGE_BUTTONS_1_NAME
                
                chats.setdefault(group_id_str, {"active": False, "type": "group"}) 
                if "buttons" not in chats[group_id_str] or len(chats[group_id_str]["buttons"]) < 2:
                    chats[group_id_str]["buttons"] = [
                        {"name": DEFAULT_BUTTON_1_NAME, "url": DEFAULT_BUTTON_1_URL},
                        {"name": DEFAULT_BUTTON_2_NAME, "url": DEFAULT_BUTTON_2_URL},
                    ]
                    await save_chats()
                
                await update.message.reply_text(
                    "Group ID validated. Send the <b>Name</b> for <b>Button 1</b> now.", parse_mode='HTML'
                )
                return
                
            except ValueError:
                await update.message.reply_text("Invalid input. Please send a valid numeric Group ID.")
                context.user_data.pop("conv_state")
                return
            except Exception as e:
                await update.message.reply_text(f"An error occurred during verification. Error: {e}")
                context.user_data.pop("conv_state")
                return

        elif conv_state == OWNER_STATE_MANAGE_BUTTONS_1_NAME:
            context.user_data["button_1_name"] = txt
            context.user_data["conv_state"] = OWNER_STATE_MANAGE_BUTTONS_1_URL
            await update.message.reply_text("Now send the <b>URL</b> for <b>Button 1</b>.", parse_mode='HTML')
            return

        elif conv_state == OWNER_STATE_MANAGE_BUTTONS_1_URL:
            context.user_data["button_1_url"] = txt
            context.user_data["conv_state"] = OWNER_STATE_MANAGE_BUTTONS_2_NAME
            await update.message.reply_text("Now send the <b>Name</b> for <b>Button 2</b>.", parse_mode='HTML')
            return

        elif conv_state == OWNER_STATE_MANAGE_BUTTONS_2_NAME:
            context.user_data["button_2_name"] = txt
            context.user_data["conv_state"] = OWNER_STATE_MANAGE_BUTTONS_2_URL
            await update.message.reply_text("Finally, send the <b>URL</b> for <b>Button 2</b>.", parse_mode='HTML')
            return

        elif conv_state == OWNER_STATE_MANAGE_BUTTONS_2_URL:
            group_id_str = context.user_data.get("current_group_id")
            
            button_1_name = context.user_data.get("button_1_name")
            button_1_url = context.user_data.get("button_1_url")
            button_2_name = context.user_data.get("button_2_name")
            button_2_url = context.user_data.get("button_2_url", txt) 
            
            if not all([group_id_str, button_1_name, button_1_url, button_2_name, button_2_url]):
                await update.message.reply_text("Error: Missing button data. Please start the button management process again.", reply_markup=main_keyboard())
                context.user_data.clear()
                return

            chats[group_id_str]["buttons"] = [
                {"name": button_1_name, "url": button_1_url},
                {"name": button_2_name, "url": button_2_url},
            ]
            await save_chats()
            
            await update.message.reply_text(
                f"Buttons for Group ID <code>{group_id_str}</code> updated successfully! Choose an action:",
                parse_mode='HTML',
                reply_markup=main_keyboard()
            )
            
            context.user_data.clear()
            return

    if conv_state in (OWNER_STATE_ACTIVATE_GROUP, OWNER_STATE_DEACTIVATE_GROUP):
        
        action_name = "Active" if conv_state == OWNER_STATE_ACTIVATE_GROUP else "Deactivated"
        is_activation = conv_state == OWNER_STATE_ACTIVATE_GROUP
        
        try:
            group_id = int(txt)
            group_id_str = str(group_id)
            
            if group_id >= 0:
                await update.message.reply_text("Invalid Group ID. Group IDs are typically negative.")
                context.user_data.pop("conv_state")
                return

            bot_member: ChatMember = await context.bot.get_chat_member(group_id, context.bot.id)
            if bot_member.status not in ("administrator", "creator"):
                await update.message.reply_text("Error: Please make me <b>Admin</b> first in this group.", parse_mode='HTML')
                context.user_data.pop("conv_state")
                return

            is_user_owner = user.id in owners
            is_user_admin = False
            if not is_user_owner:
                try:
                    user_member: ChatMember = await context.bot.get_chat_member(group_id, user.id)
                    is_user_admin = user_member.status in ("administrator", "creator")
                except (Forbidden, BadRequest):
                     is_user_admin = False
            
            if not is_user_owner and not is_user_admin:
                await update.message.reply_text("Error: Only <b>Owner</b> or <b>Group Admins</b> can use this function/option.", parse_mode='HTML')
                context.user_data.pop("conv_state")
                return

            chats.setdefault(group_id_str, {"active": is_activation, "type": "group"})
            chats[group_id_str]["active"] = is_activation
            
            if "buttons" not in chats[group_id_str] or len(chats[group_id_str]["buttons"]) < 2:
                 chats[group_id_str]["buttons"] = [
                    {"name": DEFAULT_BUTTON_1_NAME, "url": DEFAULT_BUTTON_1_URL},
                    {"name": DEFAULT_BUTTON_2_NAME, "url": DEFAULT_BUTTON_2_URL},
                ]
            
            await save_chats()
            
            await update.message.reply_text(f"Group ID <code>{group_id}</code> has been <b>{action_name}</b> successfully! Choose an action:", parse_mode='HTML', reply_markup=main_keyboard())
            
        except ValueError:
            await update.message.reply_text("Invalid input. Please send a valid numeric Group ID (e.g., <code>-1001234567890</code>).", parse_mode='HTML')
        except Exception as e:
            await update.message.reply_text(f"An error occurred during verification/update. Ensure the bot is an admin. Error: {e}")
            
        context.user_data.pop("conv_state")
        return

    await update.message.reply_text("Use /start to open menu.")



async def my_chat_member_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cm = update.chat_member 
    chat = cm.chat
    chat_id = str(chat.id)
    old_status = cm.old_chat_member.status
    new_status = cm.new_chat_member.status
    chat_type = chat.type
    
    if chat_type not in ("group", "supergroup"):
        return

    print(f"[DEBUG-MY_CHAT_MEMBER] Chat: {chat_id}, Old Status: {old_status}, New Status: {new_status}")

    if new_status not in ("left", "kicked"):
        global chats 
        chats.setdefault(chat_id, {"active": True, "type": "group"}) 
        if "buttons" not in chats[chat_id] or len(chats[chat_id]["buttons"]) < 2:
            chats[chat_id]["buttons"] = [
                {"name": DEFAULT_BUTTON_1_NAME, "url": DEFAULT_BUTTON_1_URL},
                {"name": DEFAULT_BUTTON_2_NAME, "url": DEFAULT_BUTTON_2_URL},
            ]
        await save_chats()
        print(f"Bot added/promoted in group {chat_id}: {new_status}. Default buttons initialized.")
    
    elif old_status not in ("left", "kicked") and new_status in ("left", "kicked"):
        if chat_id in chats:
            del chats[chat_id]
            await save_chats()
            print(f"Bot removed from group {chat_id}, deleted from chats.json")



def apis_list_markup():
    kb = []
    for api in apis:
        status = "🟢" if api.get("active", True) else "🔴"
        label = f"API-{api['id']} {status}"
        kb.append([InlineKeyboardButton(label, callback_data=f"api_details|{api['id']}")])
    kb.append([InlineKeyboardButton("⬅️ Back to Panel", callback_data="owner_panel")])
    return InlineKeyboardMarkup(kb)

def api_details_markup(api_id):
    api_obj = next((a for a in apis if a["id"] == api_id), None)
    if not api_obj:
        return InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="owner_panel")]])
        
    status = api_obj.get("active", True)
    
    kb = [
        [InlineKeyboardButton(f"{'Deactivate 🔴' if status else 'Activate 🟢'}", 
                              callback_data=f"api_toggle|{api_id}|{'deactivate' if status else 'activate'}")],
        
        [InlineKeyboardButton("🗑 Delete API", callback_data=f"api_delete|{api_id}")],
        
        [InlineKeyboardButton("⬅️ Back to List", callback_data="owner_list_apis")],
    ]
    return InlineKeyboardMarkup(kb)
    
async def on_startup(app: Application):
    print("Bot starting... Ensuring workers and loading saved state.")
    await ensure_workers(app)

def main():
    if BOT_USERNAME == "YOUR_BOT_USERNAME":
        print("ERROR: Please update BOT_USERNAME in the CONFIG section!")
        return
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CallbackQueryHandler(callback_query_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))
    app.add_handler(ChatMemberHandler(my_chat_member_handler, ChatMemberHandler.MY_CHAT_MEMBER))

    app.post_init = on_startup
    print("Running bot (PTB version", PTB_VERSION, ")")
    app.run_polling(allowed_updates=["message", "callback_query", "my_chat_member", "chat_member"])

if __name__ == "__main__":
    main()
import re
import os
import json
import asyncio
import logging
import httpx
import phonenumbers
from datetime import datetime, timedelta
from typing import List, Dict, Any

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, CallbackQuery, ChatMemberUpdated
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

# ======================== CONFIGURATION ========================
BOT_TOKEN = "8715229700:AAFj7_LOwbQt4J_OAs7ubQH_EUMGL8lb1LI"
ADMIN_IDS = [8661200480, 8927512671]

DATA_DIR = "data"
GROUPS_FILE = os.path.join(DATA_DIR, "groups.json")
APIS_FILE = os.path.join(DATA_DIR, "apis.json")
BUTTONS_FILE = os.path.join(DATA_DIR, "buttons.json")
ICON_FILE = os.path.join(DATA_DIR, "icon.txt")
LINKED_CHANNELS_FILE = os.path.join(DATA_DIR, "linked_channels.json")

# Global fallback emoji IDs
ID_GLOBAL_SERVICE_FALLBACK = "6026092115631543342"
ID_GLOBAL_FLAG_FALLBACK = "6025908467124932460"
ID_PREMIUM_DOT = "5972022360025336988"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()

http_client = httpx.AsyncClient(timeout=20.0, follow_redirects=True)
json_lock = asyncio.Lock()

# Caches
groups_cache: List[str] = []
apis_cache: List[Dict[str, Any]] = []
buttons_cache: List[Dict[str, Any]] = []
api_records_cache: Dict[int, set] = {}
linked_channels_cache: Dict[str, str] = {}  # key: group_chat_id, value: channel_link

# Icon mappings
service_icons: Dict[str, str] = {}
flag_icons: Dict[str, str] = {}

# Premium custom emojis (HTML tags) - صرف میسج ٹیکسٹ کے لیے
E_CROWN = '<tg-emoji emoji-id="5467406098367521267">👑</tg-emoji>'
E_GEAR  = '<tg-emoji emoji-id="5424818078833715060">⚙️</tg-emoji>'
E_TICK  = '<tg-emoji emoji-id="5895458739703517004">✅</tg-emoji>'
E_CROSS = '<tg-emoji emoji-id="5852812849780362931">❌</tg-emoji>'
E_LOAD1 = '<tg-emoji emoji-id="5971972727383264364">🔸</tg-emoji>'
E_LOAD2 = '<tg-emoji emoji-id="5971816626796892111">🔹</tg-emoji>'
E_LOAD3 = '<tg-emoji emoji-id="5972124077735807885">🔸</tg-emoji>'
E_LOAD4 = '<tg-emoji emoji-id="5971837680726576448">🔹</tg-emoji>'
E_HEART = '<tg-emoji emoji-id="6023924329673135034">❤️</tg-emoji>'
E_OK    = '<tg-emoji emoji-id="6023773095284707791">👌</tg-emoji>'
E_DASH  = '<tg-emoji emoji-id="6298356878573307709">➖</tg-emoji>'
E_OTP   = '<tg-emoji emoji-id="6298717844804733009">🔑</tg-emoji>'
E_CHANNEL = '<tg-emoji emoji-id="5282843764451195532">🔗</tg-emoji>'

# Custom emoji IDs for buttons
ID_ADD    = "6033108614724456536"
ID_MANAGE = "5197269100878907942"
ID_COPY   = "5472308992514464048"
ID_LINK   = "5282843764451195532"
ID_ADMIN  = "5467406098367521267"
ID_BACK   = "5253997076169115797"
ID_TRASH  = "5372825386591732174"
ID_TOGGLE = "6066348702363031988"
ID_TICK   = "5895458739703517004"
ID_CROSS  = "5852812849780362931"

# new for api id
E_DIGITS = {
    '0': '<tg-emoji emoji-id="5778597459877957448">0️⃣</tg-emoji>',
    '1': '<tg-emoji emoji-id="5778325047282241647">1️⃣</tg-emoji>',
    '2': '<tg-emoji emoji-id="5778507987119247519">2️⃣</tg-emoji>',
    '3': '<tg-emoji emoji-id="5778355910917231510">3️⃣</tg-emoji>',
    '4': '<tg-emoji emoji-id="5778496953348264834">4️⃣</tg-emoji>',
    '5': '<tg-emoji emoji-id="5778429230303941569">5️⃣</tg-emoji>',
    '6': '<tg-emoji emoji-id="5778634662884676303">6️⃣</tg-emoji>',
    '7': '<tg-emoji emoji-id="5778650382464979758">7️⃣</tg-emoji>',
    '8': '<tg-emoji emoji-id="5778572626377052504">8️⃣</tg-emoji>',
    '9': '<tg-emoji emoji-id="5778317599808950144">9️⃣</tg-emoji>',
    '.': '.'
}

# ======================== FSM STATES ========================
class BotStates(StatesGroup):
    wait_btn_name = State()
    wait_btn_url = State()
    wait_api_name = State()
    wait_api_url = State()

# ======================== ICON PARSER ========================
def parse_icon_file():
    global service_icons, flag_icons
    default_text = """
    Facebook = 5778227624539067802
    Snapchat = 5778362190159419841
    WhatsApp = 5778576341523765178
    Tiktok = 5778262705831942198
    chrome = 5778264788891080241
    Telegram = 5778372665584654472
    🇵🇰 = 5269660289321679111
    🇺🇸 = 5202021044105257611
    """
    content = default_text
    if os.path.exists(ICON_FILE):
        with open(ICON_FILE, "r", encoding="utf-8") as f:
            content = f.read()
    for line in content.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, val = [part.strip() for part in line.split("=", 1)]
        if any(ord(char) > 127 for char in key):
            flag_icons[key] = val
        else:
            service_icons[key.lower()] = val

# ======================== PHONE HELPERS ========================
def get_country_flag_character(number_str: str) -> str:
    try:
        if not number_str.startswith("+"):
            number_str = f"+{number_str}"
        parsed = phonenumbers.parse(number_str)
        region_code = phonenumbers.region_code_for_number(parsed)
        if region_code:
            base = 127462 - ord("A")
            return chr(base + ord(region_code[0])) + chr(base + ord(region_code[1]))
    except Exception:
        pass
    return "🌍"

def get_premium_flag_emoji_tag(number_str: str) -> str:
    flag_char = get_country_flag_character(number_str)
    emoji_id = flag_icons.get(flag_char)
    if emoji_id:
        return f'<tg-emoji emoji-id="{emoji_id}">{flag_char}</tg-emoji>'
    return f'<tg-emoji emoji-id="{ID_GLOBAL_FLAG_FALLBACK}">🌍</tg-emoji>'

def get_premium_service_emoji_tag(service_name: str) -> str:
    clean_name = service_name.strip().lower()
    emoji_id = service_icons.get(clean_name)
    if emoji_id:
        return f'<tg-emoji emoji-id="{emoji_id}">📱</tg-emoji>'
    return f'<tg-emoji emoji-id="{ID_GLOBAL_SERVICE_FALLBACK}">⚙️</tg-emoji>'

def mask_number_premium(number_str: str) -> str:
    try:
        clean_num = re.sub(r'\D', '', number_str)
        if len(clean_num) >= 8:
            first_four = clean_num[:4]
            last_four = clean_num[-4:]
            premium_dots = f'<tg-emoji emoji-id="{ID_PREMIUM_DOT}">••••</tg-emoji>'
            return f"+{first_four}{premium_dots}{last_four}"
    except Exception:
        pass
    return number_str

# ======================== JSON HANDLERS ========================
def load_json_sync(file_path: str, default_value: Any) -> Any:
    if not os.path.exists(file_path):
        return default_value
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default_value

async def save_json_async(file_path: str, data: Any):
    async with json_lock:
        tmp_file = file_path + ".tmp"
        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp_file, file_path)
        except Exception as e:
            logging.error(f"Error writing to {file_path}: {e}")

def init_all_json_storage():
    global groups_cache, apis_cache, buttons_cache, linked_channels_cache
    os.makedirs(DATA_DIR, exist_ok=True)
    groups_cache = load_json_sync(GROUPS_FILE, [])
    apis_cache = load_json_sync(APIS_FILE, [])
    buttons_cache = load_json_sync(BUTTONS_FILE, [])
    linked_channels_cache = load_json_sync(LINKED_CHANNELS_FILE, {})
    parse_icon_file()

# ======================== RAW TELEGRAM API ========================
async def send_raw_api_message(chat_id: Any, text: str, reply_markup: dict = None):
    payload = {"chat_id": str(chat_id), "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        return await http_client.post(url, json=payload)
    except Exception as e:
        logging.error(f"send_raw_api_message error: {e}")

async def edit_raw_api_message(chat_id: Any, message_id: int, text: str, reply_markup: dict = None):
    payload = {"chat_id": str(chat_id), "message_id": message_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
    try:
        return await http_client.post(url, json=payload)
    except Exception as e:
        logging.error(f"edit_raw_api_message error: {e}")

async def get_chat_info(chat_id: str) -> dict:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChat"
    try:
        resp = await http_client.post(url, json={"chat_id": chat_id})
        if resp.status_code == 200:
            data = resp.json()
            if data.get("ok"):
                return data.get("result", {})
    except Exception as e:
        logging.error(f"getChat failed for {chat_id}: {e}")
    return {}

async def get_chat_member_status(chat_id: str, bot_id: int) -> str:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember"
    try:
        resp = await http_client.post(url, json={"chat_id": chat_id, "user_id": bot_id})
        if resp.status_code == 200:
            data = resp.json()
            if data.get("ok"):
                return data["result"].get("status", "left")
    except Exception:
        pass
    return "left"

# ======================== LINKED CHANNEL TRACKING ========================
async def update_linked_channels():
    global linked_channels_cache
    updated = False
    for group_id in groups_cache:
        info = await get_chat_info(group_id)
        linked_id = info.get("linked_chat_id")
        if linked_id:
            channel_info = await get_chat_info(str(linked_id))
            link = None
            if channel_info.get("username"):
                link = f"https://t.me/{channel_info['username']}"
            else:
                try:
                    inv_link_resp = await http_client.post(f"https://api.telegram.org/bot{BOT_TOKEN}/exportChatInviteLink", json={"chat_id": linked_id})
                    if inv_link_resp.status_code == 200 and inv_link_resp.json().get("ok"):
                        link = inv_link_resp.json()["result"]
                except:
                    link = None
            if link:
                if linked_channels_cache.get(group_id) != link:
                    linked_channels_cache[group_id] = link
                    updated = True
            else:
                if group_id in linked_channels_cache:
                    del linked_channels_cache[group_id]
                    updated = True
        else:
            if group_id in linked_channels_cache:
                del linked_channels_cache[group_id]
                updated = True
    if updated:
        await save_json_async(LINKED_CHANNELS_FILE, linked_channels_cache)

async def verify_groups_presence():
    global groups_cache
    bot_info = await bot.get_me()
    bot_id = bot_info.id
    removed = False
    for group_id in groups_cache[:]:
        status = await get_chat_member_status(group_id, bot_id)
        if status not in ["administrator", "member"]:
            groups_cache.remove(group_id)
            removed = True
            linked_channels_cache.pop(group_id, None)
    if removed:
        await save_json_async(GROUPS_FILE, groups_cache)
        await save_json_async(LINKED_CHANNELS_FILE, linked_channels_cache)

# ======================== OTP CARD (ORIGINAL BUTTON VALUES RESTORED) ========================
async def send_vip_card_direct(chat_id: str, norm_record: dict, custom_buttons_list: list, api_id: int):
    service = norm_record.get("Service", "Unknown")
    number = norm_record.get("Number", "N/A")
    raw_msg = norm_record.get("Full_message", "")
    
    otp_match = re.search(r'\d{3}[-\s]?\d{3}|\d{4,8}', raw_msg)
    otp = otp_match.group(0) if otp_match else "N/A"

    service_emoji = get_premium_service_emoji_tag(service)
    flag_emoji = get_premium_flag_emoji_tag(number)
    masked_phone = mask_number_premium(number)

    # Convert API ID to premium digit emojis
    api_id_str = str(api_id)
    api_id_emojis = "".join(E_DIGITS.get(char, char) for char in api_id_str)

    text = (
        f"{E_LOAD1}{E_LOAD1}{E_LOAD1}{E_LOAD1}{E_LOAD1}{E_LOAD1}{E_LOAD1}{E_LOAD1}{E_LOAD1}\n"
        f"{api_id_emojis} New {service_emoji} OTP {E_HEART} Received {E_OK}\n"
        f"{E_LOAD2}{E_LOAD2}{E_LOAD2}{E_LOAD2}{E_LOAD2}{E_LOAD2}{E_LOAD2}{E_LOAD2}{E_LOAD2}\n"
        f"{flag_emoji} {E_DASH} {masked_phone}\n"
        f"{E_OTP} {E_DASH} <code>{otp}</code>\n"
        f"{E_LOAD3}{E_LOAD3}{E_LOAD3}{E_LOAD3}{E_LOAD3}{E_LOAD3}{E_LOAD3}{E_LOAD3}{E_LOAD3}\n"
        f"<pre>Message \n{raw_msg}\n</pre>"
        f"{E_LOAD4}{E_LOAD4}{E_LOAD4}{E_LOAD4}{E_LOAD4}{E_LOAD4}{E_LOAD4}{E_LOAD4}{E_LOAD4}"
    )

    inline_keyboard = []

    # Copy button (original fields kept completely intact)
    inline_keyboard.append([{
        "text": f"Copy: {otp}",
        "copy_text": {"text": otp},
        "icon_custom_emoji_id": ID_COPY,
        "style": "success"
    }])

    # Auto channel button
    channel_link = linked_channels_cache.get(chat_id)
    if channel_link:
        inline_keyboard.append([{
            "text": "Numbers",
            "url": channel_link,
            "icon_custom_emoji_id": ID_LINK,
            "style": "primary"
        }])

    # Custom buttons (two per row)
    for i in range(0, len(custom_buttons_list), 2):
        row = []
        for btn in custom_buttons_list[i:i+2]:
            row.append({
                "text": btn["name"],
                "url": btn["url"],
                "icon_custom_emoji_id": ID_LINK,
                "style": "danger"
            })
        if row:
            inline_keyboard.append(row)

    await send_raw_api_message(chat_id, text, {"inline_keyboard": inline_keyboard})

# ======================== STARTUP TEST FUNCTION ========================
async def check_apis_on_startup():
    logging.info("🚀 Startup sequence initiated: Fetching and verifying all pipelines...")
    if not apis_cache:
        return

    current_buttons = [{"name": b["name"], "url": b["url"]} for b in buttons_cache]
    active_apis = [api for api in apis_cache if api.get("is_active") == 1]

    for api in active_apis:
        api_id = api["id"]
        try:
            # 5-second fast timeout check on boot to prevent hanging
            r = await http_client.get(api["url"], timeout=5.0)
            if r.status_code != 200:
                continue

            data = r.json()
            records = data.get("aaData", []) if isinstance(data, dict) else data

            if not isinstance(records, list) or len(records) == 0:
                continue

            current_cycle_sigs = set()
            latest_record = None

            for rec in reversed(records):
                norm = None
                if isinstance(rec, list) and len(rec) >= 5:
                    if rec[0] == "0,0,0,36" or str(rec[0]).startswith("0,0"):
                        continue
                    norm = {"Date-and-time": str(rec[0]), "Service": str(rec[3]), "Number": str(rec[2]), "Full_message": str(rec[4])}
                elif isinstance(rec, dict):
                    if any(k in rec for k in ["Number", "number", "Full_message", "message"]):
                        norm = {
                            "Date-and-time": str(rec.get("Date-and-time") or rec.get("time") or ""),
                            "Service": str(rec.get("Service") or rec.get("service") or "Unknown"),
                            "Number": str(rec.get("Number") or rec.get("number") or "N/A"),
                            "Full_message": str(rec.get("Full_message") or rec.get("message") or "")
                        }

                if not norm or not norm.get("Number") or norm.get("Number") == "N/A":
                    continue

                sig = f"{norm.get('Date-and-time')}|{norm.get('Number')}"
                current_cycle_sigs.add(sig)
                latest_record = norm

            # Cache baseline sync to avoid duplicate processing later
            api_records_cache[api_id] = current_cycle_sigs

            # Send exactly 1 test OTP verification card from this API to all existing groups instantly
            if latest_record and groups_cache:
                for chat_id in groups_cache:
                    await send_vip_card_direct(chat_id, latest_record, current_buttons, api_id)

        except Exception as e:
            logging.error(f"Startup pipeline bypass for API ID {api_id}: Error encountered -> {e}")
            continue

# ======================== BACKGROUND OTP FETCHER ========================
async def background_otp_fetcher():
    while True:
        try:
            if apis_cache and groups_cache:
                current_buttons = [{"name": b["name"], "url": b["url"]} for b in buttons_cache]
                active_apis = [api for api in apis_cache if api.get("is_active") == 1]

                for api in active_apis:
                    api_id = api["id"]
                    try:
                        # Isolated 5.0s timeout per API to eliminate endless waiting / freezes
                        r = await http_client.get(api["url"], timeout=5.0)
                        if r.status_code != 200:
                            continue
                        
                        data = r.json()
                        records = data.get("aaData", []) if isinstance(data, dict) else data
                        
                        if not isinstance(records, list) or len(records) == 0:
                            continue

                        current_cycle_sigs = set()
                        new_records_to_send = []
                        has_valid_format = False

                        for rec in reversed(records):
                            norm = None
                            if isinstance(rec, list) and len(rec) >= 5:
                                if rec[0] == "0,0,0,36" or str(rec[0]).startswith("0,0"):
                                    continue
                                norm = {"Date-and-time": str(rec[0]), "Service": str(rec[3]), "Number": str(rec[2]), "Full_message": str(rec[4])}
                                has_valid_format = True
                            elif isinstance(rec, dict):
                                if any(k in rec for k in ["Number", "number", "Full_message", "message"]):
                                    norm = {
                                        "Date-and-time": str(rec.get("Date-and-time") or rec.get("time") or ""),
                                        "Service": str(rec.get("Service") or rec.get("service") or "Unknown"),
                                        "Number": str(rec.get("Number") or rec.get("number") or "N/A"),
                                        "Full_message": str(rec.get("Full_message") or rec.get("message") or "")
                                    }
                                    has_valid_format = True
                            
                            if not norm or not norm.get("Number") or norm.get("Number") == "N/A":
                                continue
                            
                            sig = f"{norm.get('Date-and-time')}|{norm.get('Number')}"
                            current_cycle_sigs.add(sig)
                            
                            if api_id in api_records_cache and sig not in api_records_cache[api_id]:
                                new_records_to_send.append(norm)

                        if not has_valid_format:
                            continue

                        if api_id not in api_records_cache:
                            if new_records_to_send or current_cycle_sigs:
                                latest_one = new_records_to_send[-1] if new_records_to_send else (norm if 'norm' in locals() and norm else None)
                                if latest_one:
                                    for chat_id in groups_cache:
                                        await send_vip_card_direct(chat_id, latest_one, current_buttons, api_id)
                            api_records_cache[api_id] = current_cycle_sigs
                        else:
                            for new_norm in new_records_to_send:
                                for chat_id in groups_cache:
                                    await send_vip_card_direct(chat_id, new_norm, current_buttons, api_id)
                            api_records_cache[api_id] = current_cycle_sigs
                        
                        await asyncio.sleep(0.2)
                    except Exception as e:
                        # Safely swallows garbage payloads, JSON errors, or dynamic crashes without stopping the loop
                        logging.warning(f"Bypassed active error/crash on API ID {api_id}: {e}")
                        continue
        except Exception:
            pass
        await asyncio.sleep(5)

# ======================== AUTO GROUP TRACKING (my_chat_member) ========================
@router.my_chat_member()
async def on_my_chat_member(update: ChatMemberUpdated):
    chat_id = str(update.chat.id)
    if update.new_chat_member.status in ["member", "administrator"]:
        if chat_id not in groups_cache:
            groups_cache.append(chat_id)
            await save_json_async(GROUPS_FILE, groups_cache)
            await update_linked_channels()
    elif update.new_chat_member.status in ["left", "kicked"]:
        if chat_id in groups_cache:
            groups_cache.remove(chat_id)
            await save_json_async(GROUPS_FILE, groups_cache)
            linked_channels_cache.pop(chat_id, None)
            await save_json_async(LINKED_CHANNELS_FILE, linked_channels_cache)

# ======================== START COMMAND ========================
@router.message(Command("start"))
async def start_cmd(message: Message):
    if message.chat.type in ["group", "supergroup"]:
        return

    text = (
        f"{E_CROWN}{E_CROWN}{E_CROWN}{E_CROWN}{E_CROWN}{E_CROWN}{E_CROWN}{E_CROWN}{E_CROWN}{E_CROWN}{E_CROWN}\n"
        f"{E_CROWN} <b>𝗩𝗜𝗣 𝗢𝗧𝗣 𝗕𝗥𝗢𝗔𝗗𝗖𝗔𝗦𝗧𝗘𝗥</b> {E_CROWN}\n"
        f"{E_CROWN}{E_CROWN}{E_CROWN}{E_CROWN}{E_CROWN}{E_CROWN}{E_CROWN}{E_CROWN}{E_CROWN}{E_CROWN}{E_CROWN}\n\n"
        f"{E_GEAR} <i>Ultra Speed Forwarder System</i> {E_GEAR}\n\n"
        f"Click below to add me to your groups instantly!\n"
    )

    inline_keyboard = [[{
        "text": "Add Bot to Your Group",
        "url": f"https://t.me/ZREOFLEX_bot?startgroup=start",
        "icon_custom_emoji_id": ID_ADD,
        "style": "primary"
    }]]

    if message.from_user.id in ADMIN_IDS:
        inline_keyboard.append([{
            "text": "Owner Panel",
            "callback_data": "owner_main",
            "icon_custom_emoji_id": ID_ADMIN,
            "style": "primary"
        }])

    await send_raw_api_message(message.chat.id, text, {"inline_keyboard": inline_keyboard})

# ======================== OWNER PANEL ========================
@router.callback_query(F.data == "owner_main")
async def owner_panel(q: CallbackQuery, state: FSMContext):
    if q.from_user.id not in ADMIN_IDS:
        return
    await state.clear()

    inline_keyboard = [
        [
            {"text": "Add New API", "callback_data": "adm_add_api", "icon_custom_emoji_id": ID_ADD, "style": "success"},
            {"text": "Manage APIs", "callback_data": "adm_manage_api", "icon_custom_emoji_id": ID_MANAGE, "style": "primary"}
        ],
        [
            {"text": "Add Custom Button", "callback_data": "adm_add_btn", "icon_custom_emoji_id": ID_ADD, "style": "success"},
            {"text": "Manage Buttons", "callback_data": "adm_manage_btn", "icon_custom_emoji_id": ID_MANAGE, "style": "primary"}
        ],
        [
            {"text": "Close Menu", "callback_data": "adm_close", "icon_custom_emoji_id": ID_CROSS, "style": "danger"}
        ]
    ]
    await edit_raw_api_message(q.message.chat.id, q.message.message_id, f"{E_CROWN} <b>Welcome Master to Control Hub</b> {E_CROWN}", {"inline_keyboard": inline_keyboard})

@router.callback_query(F.data == "adm_close")
async def close_panel(q: CallbackQuery):
    await q.message.delete()

# ======================== CUSTOM BUTTON MANAGEMENT ========================
@router.callback_query(F.data == "adm_add_btn")
async def start_add_btn(q: CallbackQuery, state: FSMContext):
    if q.from_user.id not in ADMIN_IDS:
        return
    await state.set_state(BotStates.wait_btn_name)
    await edit_raw_api_message(q.message.chat.id, q.message.message_id, f"{E_GEAR} Send name for the new custom button:")

@router.message(BotStates.wait_btn_name, F.text)
async def process_btn_name(message: Message, state: FSMContext):
    await state.update_data(btn_name=message.text.strip())
    await state.set_state(BotStates.wait_btn_url)
    await message.answer(f"{E_CHANNEL} Now send the destination URL / Link for this button:")

@router.message(BotStates.wait_btn_url, F.text)
async def process_btn_url(message: Message, state: FSMContext):
    url_text = message.text.strip()
    if not (url_text.startswith("http://") or url_text.startswith("https://")):
        await message.answer(f"{E_CROSS} Invalid URL format. Provide link starting with http/https.")
        return
    data = await state.get_data()
    btn_name = data.get("btn_name")
    new_id = max([b["id"] for b in buttons_cache], default=0) + 1
    buttons_cache.append({"id": new_id, "name": btn_name, "url": url_text})
    await save_json_async(BUTTONS_FILE, buttons_cache)
    await state.clear()
    inline_keyboard = [[{"text": "Back to Menu", "callback_data": "owner_main", "icon_custom_emoji_id": ID_BACK, "style": "primary"}]]
    await send_raw_api_message(message.chat.id, f"{E_TICK} <b>Button saved successfully!</b>\nName: {btn_name}\nLink: {url_text}", {"inline_keyboard": inline_keyboard})

@router.callback_query(F.data == "adm_manage_btn")
async def manage_buttons(q: CallbackQuery):
    if q.from_user.id not in ADMIN_IDS:
        return
    if not buttons_cache:
        await edit_raw_api_message(q.message.chat.id, q.message.message_id, f"{E_CROSS} No custom buttons found.", {"inline_keyboard": [[{"text": "Back", "callback_data": "owner_main", "icon_custom_emoji_id": ID_BACK, "style": "primary"}]]})
        return
    inline_keyboard = []
    for row in buttons_cache:
        inline_keyboard.append([{"text": row['name'], "callback_data": f"view_btn_{row['id']}", "icon_custom_emoji_id": ID_MANAGE, "style": "primary"}])
    inline_keyboard.append([{"text": "Back", "callback_data": "owner_main", "icon_custom_emoji_id": ID_BACK, "style": "danger"}])
    await edit_raw_api_message(q.message.chat.id, q.message.message_id, f"{E_GEAR} Select custom button to modify:", {"inline_keyboard": inline_keyboard})

@router.callback_query(F.data.startswith("view_btn_"))
async def view_button_details(q: CallbackQuery):
    if q.from_user.id not in ADMIN_IDS:
        return
    btn_id = int(q.data.split("_")[2])
    btn = next((b for b in buttons_cache if b["id"] == btn_id), None)
    if not btn:
        return
    text = f"<b>Button Details:</b>\n\n<b>Name:</b> {btn['name']}\n<b>Link:</b> <code>{btn['url']}</code>"
    inline_keyboard = [
        [{"text": "Delete Button", "callback_data": f"del_btn_{btn['id']}", "icon_custom_emoji_id": ID_TRASH, "style": "danger"}],
        [{"text": "Back", "callback_data": "adm_manage_btn", "icon_custom_emoji_id": ID_BACK, "style": "primary"}]
    ]
    await edit_raw_api_message(q.message.chat.id, q.message.message_id, text, {"inline_keyboard": inline_keyboard})

@router.callback_query(F.data.startswith("del_btn_"))
async def delete_button(q: CallbackQuery):
    if q.from_user.id not in ADMIN_IDS:
        return
    btn_id = int(q.data.split("_")[2])
    global buttons_cache
    buttons_cache = [b for b in buttons_cache if b["id"] != btn_id]
    await save_json_async(BUTTONS_FILE, buttons_cache)
    inline_keyboard = [[{"text": "Back", "callback_data": "adm_manage_btn", "icon_custom_emoji_id": ID_BACK, "style": "primary"}]]
    await edit_raw_api_message(q.message.chat.id, q.message.message_id, f"{E_TICK} Button deleted successfully!", {"inline_keyboard": inline_keyboard})

# ======================== API MANAGEMENT ========================
@router.callback_query(F.data == "adm_add_api")
async def start_add_api(q: CallbackQuery, state: FSMContext):
    if q.from_user.id not in ADMIN_IDS:
        return
    await state.set_state(BotStates.wait_api_name)
    await edit_raw_api_message(q.message.chat.id, q.message.message_id, f"{E_GEAR} Send custom identification name for this new API:")

@router.message(BotStates.wait_api_name, F.text)
async def process_api_name(message: Message, state: FSMContext):
    await state.update_data(api_name=message.text.strip())
    await state.set_state(BotStates.wait_api_url)
    await message.answer(f"{E_CHANNEL} Now send the JSON Endpoint URL for this pipeline:")

@router.message(BotStates.wait_api_url, F.text)
async def process_api_url(message: Message, state: FSMContext):
    url_text = message.text.strip()
    if not (url_text.startswith("http://") or url_text.startswith("https://")):
        await message.answer(f"{E_CROSS} Provide valid link starting with http/https.")
        return
    data = await state.get_data()
    api_name = data.get("api_name")
    new_id = max([a["id"] for a in apis_cache], default=0) + 1
    apis_cache.append({"id": new_id, "name": api_name, "url": url_text, "is_active": 1})
    await save_json_async(APIS_FILE, apis_cache)
    await state.clear()
    inline_keyboard = [[{"text": "Back to Menu", "callback_data": "owner_main", "icon_custom_emoji_id": ID_BACK, "style": "primary"}]]
    await send_raw_api_message(message.chat.id, f"{E_TICK} <b>Pipeline saved successfully!</b>\nIdentifier Name: {api_name}", {"inline_keyboard": inline_keyboard})

@router.callback_query(F.data == "adm_manage_api")
async def manage_apis(q: CallbackQuery):
    if q.from_user.id not in ADMIN_IDS:
        return
    if not apis_cache:
        await edit_raw_api_message(q.message.chat.id, q.message.message_id, f"{E_CROSS} No APIs found.", {"inline_keyboard": [[{"text": "Back", "callback_data": "owner_main", "icon_custom_emoji_id": ID_BACK, "style": "primary"}]]})
        return
    inline_keyboard = []
    for row in apis_cache:
        status_emoji = ID_TICK if row['is_active'] == 1 else ID_CROSS
        status_style = "success" if row['is_active'] == 1 else "danger"
        inline_keyboard.append([{"text": row['name'], "callback_data": f"api_view_{row['id']}", "icon_custom_emoji_id": status_emoji, "style": status_style}])
    inline_keyboard.append([{"text": "Back", "callback_data": "owner_main", "icon_custom_emoji_id": ID_BACK, "style": "primary"}])
    await edit_raw_api_message(q.message.chat.id, q.message.message_id, f"{E_GEAR} System Dynamic Pipelines:", {"inline_keyboard": inline_keyboard})

@router.callback_query(F.data.startswith("api_view_"))
async def view_api_details(q: CallbackQuery):
    if q.from_user.id not in ADMIN_IDS:
        return
    api_id = int(q.data.split("_")[2])
    api = next((a for a in apis_cache if a["id"] == api_id), None)
    if not api:
        return
    status_str = "Active" if api['is_active'] == 1 else "Deactivated"
    text = f"<b>Pipeline Details:</b>\n\nName: <b>{api['name']}</b>\nURL: <code>{api['url']}</code>\nStatus: {status_str}"
    inline_keyboard = [
        [
            {"text": "Toggle State", "callback_data": f"api_tog_{api['id']}", "icon_custom_emoji_id": ID_TOGGLE, "style": "primary"},
            {"text": "Delete API", "callback_data": f"api_del_{api['id']}", "icon_custom_emoji_id": ID_TRASH, "style": "danger"}
        ],
        [{"text": "Back", "callback_data": "adm_manage_api", "icon_custom_emoji_id": ID_BACK, "style": "primary"}]
    ]
    await edit_raw_api_message(q.message.chat.id, q.message.message_id, text, {"inline_keyboard": inline_keyboard})

@router.callback_query(F.data.startswith("api_tog_"))
async def toggle_api(q: CallbackQuery):
    if q.from_user.id not in ADMIN_IDS:
        return
    api_id = int(q.data.split("_")[2])
    for api in apis_cache:
        if api["id"] == api_id:
            api["is_active"] = 0 if api["is_active"] == 1 else 1
            break
    await save_json_async(APIS_FILE, apis_cache)
    await view_api_details(q)

@router.callback_query(F.data.startswith("api_del_"))
async def delete_api(q: CallbackQuery):
    if q.from_user.id not in ADMIN_IDS:
        return
    api_id = int(q.data.split("_")[2])
    global apis_cache
    apis_cache = [a for a in apis_cache if a["id"] != api_id]
    await save_json_async(APIS_FILE, apis_cache)
    if api_id in api_records_cache:
        del api_records_cache[api_id]
    await manage_apis(q)

# ======================== BACKGROUND TASKS ========================
async def background_linked_updater():
    while True:
        try:
            await update_linked_channels()
            await verify_groups_presence()
        except Exception:
            pass
        await asyncio.sleep(1800)  # Routine check every 30 minutes

# ======================== MAIN RUNNER ========================
async def main():
    init_all_json_storage()
    dp.include_router(router)
    
    # 1. Start execution flow with instant API Hit and verification broadcast
    await check_apis_on_startup()
    
    # 2. Fire continuous workers
    asyncio.create_task(background_otp_fetcher())
    asyncio.create_task(background_linked_updater())
    
    print("🚀 Bot is running with 30-min group verification and full error shielding...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

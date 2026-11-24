import threading, time, re, html, requests, telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

bot = telebot.TeleBot("9070350983:AAFlXeZwBShjYwt31YogdohPHKHeyBJ-RJA", parse_mode="HTML")
users = {}
TBANK_IDS = {"581", "75"}
LIMITS = [3, 5, 10]

def cfg(uid):
    return users.setdefault(uid, {"amt": None, "tp": True, "target": None, "limit": 5, "mon": False, "seen": set(), "step": None, "cache": {}})

def kb(c):
    m = InlineKeyboardMarkup(row_width=2)
    tp = "✅ 1/3 и 3-и лица: ДА" if c["tp"] else "🌐 Все лица: ВСЕ"
    tgt = f"🎯 До {c['target']} ₽" if c["target"] else "🎯 Порог курса"
    mon = "🚨 РАДАР: ВКЛ (стоп)" if c["mon"] else "📡 ВКЛЮЧИТЬ РАДАР"
    m.add(InlineKeyboardButton("💰 Задать сумму", callback_data="set_amt"), InlineKeyboardButton(tgt, callback_data="set_tgt"))
    m.add(InlineKeyboardButton(tp, callback_data="flip_tp"), InlineKeyboardButton(f"📋 Топ-{c['limit']}", callback_data="next_lim"))
    m.add(InlineKeyboardButton("🔎 Обновить Т-Банк", callback_data="scan_now"), InlineKeyboardButton(mon, callback_data="flip_mon"))
    return m

def status(c):
    amt = f"<code>{c['amt']:,.0f} ₽</code>".replace(",", " ") if c["amt"] else "<i>напишите число в чат</i>"
    tgt = f"<code>≤ {c['target']} ₽</code>" if c["target"] else "<i>любой</i>"
    mon = "🟢 <b>Активен</b>" if c["mon"] else "⚪️ Выключен"
    return f"🟡 <b>BYBIT P2P • Т-БАНК (USDT)</b>\n\n💰 <b>Сумма:</b> {amt}\n🏦 <b>Банк:</b> 🟡 Т-Банк / Жёлтый\n👥 <b>Лица:</b> {'1/3 и 3-и лица' if c['tp'] else 'Все'}\n🎯 <b>Макс. курс:</b> {tgt}\n📡 <b>Радар:</b> {mon}\n\n💡 <i>Отправьте сумму в чат (например: <code>6000</code> или <code>23000</code>).</i>"

def is_tbank(item):
    pays = {str(p) for p in item.get("payments", [])}
    rem = (item.get("remark") or "").lower()
    has_tb = any(re.search(p, rem) for p in [r"ж[её]лт", r"yellow", r"т[\s\-]*банк", r"тбанк", r"тиньк", r"tink", r"t[\s\-]*bank"])
    other = any(re.search(p, rem) for p in [r"только\s*зел[её]н", r"только\s*сбер", r"строго\s*зел[её]н", r"строго\s*сбер", r"только\s*красн", r"только\s*альф"])
    return False if (other and not has_tb) else (bool(pays & TBANK_IDS) or has_tb)

def detect_faces(text):
    if not text: return "unknown", "❓ Не указано"
    t = text.lower()
    if any(re.search(p, t) for p in [r"без\s*3", r"без\s*третьих", r"3[\s\-]*и?\s*лица\s*нет", r"не\s*принимаю\s*от\s*3", r"строго\s*от\s*1", r"только\s*1", r"со\s*своей", r"от\s*владельца"]):
        return "first_only", "⚠️ Только 1-е лицо"
    if re.search(r"1\s*[/\\\-–,и]\s*3", t): return "third_ok", "✅ 1/3 лица (свои и третьи)"
    if any(re.search(p, t) for p in [r"3[\s\-]*и?\s*лица", r"3[\s\-]*х\s*лиц", r"третьи", r"третьих", r"от\s*3[\s\-]*го", r"лк\b"]):
        return "third_ok", "✅ 3-и лица / ЛК"
    return "unknown", "❓ Не указано"

def check_amounts(raw, target):
    if not raw: return False, []
    clean = re.sub(r'(\d)\s+(\d{3})', r'\1\2', raw)
    exact, nums = False, []
    for m in re.finditer(r'(\d{3,7})\s*[-–]\s*(\d{3,7})', clean):
        a, b = float(m.group(1)), float(m.group(2))
        nums.append(f"{int(a)}–{int(b)}")
        if min(a, b) <= target <= max(a, b): exact = True
    for m in re.finditer(r'\b(\d{3,7})\b', clean):
        v = float(m.group(1))
        if 500 <= v <= 5000000:
            sv = str(int(v))
            if sv not in nums: nums.append(sv)
            if abs(v - target) < 1: exact = True
    return exact, nums[:8]

def fmt_rem(raw):
    if not raw or not raw.strip(): return "Без описания"
    s = html.escape(raw.strip()[:1200])
    s = re.sub(r'(\d[\d\s.,\-–]{2,}\d|\b\d{3,}\b)', r'<b>\1</b>', s)
    return re.sub(r'(ж[её]лт\w*|т[\s\-]*банк\w*|тбанк\w*|тиньк\w*)', r'<b>\1</b>', s, flags=re.IGNORECASE)
def get_ads(c):
    if not c["amt"]: return []
    payload = {"userId": "", "tokenId": "USDT", "currencyId": "RUB", "payment": [], "side": "1", "size": "50", "page": "1", "amount": str(int(c["amt"])), "authMaker": False, "canTrade": False}
    r = requests.post("https://bybit.com", json=payload, headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}, timeout=15).json()
    res = []
    for i in r.get("result", {}).get("items", []):
        if not is_tbank(i): continue
        mn, mx, price = float(i.get("minAmount", 0)), float(i.get("maxAmount", 0)), float(i.get("price", 0))
        rem, ad_id, uid_m = i.get("remark", ""), str(i.get("id", "")), str(i.get("userId", ""))
        fcode, flabel = detect_faces(rem)
        if (c["tp"] and fcode != "third_ok") or (c["target"] and price > c["target"]): continue
        in_lim = (mn <= c["amt"] <= mx)
        in_rem, rnums = check_amounts(rem, c["amt"])
        if not in_lim and not in_rem: continue
        ords, rate, avail = int(i.get("recentOrderNum", 0)), float(i.get("recentExecuteRate", 0)), float(i.get("lastQuantity", 0))
        badge = "🏆 ТОП" if (ords >= 300 and rate >= 95) else ("🛡 ПРОВЕРЕН" if ords >= 50 else "🆕 НОВЫЙ")
        nick = html.escape(str(i.get("nickName", "Мерчант")))
        c["cache"][ad_id] = {"nick": nick, "uid": uid_m, "price": price}
        tag = "🎯 <b>СУММА ЕСТЬ В ОПИСАНИИ КА!</b>\n" if in_rem else ""
        nline = f"🔢 <b>Суммы у КА:</b> <code>{', '.join(rnums)} ₽</code>\n" if rnums else ""
        card = f"{tag}{badge} | <b>{nick}</b> • 🟡 Т-Банк\n📊 {ords} орд. • {rate}% • ⏱ {i.get('paymentPeriod', 15)} мин\n━━━━━━━━━━━━━━━━━━━━\n👥 <b>Приём:</b> {flabel}\n💵 <b>Курс:</b> <code>{price:.2f} ₽</code> (<b>{c['amt']/price:.2f} USDT</b>)\n📏 <b>Лимиты:</b> <code>{mn:,.0f} – {mx:,.0f} ₽</code>\n{nline}📦 <b>Доступно:</b> <code>{avail:.2f} USDT</code>\n📝 <b>Описание КА:</b>\n<blockquote>{fmt_rem(rem)}</blockquote>".replace(",", " ")
        res.append((0 if in_rem else 1, price, ad_id, card))
    res.sort(key=lambda x: (x[0], x[1]))
    return res

def send_results(chat_id, c):
    w = bot.send_message(chat_id, f"⏳ <i>Ищу КА по Т-Банку под <b>{c['amt']:,.0f} ₽</b>...</i>".replace(",", " "))
    try: ads = get_ads(c)
    except Exception as e: return bot.edit_message_text(f"⚠️ Ошибка Bybit: <code>{html.escape(str(e))}</code>", chat_id, w.message_id)
    if not ads: bot.edit_message_text("😔 <b>Подходящих КА по Т-Банку не найдено.</b>", chat_id, w.message_id)
    else:
        bot.delete_message(chat_id, w.message_id)
        for _, _, ad_id, card in ads[:c["limit"]]:
            c["seen"].add(ad_id)
            m = InlineKeyboardMarkup(); m.add(InlineKeyboardButton("🔗 Получить ссылку на покупку USDT", callback_data=f"link_{ad_id}"))
            bot.send_message(chat_id, card, reply_markup=m)
    bot.send_message(chat_id, status(c), reply_markup=kb(c))

@bot.message_handler(commands=["start"])
def start(m):
    c = cfg(m.from_user.id); c["step"] = None; bot.send_message(m.chat.id, status(c), reply_markup=kb(c))

@bot.callback_query_handler(func=lambda call: True)
def cb(call):
    c = cfg(call.from_user.id); d = call.data
    if d.startswith("link_"):
        ad_id = d.split("_", 1)[1]; info = c["cache"].get(ad_id); bot.answer_callback_query(call.id)
        buy = "https://bybit.com"
        msg = f"🔗 <b>Покупка USDT у {info['nick']}</b> (<code>{info['price']} ₽</code>):\n1️⃣ <a href='https://bybit.com{info['uid']}/USDT/RUB/item'>Профиль и ордера мерчанта</a>\n2️⃣ <a href='{buy}'>Стакан покупки USDT / RUB</a>\n<i>ID:</i> <code>{ad_id}</code>" if (info and info.get("uid")) else f"🔗 <a href='{buy}'>Открыть стакан USDT / RUB</a>"
        return bot.send_message(call.message.chat.id, msg, disable_web_page_preview=True)
    if d == "next_lim": c["limit"] = LIMITS[(LIMITS.index(c["limit"]) + 1) % len(LIMITS)]
    elif d == "flip_tp": c["tp"] = not c["tp"]; c["seen"].clear()
    elif d == "flip_mon":
        if not c["amt"]: return bot.answer_callback_query(call.id, "⚠️ Сначала задайте сумму!", show_alert=True)
        c["mon"] = not c["mon"]; c["seen"].clear()
    elif d == "scan_now":
        if not c["amt"]: return bot.answer_callback_query(call.id, "⚠️ Сначала задайте сумму!", show_alert=True)
        bot.answer_callback_query(call.id); return send_results(call.message.chat.id, c)
    elif d == "set_amt": c["step"] = "amt"; bot.send_message(call.message.chat.id, "💰 Введите сумму в рублях (например: <code>6000</code>):"); return bot.answer_callback_query(call.id)
    elif d == "set_tgt": c["step"] = "target"; bot.send_message(call.message.chat.id, "🎯 Введите макс. курс (например: <code>84.5</code>) или <code>0</code>:"); return bot.answer_callback_query(call.id)
    bot.edit_message_text(status(c), call.message.chat.id, call.message.message_id, reply_markup=kb(c))

@bot.message_handler(func=lambda m: True)
def txt(m):
    c = cfg(m.from_user.id); val = m.text.replace(",", ".").replace(" ", "").strip()
    if c["step"] == "target":
        try: num = float(val); c["target"] = None if num <= 0 else num; c["step"] = None; c["seen"].clear(); return bot.send_message(m.chat.id, status(c), reply_markup=kb(c))
        except: return bot.send_message(m.chat.id, "❌ Введите курс числом или <code>0</code>.")
    try:
        num = float(val); assert num > 0
        c["amt"], c["step"] = num, None; c["seen"].clear(); send_results(m.chat.id, c)
    except: bot.send_message(m.chat.id, "❌ Напишите сумму числом (например: <code>6000</code> или <code>23000</code>).")

def radar():
    while True:
        time.sleep(25)
        for uid, c in list(users.items()):
            if c["mon"] and c["amt"]:
                try:
                    for _, _, ad_id, card in get_ads(c):
                        if ad_id not in c["seen"]:
                            c["seen"].add(ad_id); m = InlineKeyboardMarkup(); m.add(InlineKeyboardButton("🔗 Получить ссылку", callback_data=f"link_{ad_id}"))
                            bot.send_message(uid, "🚨 <b>РАДАР (Т-БАНК): НОВЫЙ КА!</b>\n\n" + card, reply_markup=m)
                except: pass

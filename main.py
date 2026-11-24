import threading, time, re, html, requests, telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

TG_TOKEN = "9070350983:AAFlXeZwBShjYwt31YogdohPHKHeyBJ-RJA"
bot = telebot.TeleBot(TG_TOKEN, parse_mode="HTML")
users = {}

TBANK_IDS = {"581", "75"}
LIMITS = [3, 5, 10]

def cfg(uid):
    return users.setdefault(uid, {
        "amt": None,
        "tp": True,
        "target": None,
        "limit": 5,
        "mon": False,
        "seen": set(),
        "step": None,
        "cache": {}
    })

def kb(c):
    m = InlineKeyboardMarkup(row_width=2)
    tp_txt = "✅ 1/3 и 3-и лица: ДА" if c["tp"] else "🌐 Все лица: ВСЕ"
    tgt_txt = f"🎯 До {c['target']} ₽" if c["target"] else "🎯 Порог курса"
    lim_txt = f"📋 Выдача: Топ-{c['limit']}"
    mon_txt = "🚨 РАДАР: ВКЛ (остановить)" if c["mon"] else "📡 ВКЛЮЧИТЬ РАДАР"

    m.add(InlineKeyboardButton("💰 Задать сумму", callback_data="set_amt"),
          InlineKeyboardButton(tgt_txt, callback_data="set_tgt"))
    m.add(InlineKeyboardButton(tp_txt, callback_data="flip_tp"),
          InlineKeyboardButton(lim_txt, callback_data="next_lim"))
    m.add(InlineKeyboardButton("🔎 Обновить Т-Банк", callback_data="scan_now"),
          InlineKeyboardButton(mon_txt, callback_data="flip_mon"))
    return m

def card_kb(ad_id):
    m = InlineKeyboardMarkup()
    m.add(InlineKeyboardButton("🔗 Получить ссылку на покупку USDT", callback_data=f"link_{ad_id}"))
    return m

def status(c):
    amt_str = f"<code>{c['amt']:,.0f} ₽</code>".replace(",", " ") if c["amt"] else "<i>не задана (напишите число в чат)</i>"
    tgt_str = f"<code>≤ {c['target']} ₽</code>" if c["target"] else "<i>любой</i>"
    mon_str = "🟢 <b>Активен</b> (проверка каждые 25 сек)" if c["mon"] else "⚪️ Выключен"

    return (
        f"╔══════════════════════╗\n"
        f"║  🟡 <b>BYBIT P2P • Т-БАНК (USDT)</b>  ║\n"
        f"╚══════════════════════╝\n\n"
        f"💰 <b>Нужная сумма:</b> {amt_str}\n"
        f"🏦 <b>Банк:</b> 🟡 Т-Банк / Жёлтый банк\n"
        f"👥 <b>Фильтр лиц:</b> {'Только 1/3 и 3-и лица' if c['tp'] else 'Показывать всех'}\n"
        f"🎯 <b>Макс. курс:</b> {tgt_str}\n"
        f"📡 <b>Фоновый радар:</b> {mon_str}\n\n"
        f"💡 <i>Напишите нужную сумму в чат (например: <code>6000</code> или <code>23000</code>).</i>"
    )

def is_tbank_ad(item):
    payments = {str(p) for p in item.get("payments", [])}
    rem = (item.get("remark") or "").lower()

    # Явные слова Т-Банка / Жёлтого банка в описании
    tbank_words = [
        r"ж[её]лт", r"yellow", r"т[\s\-]*банк", r"тбанк",
        r"тиньк", r"tink", r"t[\s\-]*bank"
    ]
    has_tbank_text = any(re.search(p, rem) for p in tbank_words)

    # Исключаем, если в тексте строго указан только другой банк (например, только зелёный/сбер)
    other_only = [
        r"только\s*зел[её]н", r"только\s*сбер", r"строго\s*зел[её]н", r"строго\s*сбер",
        r"только\s*красн", r"только\s*альф"
    ]
    if any(re.search(p, rem) for p in other_only) and not has_tbank_text:
        return False

    if payments & TBANK_IDS:
        return True
    if has_tbank_text:
        return True
    return False

def detect_faces(text):
    if not text:
        return "unknown", "❓ Не указано в описании"
    t = text.lower()
    ban = [
        r"без\s*3", r"без\s*третьих", r"3[\s\-]*и?\s*лица\s*нет",
        r"не\s*принимаю\s*от\s*3", r"не\s*принимаю\s*от\s*третьих",
        r"строго\s*от\s*1", r"только\s*1[\s\-]*е?\s*лицо",
        r"только\s*со\s*своей", r"от\s*владельца"
    ]
    if any(re.search(p, t) for p in ban):
        return "first_only", "⚠️ Только 1-е лицо (со своей карты)"
    if re.search(r"1\s*[/\\\-–,и]\s*3", t):
        return "third_ok", "✅ 1/3 лица (свои и третьи)"
    ok = [r"3[\s\-]*и?\s*лица", r"3[\s\-]*х\s*лиц", r"третьи", r"третьих", r"от\s*3[\s\-]*го", r"лк\b"]
    if any(re.search(p, t) for p in ok):
        return "third_ok", "✅ 3-и лица / ЛК"
    return "unknown", "❓ Не указано в описании"

def check_remark_amounts(raw_remark, target_amt):
    if not raw_remark:
        return False, []
    clean = re.sub(r'(\d)\s+(\d{3})', r'\1\2', raw_remark)
    exact_match = False
    found_nums = []

    for m in re.finditer(r'(\d{3,7})\s*[-–]\s*(\d{3,7})', clean):
        a, b = float(m.group(1)), float(m.group(2))
        found_nums.append(f"{int(a)}–{int(b)}")
        if min(a, b) <= target_amt <= max(a, b):
            exact_match = True

    for m in re.finditer(r'\b(\d{3,7})\b', clean):
        val = float(m.group(1))
        if 500 <= val <= 5000000:
            s_val = str(int(val))
            if s_val not in found_nums:
                found_nums.append(s_val)
            if abs(val - target_amt) < 1:
                exact_match = True

    return exact_match, found_nums[:8]

def format_remark(raw_remark):
    if not raw_remark or not raw_remark.strip():
        return "Без описания"
    safe = html.escape(raw_remark.strip()[:1200])
    # Выделяем жирным суммы и упоминания жёлтого / Т-Банка
    safe = re.sub(r'(\d[\d\s.,\-–]{2,}\d|\b\d{3,}\b)', r'<b>\1</b>', safe)
    safe = re.sub(r'(ж[её]лт\w*|т[\s\-]*банк\w*|тбанк\w*|тиньк\w*)', r'<b>\1</b>', safe, flags=re.IGNORECASE)
    return safe

def get_ads(c):
    if not c["amt"]:
        return []
    # Запрашиваем общий стакан (payment=[]), чтобы поймать и тех, кто скрыл тег Т-Банка и написал «жёлтый банк» в тексте
    payload = {
        "userId": "",
        "tokenId": "USDT",
        "currencyId": "RUB",
        "payment": [],
        "side": "1",
        "size": "50",
        "page": "1",
        "amount": str(int(c["amt"])),
        "authMaker": False,
        "canTrade": False
    }
    headers = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}
    r = requests.post("https://bybit.com", json=payload, headers=headers, timeout=15).json()
    items = r.get("result", {}).get("items", [])

    res = []
    for i in items:
        if not is_tbank_ad(i):
            continue

        mn, mx = float(i.get("minAmount", 0)), float(i.get("maxAmount", 0))
        price = float(i.get("price", 0))
        rem = i.get("remark", "")
        ad_id = str(i.get("id", ""))
        uid_maker = str(i.get("userId", ""))

        face_code, face_label = detect_faces(rem)
        if c["tp"] and face_code != "third_ok":
            continue
        if c["target"] and price > c["target"]:
            continue

        in_limits = (mn <= c["amt"] <= mx)
        in_remark, rem_nums = check_remark_amounts(rem, c["amt"])

        if not in_limits and not in_remark:
            continue

        orders = int(i.get("recentOrderNum", 0))
        rate = float(i.get("recentExecuteRate", 0))
        avail = float(i.get("lastQuantity", 0))
        pay_period = i.get("paymentPeriod", 15)
        badge = "🏆 ТОП" if (orders >= 300 and rate >= 95) else ("🛡 ПРОВЕРЕН" if orders >= 50 else "🆕 НОВЫЙ")
        usdt_calc = c["amt"] / price if price > 0 else 0
        nick = html.escape(str(i.get("nickName", "Мерчант")))
        rem_formatted = format_remark(rem)

        c["cache"][ad_id] = {
            "nick": nick,
            "uid": uid_maker,
            "price": price,
            "amt": c["amt"]
        }

        match_tag = "🎯 <b>СУММА ЕСТЬ В ОПИСАНИИ КА!</b>\n" if in_remark else ""
        nums_line = f"🔢 <b>Суммы в тексте КА:</b> <code>{', '.join(rem_nums)} ₽</code>\n" if rem_nums else ""

        card = (
            f"{match_tag}"
            f"{badge} | <b>{nick}</b> • 🟡 Т-Банк / Жёлтый\n"
            f"📊 {orders} орд. • {rate}% • ⏱ {pay_period} мин\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👥 <b>Приём:</b> {face_label}\n"
            f"💵 <b>Курс:</b> <code>{price:.2f} ₽</code>  (получите <b>{usdt_calc:.2f} USDT</b>)\n"
            f"📏 <b>Лимиты ордера:</b> <code>{mn:,.0f} – {mx:,.0f} ₽</code>\n"
            f"{nums_line}"
            f"📦 <b>Доступно:</b> <code>{avail:.2f} USDT</code>\n"
            f"📝 <b>Описание КА:</b>\n<blockquote>{rem_formatted}</blockquote>"
        ).replace(",", " ")

        res.append((0 if in_remark else 1, price, ad_id, card))

    res.sort(key=lambda x: (x[0], x[1]))
    return res

def send_results(chat_id, c):
    w = bot.send_message(chat_id, f"⏳ <i>Ищу КА (Т-Банк / жёлтый) под <b>{c['amt']:,.0f} ₽</b>...</i>".replace(",", " "))
    try:
        ads = get_ads(c)
    except Exception as e:
        bot.edit_message_text(f"⚠️ Ошибка запроса к Bybit: <code>{html.escape(str(e))}</code>", chat_id, w.message_id)
        return
    if not ads:
        bot.edit_message_text("😔 <b>Подходящих КА по Т-Банку / жёлтому банку не найдено.</b>\nПопробуйте изменить сумму, порог курса или переключить фильтр лиц.", chat_id, w.message_id)
    else:
        bot.delete_message(chat_id, w.message_id)
        for _, _, ad_id, card in ads[:c["limit"]]:
            c["seen"].add(ad_id)
            bot.send_message(chat_id, card, reply_markup=card_kb(ad_id))
    bot.send_message(chat_id, status(c), reply_markup=kb(c))

@bot.message_handler(commands=["start"])
def start(m):
    c = cfg(m.from_user.id)
    c["step"] = None
    bot.send_message(m.chat.id, status(c), reply_markup=kb(c))

@bot.callback_query_handler(func=lambda call: True)
def cb(call):
    c = cfg(call.from_user.id)
    d = call.data

    if d.startswith("link_"):
        ad_id = d.split("_", 1)[1]
        info = c["cache"].get(ad_id)
        bot.answer_callback_query(call.id)
        buy_url = "https://bybit.com"
        if info and info.get("uid"):
            prof_url = f"https://bybit.com{info['uid']}/USDT/RUB/item"
            msg = (
                f"🔗 <b>Ссылки для покупки USDT у {info['nick']}</b> (🟡 Т-Банк / жёлтый, курс <code>{info['price']} ₽</code>):\n\n"
                f"1️⃣ <a href='{prof_url}'>Открыть профиль и ордера мерчанта {info['nick']}</a>\n"
  

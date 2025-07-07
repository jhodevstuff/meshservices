import warnings
from warnings import showwarning as _showwarning

import time
import subprocess

def _filter_ssl_warning(message, category, filename, lineno, file=None, line=None):
    if 'NotOpenSSLWarning' in str(message):
        return
    return _showwarning(message, category, filename, lineno, file, line)
warnings.showwarning = _filter_ssl_warning
warnings.filterwarnings("ignore", category=UserWarning, module="urllib3")

import serial
import json
import re
from datetime import datetime
import requests
import smtplib
from email.mime.text import MIMEText
import glob
import platform
from bs4 import BeautifulSoup
import threading
last_warn_check = None

warned_ids = set()

def fetch_dwd_warnings():
    try:
        url = "https://warnung.bund.de/bbk.mowas/gefahrendurchsagen.json"
        dwd_url = "https://warnung.bund.de/bbk.dwd/unwetter.json"
        resp = requests.get(dwd_url, timeout=10)
        data = resp.json()
        bayern_warnings = []
        for warn in data:
            # Bayern
            if warn.get('stateShort') == 'BY' and warn.get('level', 0) >= 3:
                bayern_warnings.append(warn)
        resp2 = requests.get(url, timeout=10)
        data2 = resp2.json()
        bayern_cat = [w for w in data2 if w.get('stateShort') == 'BY']
        return bayern_warnings, bayern_cat
    except Exception as e:
        print(f"{datetime.now()} - Error fetching warnings: {e}")
        return [], []

def warn_service(message, nodeid):
    # call @warn for current state
    bayern_warnings, bayern_cat = fetch_dwd_warnings()
    meldungen = []
    for w in bayern_warnings:
        meldungen.append(f"DWD: {w.get('headline', 'Warnung')} (Stufe {w.get('level')}) - {w.get('description', '')}")
    for w in bayern_cat:
        meldungen.append(f"Katastrophe: {w.get('headline', 'Warnung')} - {w.get('description', '')}")
    if meldungen:
        send_message_to_node(nodeid, '\n\n'.join(meldungen))
    else:
        send_message_to_node(nodeid, "Keine aktuellen Unwetter- oder Katastrophenwarnungen für Bayern.")

def warn_background_loop():
    global warned_ids
    while True:
        bayern_warnings, bayern_cat = fetch_dwd_warnings()
        meldungen = []
        neue_ids = set()
        for w in bayern_warnings:
            wid = w.get('identifier')
            if wid and wid not in warned_ids:
                meldungen.append(f"DWD: {w.get('headline', 'Warnung')} (Stufe {w.get('level')}) - {w.get('description', '')}")
                neue_ids.add(wid)
        for w in bayern_cat:
            wid = w.get('identifier')
            if wid and wid not in warned_ids:
                meldungen.append(f"Katastrophe: {w.get('headline', 'Warnung')} - {w.get('description', '')}")
                neue_ids.add(wid)
        if meldungen:
            for msg in meldungen:
                try:
                    # Send warning to channel 0 - because this may be important
                    cli_path = get_meshtastic_cli_path()
                    cmd = f"{cli_path} --ch-index 0 --sendtext '{msg}'"
                    ser_was_open = False
                    try:
                        try:
                            if ser and ser.is_open:
                                ser.close()
                                ser_was_open = True
                        except Exception:
                            pass
                        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL)
                        if result.returncode != 0 or result.stderr:
                            raise Exception(result.stderr)
                        print(f"{datetime.now()} - Sent warning to channel: {msg}")
                    except Exception as e:
                        print(f"{datetime.now()} - Error on first attempt to send to channel: {str(e)}. Try again with 30 secs.")
                        try:
                            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
                            if result.returncode != 0 or result.stderr:
                                raise Exception(result.stderr)
                            print(f"{datetime.now()} - Warning sent to channel on second attempt: {msg}")
                        except Exception as e2:
                            print(f"{datetime.now()} - Error on second attempt to send to channel: {str(e2)}")
                    time.sleep(2)
                    try:
                        if ser_was_open and not ser.is_open:
                            ser.open()
                            print(f"{datetime.now()} - Serial port reopened.")
                    except Exception as e:
                        print(f"{datetime.now()} - Error reopening serial port: {str(e)}")
                except Exception as e:
                    print(f"{datetime.now()} - Error sending warning to channel: {e}")
            warned_ids.update(neue_ids)
        time.sleep(900)
        
# Log all messages (no service requests)
def log_json_message(entry, log_file, api_url, api_key):
    if "timestamp" not in entry or not entry["timestamp"]:
        entry["timestamp"] = datetime.now().isoformat()
    if 'from' in entry and entry['from'].startswith('0x'):
        entry['from'] = '!' + entry['from'][2:]
    with open(log_file, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"{datetime.now()} - Logged message: {entry}")
    try:
        response = requests.post(
            api_url,
            json=entry,
            headers={"X-API-KEY": api_key}
        )
        if response.status_code == 200:
            print(f"{datetime.now()} - Successfully pushed to server.")
        else:
            print(f"{datetime.now()} - Error on POST: {response.status_code} {response.text}")
    except Exception as e:
        print(f"{datetime.now()} - Error on POST: {str(e)}")

# Service @mail (not functional for now)
def mail_service(message, nodeid):
    import re
    if nodeid.startswith('0x'):
        nodeid = '!' + nodeid[2:]
    mail_config = load_config().get('mail', {})
    SMTP_SERVER = mail_config['smtp']['server']
    SMTP_PORT = mail_config['smtp']['port']
    SMTP_USER = mail_config['smtp']['user']
    SMTP_PASSWORD = mail_config['smtp']['password']
    DEFAULT_SENDER_NAME = mail_config.get('default_sender', 'Mesh-Service')
    LOG_FILE = "meshmail.log"
    def log_message(message):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, "a") as log_file:
            log_file.write(f"{timestamp} - {message}\n")
    lines = [l.strip() for l in message.split('\n')]
    if lines and lines[0].lower() == '@mail':
        lines = lines[1:]
    lines = [l for l in lines if l]
    fields = {}
    content_lines = []
    current_field = None
    for line in lines:
        m = re.match(r'^(to|from|subject|content):\s*(.*)$', line, re.IGNORECASE)
        if m:
            field = m.group(1).lower()
            value = m.group(2)
            if field == 'content':
                current_field = 'content'
                if value:
                    content_lines.append(value)
            else:
                fields[field] = value
                current_field = None
        elif current_field == 'content':
            content_lines.append(line)
    fields['content'] = '\n'.join(content_lines).strip()
    recipient = fields.get('to')
    subject = fields.get('subject')
    sender_name = fields.get('from')
    content = fields.get('content')
    if recipient and subject and content:
        msg = MIMEText(content)
        msg['Subject'] = subject
        msg['From'] = f"{sender_name} <{SMTP_USER}>" if sender_name else f"{DEFAULT_SENDER_NAME} <{SMTP_USER}>"
        msg['To'] = recipient
        try:
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.send_message(msg)
            log_message(f"Sent Mail successfully! {recipient}, Subject: {subject}, Content: {content}")
            print(f"{datetime.now()} - Sent Mail successfully! {recipient}")
            send_message_to_node(nodeid, "Mail erfolgreich gesendet!")
        except Exception as e:
            log_message(f"Error while sending mail: {str(e)}")
            print(f"{datetime.now()} - Error while sending mail: {str(e)}")
            send_message_to_node(nodeid, f"Fehler beim Senden der Mail: {e}")
    else:
        fehlende = []
        if not recipient:
            fehlende.append('to:')
        if not subject:
            fehlende.append('subject:')
        if not content:
            fehlende.append('content:')
        help_text = (
            "Mail-Service Hilfe: Sende eine Nachricht im Format:\n"
            "@mail to: <empfaenger@email> subject: <betreff> content: <text> [from: <dein name>]\n"
            "Beispiel:\n@mail to: test@example.com subject: Test content: Hallo Welt!\n"
        )
        if fehlende:
            help_text = f"Fehlende Felder: {', '.join(fehlende)}\n" + help_text
        log_message(f"Mail message invalid: {message} (NodeID: {nodeid})")
        print(f"{datetime.now()} - Mail message invalid: {message} (NodeID: {nodeid})")
        send_message_to_node(nodeid, help_text)

# Service @test
def test_service(message, nodeid):
    test_text = "Ack test."
    send_message_to_node(nodeid, test_text)

# Service @wetter
def weather_service(message, nodeid):
    weather_config = load_config().get('weather', {})
    provider = weather_config.get('provider', 'wttr.in')
    arg = message.strip()
    if not arg:
        help_text = (
            "Wetter-Service Hilfe: Sende eine Nachricht im Format:\n"
            "@wetter <PLZ oder Ort>\n"
            "Beispiel:\n@wetter Wolfratshausen oder @wetter 82515"
        )
        send_message_to_node(nodeid, help_text)
        return
    location = arg.replace(' ', '+')
    url = f"https://wttr.in/{location}?format=j1"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            current = data['current_condition'][0]
            weather = data['weather'][0]
            temp = current['temp_C']
            feels = current['FeelsLikeC']
            desc = current['weatherDesc'][0]['value']
            wind = current['windspeedKmph']
            humidity = current['humidity']
            rain = weather['hourly'][0]['chanceofrain']
            msg = (
                f"Wetter für {arg}: {desc}, {temp}°C (gefühlt {feels}°C), "
                f"Wind: {wind} km/h, Luftfeuchte: {humidity}%, Regenwahrscheinlichkeit: {rain}%"
            )
            send_message_to_node(nodeid, msg)
        else:
            send_message_to_node(nodeid, f"Fehler beim Abrufen des Wetters für {arg}.")
    except Exception as e:
        send_message_to_node(nodeid, f"Fehler beim Abrufen des Wetters: {str(e)}")

# Service @google
def google_service(message, nodeid):
    query = message.strip()
    print(f"{datetime.now()} - [Google-Service] Called with query: '{query}' for NodeID: {nodeid}")
    if not query:
        help_text = (
            "Google-Service Hilfe: Sende eine Nachricht im Format:\n"
            "@google <Suchtext>\nBeispiel:\n@google dies ist ein test"
        )
        print(f"{datetime.now()} - [Google-Service] No query provided, sending help text.")
        send_message_to_node(nodeid, help_text)
        return
    results = []
    try:
        ddg_url = f'https://duckduckgo.com/html/?q={requests.utils.quote(query)}'
        resp = requests.get(ddg_url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
        soup = BeautifulSoup(resp.text, 'html.parser')
        links = soup.select('.result__a')
        for a in links[:5]:
            title = a.get_text()
            href = a['href']
            if href.startswith('//duckduckgo.com/l/?uddg='):
                import urllib.parse
                parsed = urllib.parse.urlparse(href)
                query_params = urllib.parse.parse_qs(parsed.query)
                real_url = query_params.get('uddg', [''])[0]
                real_url = urllib.parse.unquote(real_url)
                results.append((title, real_url))
            else:
                results.append((title, href))
        print(f"{datetime.now()} - [Google-Service] DuckDuckGo: {len(results)} results found.")
    except Exception as e:
        print(f"{datetime.now()} - [Google-Service] Error during DuckDuckGo search: {str(e)}")
        send_message_to_node(nodeid, f"Fehler bei der DuckDuckGo-Suche: {str(e)}")
        return
    antworten = []
    for title, url in results:
        try:
            print(f"{datetime.now()} - [Google-Service] Loading and summarizing: {title}")
            page = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            soup = BeautifulSoup(page.text, 'html.parser')
            texts = soup.find_all(['p', 'div'])
            text_content = ' '.join([t.get_text(separator=' ', strip=True) for t in texts])
            words = text_content.split()
            summary = ' '.join(words[:10]) + ('...' if len(words) > 10 else '')
            antworten.append(f"{title}\n{summary}")
        except Exception as e:
            print(f"{datetime.now()} - [Google-Service] Error summarizing '{title}': {e}")
            pass
    if not antworten:
        antworten = ["Keine Suchergebnisse gefunden."]
    antwort = '\n\n'.join(antworten)
    print(f"{datetime.now()} - [Google-Service] Sending answer to NodeID {nodeid}: {antwort}")
    send_message_to_node(nodeid, antwort)

# Service @news
def news_service(message, nodeid):
    import feedparser
    try:
        feed_url = "https://www.tagesschau.de/xml/rss2"
        print(f"{datetime.now()} - [News-Service] Fetching news feed: {feed_url}")
        feed = feedparser.parse(feed_url)
        headlines = []
        for entry in feed.entries[:10]:
            title = entry.title.strip()
            headlines.append(f"- {title}")
        if headlines:
            nachricht = "Aktuelle Nachrichten:\n" + "\n".join(headlines)
        else:
            nachricht = "Keine aktuellen Nachrichten gefunden."
        print(f"{datetime.now()} - [News-Service] Sending to NodeID {nodeid}: {nachricht}")
        send_message_to_node(nodeid, nachricht)
    except Exception as e:
        print(f"{datetime.now()} - [News-Service] Error: {e}")
        send_message_to_node(nodeid, f"Fehler beim Laden der Nachrichten: {e}")

# Service @wiki
def wiki_service(message, nodeid):
    import wikipedia
    query = message.strip()
    if not query:
        send_message_to_node(nodeid, "Wiki-Service Hilfe: @wiki <Suchbegriff>")
        return
    for lang in ["de", "en"]:
        try:
            wikipedia.set_lang(lang)
            try:
                summary = wikipedia.summary(query, sentences=2, auto_suggest=False)
            except wikipedia.exceptions.PageError:
                summary = wikipedia.summary(query, sentences=2, auto_suggest=True)
            send_message_to_node(nodeid, summary)
            return
        except wikipedia.exceptions.DisambiguationError as e:
            vorschlaege = ', '.join(e.options[:3])
            send_message_to_node(nodeid, f"Mehrdeutig: {vorschlaege}")
            return
        except wikipedia.exceptions.PageError:
            continue
        except Exception as e:
            continue
    send_message_to_node(nodeid, "Kein Wikipedia-Artikel dazu gefunden, sorry.")

# Service @translate
def translate_service(message, nodeid):
    from googletrans import Translator
    try:
        parts = message.strip().split(None, 1)
        if len(parts) < 2:
            send_message_to_node(nodeid, "Translate-Service Hilfe: @translate <zielsprachcode> <Text>")
            return
        lang, text = parts[0], parts[1]
        translator = Translator()
        result = translator.translate(text, dest=lang)
        send_message_to_node(nodeid, result.text)
    except Exception as e:
        send_message_to_node(nodeid, f"Fehler: {e}")

def load_config():
    with open('config.json') as config_file:
        config = json.load(config_file)
        return config

def load_services_config():
    config = load_config()
    return config.get('services', {})

# extract text messages from serial log
def extract_text_message(raw):
    match = re.search(r"Received text msg from=(0x[0-9a-fA-F]+), id=(0x[0-9a-fA-F]+), msg=(.*)", raw)
    if match:
        return {
            "from": match.group(1),
            "msg_id": match.group(2),
            "text": match.group(3)
        }
    return None

# Service @radar (WIP / please adjust)
# Usage: Detection Sensor Module Message with @radar xyz
def radar_service(message, nodeid):
    cleaned = message.replace('#', '').strip()
    config = load_config()
    radar_channel = config.get('radar_channel_index', 3)
    radar_config = config.get('radar', {})
    import re
    from datetime import datetime
    def is_time_in_range(timerange):
        if not timerange or not isinstance(timerange, str):
            return False
        try:
            now = datetime.now().time()
            start_str, end_str = timerange.split('-')
            start = datetime.strptime(start_str.strip(), '%H:%M').time()
            end = datetime.strptime(end_str.strip(), '%H:%M').time()
            if start <= end:
                return start <= now <= end
            else:
                return now >= start or now <= end
        except Exception:
            return False
    if not hasattr(radar_service, "_detection_times"):
        radar_service._detection_times = {}
    detection_times = radar_service._detection_times
    parts = cleaned.split()
    radar_name = parts[0] if parts else None
    is_notify = any(p.lower() == "$notify" for p in parts)
    radar_settings = radar_config.get(radar_name, {"mail": False, "ignore": False})
    alias_name = radar_settings.get("aliasName")
    def radar_display_name():
        if alias_name:
            return f"{radar_name} ({alias_name})"
        return radar_name
    dta = radar_settings.get("detectionsToAlert", {"timeSpan": 0, "detections": 0})
    dta_time = int(dta.get("timeSpan", 0))
    dta_count = int(dta.get("detections", 0))
    allow_trigger = True
    if dta_time > 0 and dta_count > 0:
        now_ts = time.time()
        if radar_name not in detection_times:
            detection_times[radar_name] = []
        detection_times[radar_name] = [t for t in detection_times[radar_name] if now_ts - t <= dta_time]
        detection_times[radar_name].append(now_ts)
        if len(detection_times[radar_name]) < dta_count:
            allow_trigger = False
    if not allow_trigger:
        print(f"{datetime.now()} - Radar '{radar_display_name()}': Not enough detections ({len(detection_times[radar_name])}/{dta_count}) in {dta_time}s.")
        return
    if "state:" in cleaned:
        post_state_info = radar_settings.get("postStateInfo", False)
        if not post_state_info:
            print(f"{datetime.now()} - Radar state info for '{radar_display_name()}' ignored (postStateInfo not enabled).")
            return
    ignore = radar_settings.get("ignore", False)
    mail_setting = radar_settings.get("mail", False)
    mail_to = radar_settings.get("mail_to")
    if isinstance(ignore, str):
        if is_time_in_range(ignore):
            return 
    elif ignore:
        return
    send_mail = False
    if is_notify:
        send_mail = True
    elif isinstance(mail_setting, str):
        if is_time_in_range(mail_setting):
            send_mail = True
    elif mail_setting:
        send_mail = True
    if send_mail and mail_to:
        mail_config = load_config().get('mail', {})
        SMTP_SERVER = mail_config['smtp']['server']
        SMTP_PORT = int(mail_config['smtp']['port'])
        SMTP_USER = mail_config['smtp']['user']
        SMTP_PASSWORD = mail_config['smtp']['password']
        DEFAULT_SENDER_NAME = mail_config.get('default_sender', 'Mesh-Service')
        from email.mime.text import MIMEText
        import smtplib
        now_full = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        subject = f"Radar alert from {radar_display_name()}"
        content = f"{cleaned}\n\nRadar: {radar_display_name()}\nTime: {now_full}"
        msg = MIMEText(content)
        msg['Subject'] = subject
        msg['From'] = f"{DEFAULT_SENDER_NAME} <{SMTP_USER}>"
        msg['To'] = mail_to
        try:
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.send_message(msg)
            print(f"{datetime.now()} - Radar alert mail sent to {mail_to} (Radar: {radar_display_name()})")
        except Exception as e:
            print(f"{datetime.now()} - Error sending radar alert mail: {str(e)}")
    now = datetime.now().strftime('%H:%M:%S')
    cleaned_with_time = f"[{now}] {cleaned} (Radar: {radar_display_name()})"
    cli_path = get_meshtastic_cli_path()
    cmd = f"{cli_path} --ch-index {radar_channel} --sendtext '{cleaned_with_time}'"
    global ser
    ser_was_open = False
    try:
        try:
            if ser and ser.is_open:
                ser.close()
                ser_was_open = True
                print(f"{datetime.now()} - Serial port closed for sending (Radar).")
        except Exception:
            pass
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL)
        if result.returncode != 0 or result.stderr:
            raise Exception(result.stderr)
        print(f"{datetime.now()} - Radar message sent to channel {radar_channel}: {cleaned_with_time}")
    except Exception as e:
        print(f"{datetime.now()} - Error on first attempt to send to channel {radar_channel}: {str(e)}. Second attempt with 30s timeout...")
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
            if result.returncode != 0 or result.stderr:
                raise Exception(result.stderr)
            print(f"{datetime.now()} - Radar message sent to channel {radar_channel} on second attempt: {cleaned_with_time}")
        except Exception as e2:
            print(f"{datetime.now()} - Error on second attempt to send to channel {radar_channel}: {str(e2)}")
    time.sleep(2)
    try:
        if ser_was_open and not ser.is_open:
            ser.open()
            print(f"{datetime.now()} - Serial port reopened.")
    except Exception as e:
        print(f"{datetime.now()} - Error reopening serial port: {str(e)}")

def ignore_service(message, nodeid):
    pass

def info_service(message, nodeid):
    services_config = load_services_config()
    enabled = [name for name, active in services_config.items() if active and name in SERVICES and SERVICES[name]]
    if not enabled:
        enabled = [name for name in SERVICES if SERVICES[name]]
    enabled.sort()
    msg = "Aktivierte Services:\r" + '\r'.join([f"@{name}" for name in enabled])
    send_message_to_node(nodeid, msg)

def echo_service(message, nodeid):
    if nodeid.startswith('0x'):
        nodeid = '!' + nodeid[2:]
    msg = message.strip()
    echo_prefix = f"[ECHO/{nodeid}] "
    max_len = 200
    allowed_len = max_len - len(echo_prefix)
    if len(msg) > allowed_len:
        msg = msg[:allowed_len]
    echo_msg = echo_prefix + msg
    cli_path = get_meshtastic_cli_path()
    cmd = f"{cli_path} --ch-index 0 --sendtext '{echo_msg}'"
    global ser
    ser_was_open = False
    try:
        try:
            if ser and ser.is_open:
                ser.close()
                ser_was_open = True
                print(f"{datetime.now()} - Serial port closed for sending (Echo).")
        except Exception:
            pass
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
        if result.returncode != 0 or result.stderr:
            raise Exception(result.stderr)
        print(f"{datetime.now()} - Echo message sent to channel 0: {echo_msg}")
    except Exception as e:
        print(f"{datetime.now()} - Error sending echo message to channel 0: {str(e)}")
    time.sleep(2)
    try:
        if ser_was_open and not ser.is_open:
            ser.open()
            print(f"{datetime.now()} - Serial port reopened.")
    except Exception as e:
        print(f"{datetime.now()} - Error reopening serial port: {str(e)}")

SERVICES = {
    'mail': mail_service,
    'test': test_service,
    'wetter': weather_service,
    'google': google_service,
    'news': news_service,
    'wiki': wiki_service,
    'translate': translate_service,
    'log': None,
    'warn': warn_service,
    'radar': radar_service,
    'ignore': ignore_service,
    'echo': echo_service,
    'info': info_service,
}

def find_serial_port(port_list):
    import os
    for port in port_list:
        if os.path.exists(port):
            return port
    return None

def get_meshtastic_cli_path():
    import shutil
    cli_path = shutil.which("meshtastic")
    if cli_path:
        return cli_path
    return "meshtastic"

def send_message_to_node(nodeid, text):
    if not text or not str(text).strip():
        return
    if nodeid.startswith('0x'):
        nodeid = '!' + nodeid[2:]
    global ser
    try:
        max_len = 200
        blocks = [text[i:i+max_len] for i in range(0, len(text), max_len)]
        for idx, block in enumerate(blocks):
            print(f"{datetime.now()} - Send message to {nodeid} (Block {idx+1}/{len(blocks)}): {block}")
            ser_was_open = False
            try:
                if ser and ser.is_open:
                    ser.close()
                    ser_was_open = True
                    print(f"{datetime.now()} - Serial port closed for sending.")
            except Exception:
                pass
            cli_path = get_meshtastic_cli_path()
            cmd = f"{cli_path} --dest '{nodeid}' --sendtext '{block}'"
            try:
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
                if result.returncode != 0 or result.stderr:
                    raise Exception(result.stderr)
                print(f"{datetime.now()} - Message sent to node: {nodeid}")
            except Exception as e:
                print(f"{datetime.now()} - Error on first send attempt: {str(e)}. Second attempt with 30s timeout...")
                try:
                    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
                    if result.returncode != 0 or result.stderr:
                        raise Exception(result.stderr)
                    print(f"{datetime.now()} - Message sent to node: {nodeid} on second attempt.")
                except Exception as e2:
                    print(f"{datetime.now()} - Error on second send attempt to node {nodeid}: {str(e2)}")
            time.sleep(2)
            try:
                if ser_was_open and not ser.is_open:
                    ser.open()
                    print(f"{datetime.now()} - Serial port reopened.")
            except Exception as e:
                print(f"{datetime.now()} - Error reopening serial port: {str(e)}")
    except Exception as e:
        print(f"{datetime.now()} - Unexpected error while sending message to node {nodeid}: {str(e)}")

def is_service_enabled(servicename):
    try:
        config = load_services_config()
        if servicename == 'echo':
            return config.get('echo', True)
        return config.get(servicename, True)
    except Exception:
        return True

def main():
    # silent background fetching for @warn - but nobody asked
    warn_thread = threading.Thread(target=warn_background_loop, daemon=True)
    warn_thread.start()

    while True:
        try:
            global ser
            config = load_config()
            services = load_services_config()
            ser = None
            BAUD_RATE = 115200
            LOG_FILE = "messages.jsonl"
            log_service = config.get('log', {})
            log_enabled = log_service.get('enabled', True)
            log_api_url = log_service.get('api_url')
            log_api_key = log_service.get('api_key')
            if log_enabled and (not log_api_url or not log_api_key):
                log_enabled = False
            config_port = config['serial'].get('port')
            if isinstance(config_port, list):
                SERIAL_PORT = find_serial_port(config_port)
            else:
                SERIAL_PORT = config_port
            if not SERIAL_PORT:
                print(f"{datetime.now()} - Error: No serial port found in configuration!")
                while True:
                    time.sleep(60)
            print(f"{datetime.now()} - Serial port from configuration used: {SERIAL_PORT}")
            import os
            while True:
                while not os.path.exists(SERIAL_PORT):
                    print(f"{datetime.now()} - No device on serial {SERIAL_PORT} found.")
                    time.sleep(5)
                ser = None
                try:
                    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
                    print(f"{datetime.now()} - Serial output recognized on {SERIAL_PORT}, waiting for messages.")
                    while True:
                        try:
                            line = ser.readline().decode('utf-8', errors='ignore').strip()
                        except Exception as e:
                            print(f"{datetime.now()} - Error reading from serial port: {str(e)}")
                            break
                        if line and "Received text msg" in line:
                            msg_data = extract_text_message(line)
                            if msg_data:
                                text = msg_data['text'].lstrip()
                                nodeid = msg_data['from']
                                if text.startswith('@'):
                                    # extract possible service call name
                                    match = re.match(r"@([a-zA-Z0-9_\-]+)", text)
                                    if match:
                                        servicename = match.group(1).lower()
                                        content = text[match.end():].lstrip()
                                        print(f"{datetime.now()} - Service call detected: @{servicename} (NodeID: {nodeid}) with content: '{content}'")
                                        if servicename in SERVICES and SERVICES[servicename]:
                                            if is_service_enabled(servicename):
                                                SERVICES[servicename](content, nodeid)
                                            else:
                                                print(f"{datetime.now()} - Service @{servicename} is disabled.")
                                        else:
                                            print(f"{datetime.now()} - No service registered for @{servicename}. Ignore.")
                                    continue
                                if log_enabled:
                                    log_json_message(msg_data, LOG_FILE, log_api_url, log_api_key)
                                else:
                                    print(f"{datetime.now()} - Message received, but logging service is disabled: {msg_data}")
                except Exception as e:
                    print(f"{datetime.now()} - Error opening or reading from serial port: {str(e)}")
                finally:
                    if ser:
                        try:
                            ser.close()
                        except Exception:
                            pass
                    print(f"{datetime.now()} - Connection to {SERIAL_PORT} lost or error. Restarting monitoring.")
                    time.sleep(5)
        except Exception as fatal:
            print(f"{datetime.now()} - FATAL ERROR in main loop: {fatal}")
            time.sleep(10)

if __name__ == "__main__":
    main()

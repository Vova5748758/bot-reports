import os
import requests
import json
from pathlib import Path
from datetime import datetime, timedelta

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
MESSENGER_API = os.environ.get("MESSENGER_API", "").strip()
MESSENGER_SECRET = os.environ.get("MESSENGER_SECRET", "").strip()

STATE_FILE = Path("state.json")

if STATE_FILE.exists():
    state = json.loads(STATE_FILE.read_text())
else:
    state = {"seen": [], "offset": 0}

seen = state["seen"]
offset = state["offset"]

# ============================================================
# ПОКА ТЕСТОВЫЕ ЖАЛОБЫ. ПОТОМ ЗАМЕНИШЬ НА РЕАЛЬНЫЕ ИЗ REDFOX.
# ============================================================
reports = [
    {
        "id": 101,
        "type": "message",
        "reporter": "vasya",
        "target_user": "petya",
        "target_user_id": "12345",
        "message_text": "купи крипту",
        "message_date": "2026-09-18",
        "reason": "спам",
    },
    {
        "id": 102,
        "type": "user",
        "reporter": "kolya",
        "target_user": "petya",
        "target_user_id": "12345",
        "reason": "оскорбления",
        "user_messages": [
            {"text": "привет", "date": "2026-08-20"},
            {"text": "ты дурак", "date": "2026-09-15"},
        ],
    },
    {
        "id": 103,
        "type": "message",
        "reporter": "test3",
        "target_user": "petya",
        "target_user_id": "12345",
        "message_text": "новая жалоба для проверки третьей кнопки",
        "message_date": "2026-09-19",
        "reason": "флуд",
    },
]
# ============================================================


def format_message_report(r):
    return (
        f"🚨 <b>Новая жалоба на сообщение!</b>\n\n"
        f"👤 От: <b>{r['reporter']}</b>\n"
        f"🎯 Автор: <b>{r['target_user']}</b>\n"
        f"💬 <i>{r['message_text']}</i>\n"
        f"📅 {r.get('message_date', '?')}\n"
        f"❗ Причина: <b>{r['reason']}</b>"
    )


def format_user_report(r):
    msgs = r.get("user_messages", [])
    if msgs:
        body = "\n".join(f"  • [{m['date']}] {m['text']}" for m in msgs)
    else:
        body = "  (нет сообщений за месяц)"
    return (
        f"🚨 <b>Новая жалоба на пользователя!</b>\n\n"
        f"👤 От: <b>{r['reporter']}</b>\n"
        f"🎯 На: <b>{r['target_user']}</b>\n"
        f"❗ Причина: <b>{r['reason']}</b>\n\n"
        f"📜 <b>Последние сообщения за месяц:</b>\n{body}"
    )


# ========== 1. Отправить новые жалобы ==========
sent_ids = {s["report_id"] for s in seen if isinstance(s, dict)}

for r in reports:
    if r["id"] in sent_ids:
        continue

    text = format_message_report(r) if r["type"] == "message" else format_user_report(r)

    keyboard = {
        "inline_keyboard": [[
            {"text": "🚫 Заблокировать", "callback_data": f"ban_{r['id']}"},
            {"text": "⚠️ Предупреждение", "callback_data": f"warn_{r['id']}"},
            {"text": "🙈 Игнорировать",  "callback_data": f"ignore_{r['id']}"},
        ]]
    }

    resp = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": keyboard,
        },
    ).json()

    if resp.get("ok"):
        seen.append({
            "report_id": r["id"],
            "message_id": resp["result"]["message_id"],
            "report": r,
        })
    else:
        print("Ошибка отправки:", resp)


# ========== 2. Обработать нажатия кнопок ==========
upd_resp = requests.get(
    f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
    params={"offset": offset, "timeout": 0,
            "allowed_updates": '["callback_query"]'},
).json()

for upd in upd_resp.get("result", []):
    offset = upd["update_id"] + 1
    cq = upd.get("callback_query")
    if not cq:
        continue

    data = cq["data"]
    msg_id = cq["message"]["message_id"]
    original_text = cq["message"].get("text", "")

    if data.startswith("ban_"):
        report_id = int(data.split("_", 1)[1])
        entry = next((s for s in seen if s["report_id"] == report_id), None)
        target_id = entry["report"].get("target_user_id") if entry else None

        if MESSENGER_API and MESSENGER_API != "none" and target_id:
            try:
                headers = {}
                if MESSENGER_SECRET:
                    headers["X-Secret"] = MESSENGER_SECRET
                requests.post(
                    f"{MESSENGER_API}/delete_user",
                    json={"user_id": target_id},
                    headers=headers,
                    timeout=10,
                )
            except Exception as e:
                print(f"Ошибка удаления: {e}")

        new_text = original_text + "\n\n✅ <b>ПОЛЬЗОВАТЕЛЬ ЗАБЛОКИРОВАН</b>"

    elif data.startswith("warn_"):
        report_id = int(data.split("_", 1)[1])
        entry = next((s for s in seen if s["report_id"] == report_id), None)
        target_id = entry["report"].get("target_user_id") if entry else None

        until = (datetime.utcnow() + timedelta(days=7)).strftime("%Y-%m-%d")

        if MESSENGER_API and MESSENGER_API != "none" and target_id:
            try:
                headers = {}
                if MESSENGER_SECRET:
                    headers["X-Secret"] = MESSENGER_SECRET
                requests.post(
                    f"{MESSENGER_API}/warn_user",
                    json={"user_id": target_id, "days": 7, "until": until},
                    headers=headers,
                    timeout=10,
                )
            except Exception as e:
                print(f"Ошибка предупреждения: {e}")

        new_text = (
            f"⚠️ <b>ПРЕДУПРЕЖДЕНИЕ ВЫДАНО</b>\n"
            f"Блокировка на 7 дней, до <b>{until}</b>\n\n"
            + original_text
        )

    elif data.startswith("ignore_"):
        new_text = "🙈 <b>Проигнорировано</b>\n\n" + original_text

    else:
        continue

    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText",
        json={
            "chat_id": CHAT_ID,
            "message_id": msg_id,
            "text": new_text,
            "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": []},
        },
    )

    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery",
        json={"callback_query_id": cq["id"]},
    )


# ========== 3. Сохранить состояние ==========
state["seen"] = seen
state["offset"] = offset
STATE_FILE.write_text(json.dumps(state, ensure_ascii=False))

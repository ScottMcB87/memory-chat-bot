# app.py
# Minimal Flask Telegram bot for "Memory Chat" MVP
# - Works out-of-the-box as an echo bot
# - If OPENAI_API_KEY is set, replies in "memory-bot" style
# - Simple intake: "Nickname: ..." and "Memory: ...", then type READY to chat, END to finish
# - Safety: basic self-harm keyword trigger sends helpline message

from flask import Flask, request
import os
import requests
import json
import urllib.request

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")  # REQUIRED
OPENAI_KEY     = os.environ.get("OPENAI_API_KEY")      # OPTIONAL

INTRO = ("I am an AI memory-bot built from memories you supplied. "
         "I am not the real person.")

SAFE_MSG = (
    "I'm really sorry you're feeling this way — I'm not a human counselor, "
    "but I want to help keep you safe. If you are in immediate danger, please call 999 (UK) now. "
    "You can also contact Samaritans at 116 123 or visit https://www.samaritans.org — they're 24/7. "
    "If you're outside the UK, tell me your country and I'll try to share a local helpline. "
    "Are you alone right now?"
)

# Very simple in-memory session store (ephemeral)
# { chat_id: {"nick": str, "mems": [str, ...]} }
SESS = {}

# -------- Telegram helpers --------
def tg_send(chat_id, text):
    """Send a plain text message to a Telegram chat; log errors if any."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        r = requests.post(url, json=payload, timeout=12)
        if r.status_code != 200:
            print("sendMessage ERROR:", r.status_code, r.text)
    except Exception as e:
        print("sendMessage EXCEPTION:", repr(e))

# -------- OpenAI helper --------
def ai_reply(user_text, memories, nickname):
    """
    If OPENAI_KEY is set, generate a memory-style reply.
    Otherwise fallback to echo.
    """
    if not OPENAI_KEY:
        # Fallback: echo
        return f"You said: {user_text}"

    mem_join = "\n- " + "\n- ".join(memories) if memories else "\n- (no memories provided yet)"
    system_msg = (
        f"{INTRO}\n"
        f"Speak warmly in 2–6 sentences.\n"
        f"Use the following memories naturally if relevant:{mem_join}\n"
        f"Nickname they used for the user: {nickname or '(none)'}\n"
        "Never claim to be the real person. "
        "If asked for facts you don't have, ask the user to share a memory."
    )

    try:
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {OPENAI_KEY}"
            },
            data=json.dumps({
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_text}
                ],
                "temperature": 0.7
            }).encode("utf-8")
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            out = json.loads(resp.read().decode("utf-8"))
        reply = out["choices"][0]["message"]["content"].strip()
        # Ensure disclaimer at top
        if not reply.lower().startswith("i am an ai memory-bot"):
            reply = f"{INTRO}\n{reply}"
        return reply
    except Exception as e:
        print("OpenAI ERROR:", repr(e))
        return f"{INTRO}\n(Sorry, I had an issue generating a reply.)"

# -------- Flask routes --------
@app.route("/", methods=["GET"])
def home():
    return "Bot is live!"

@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json(force=True, silent=True) or {}
    # Log every incoming update for debugging
    print("INCOMING UPDATE:", json.dumps(update)[:4000])

    # Handle only normal messages for MVP
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return "ok"

    chat_id = msg["chat"]["id"]
    text = msg.get("text", "") or ""

    # Require token
    if not TELEGRAM_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN is not set")
        return "ok"

    # Commands / flow
    if text.startswith("/start"):
        SESS[chat_id] = {"nick": "", "mems": []}
        tg_send(chat_id,
            "Welcome to Memory Chat.\n\n"
            "This creates a one-time, private AI conversation based on brief memories you share.\n"
            "• To set a nickname they used for you, send:\n"
            "  Nickname: <what they called you>\n"
            "• To add a memory line (you can add multiple), send:\n"
            "  Memory: <one sentence memory>\n\n"
            "When you’ve added at least 1 memory, type: READY\n"
            "At any time type END to finish (we delete everything)."
        )
        return "ok"

    # End session & purge
    if text.strip().upper() == "END":
        SESS.pop(chat_id, None)
        tg_send(chat_id, "Session ended. All data deleted.")
        return "ok"

    # Safety check (basic keywords)
    lower = text.lower()
    danger_keywords = [
        "suicide", "kill myself", "end it", "can't go on", "cant go on",
        "hurt myself", "end my life", "take my life", "self harm", "self-harm"
    ]
    if any(k in lower for k in danger_keywords):
        tg_send(chat_id, SAFE_MSG)
        return "ok"

    # Intake
    state = SESS.setdefault(chat_id, {"nick": "", "mems": []})

    if text.lower().startswith("nickname:"):
        state["nick"] = text.split(":", 1)[1].strip()
        tg_send(chat_id, "Got the nickname. You can now add memories with 'Memory: ...' or type READY.")
        return "ok"

    if text.lower().startswith("memory:"):
        mem = text.split(":", 1)[1].strip()
        if mem:
            state["mems"].append(mem)
            tg_send(chat_id, f"Added memory ({len(state['mems'])}). Add more or type READY.")
        else:
            tg_send(chat_id, "Please add some text after 'Memory:'.")
        return "ok"

    if text.strip().upper() == "READY":
        if not state["mems"]:
            tg_send(chat_id, "Please add at least one memory using 'Memory: ...' first.")
            return "ok"
        tg_send(chat_id, "Okay — we can chat now. Type END when you’re finished.")
        return "ok"

    # Regular chat turn
    reply = ai_reply(text, state.get("mems", []), state.get("nick", ""))
    tg_send(chat_id, reply)
    return "ok"

# Gunicorn entrypoint
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

# Telegram Users — multi-user identity & enrollment

JARVIS recognizes who is talking on Telegram and personalizes replies.
Registry: `config/telegram_users.json`, logic: `services/telegram_users.py`,
wired into `services/telegram_gateway.py` + `scripts/telegram_watcher.py`.

## Registry format

```json
{
  "6987301428": {"name": "Sami", "role": "owner", "status": "approved"}
}
```

Keyed by Telegram **user id** (equals chat id in 1:1 chats).
Roles: `owner` (receives enrollment requests), `family` (default for
new users). Approved users have full access.

## Enrollment flow

1. Unknown user messages the bot → normally rejected, **unless** the message
   is a self-introduction: "Hi, this is Inga" / "I'm Markus".
2. JARVIS stores them as `pending`, replies "waiting for approval", and sends
   every owner an inline **✅ Approve / ❌ Deny** message
   (callback `usr:approve:<id>` — resolved directly, never through the LLM).
3. On approve, the user is welcomed and can talk to JARVIS from then on;
   `is_allowed()` accepts them alongside `JARVIS_TELEGRAM_ALLOWED_CHAT_IDS`.

## Identity injection

`telegram_watcher.py` prepends a system message to every request:

```
Telegram sender: Inga (family). Address them by name and personalize the reply.
```

so JARVIS greets each user personally without polluting the user text
(plan commands like `proceed PLAN-...` still parse unchanged).

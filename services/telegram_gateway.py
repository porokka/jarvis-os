from __future__ import annotations
import threading
import json
import os
import time
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Optional

def _load_env(env_path: Path) -> None:
        if not env_path.exists():
            return
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
class TelegramGateway:


    def __init__(
        self,
        vault_dir: Path,
        token: Optional[str] = None,
        allowed_chat_ids: Optional[set[str]] = None,
    ):
        _load_env(Path(__file__).parent.parent / ".env")
        self.vault_dir = Path(vault_dir)
        self.token = token or os.environ.get("JARVIS_TELEGRAM_BOT_TOKEN", "").strip()
        self.allowed_chat_ids = allowed_chat_ids or set(
            x.strip() for x in os.environ.get("JARVIS_TELEGRAM_ALLOWED_CHAT_IDS", "").split(",") if x.strip()
        )
        self.state_path = self.vault_dir / ".jarvis" / "telegram" / "state.json"
    def send_photo(self, chat_id: str | int, photo_path: str, caption: str = "") -> Dict[str, Any]:
        if not self.token:
            raise RuntimeError("Missing JARVIS_TELEGRAM_BOT_TOKEN")

        boundary = "----JarvisBoundary"
        path = Path(photo_path)

        if not path.exists():
            raise FileNotFoundError(str(path))

        body = bytearray()
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(b'Content-Disposition: form-data; name="chat_id"\r\n\r\n')
        body.extend(str(chat_id).encode() + b"\r\n")

        if caption:
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(b'Content-Disposition: form-data; name="caption"\r\n\r\n')
            body.extend(caption[:1000].encode("utf-8") + b"\r\n")

        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            f'Content-Disposition: form-data; name="photo"; filename="{path.name}"\r\n'.encode()
        )
        body.extend(b"Content-Type: image/png\r\n\r\n")
        body.extend(path.read_bytes())
        body.extend(f"\r\n--{boundary}--\r\n".encode())

        req = urllib.request.Request(
            self._api_url("sendPhoto"),
            data=bytes(body),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        return data
    def send_message_with_buttons(
        self,
        chat_id: str | int,
        text: str,
        buttons: list[list[dict]],
    ) -> Dict[str, Any]:
        if not self.token:
            raise RuntimeError("Missing JARVIS_TELEGRAM_BOT_TOKEN")

        payload = urllib.parse.urlencode(
            {
                "chat_id": str(chat_id),
                "text": text[:3900],
                "reply_markup": json.dumps({"inline_keyboard": buttons}),
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            self._api_url("sendMessage"),
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if not data.get("ok"):
            raise RuntimeError(f"Telegram sendMessage failed: {data}")

        return data
    def start_typing_loop(self, chat_id: str | int, stop_event: threading.Event, interval: float = 4.0) -> None:
        def _loop() -> None:
            while not stop_event.is_set():
                try:
                    self.send_chat_action(chat_id, "typing")
                except Exception:
                    pass
                stop_event.wait(interval)

        threading.Thread(target=_loop, daemon=True).start()
    def start_typing_stage(self, chat_id: str | int, stage_id: str, interval: float = 4.0) -> None:
        if not hasattr(self, "_typing_stages"):
            self._typing_stages = {}

        if stage_id in self._typing_stages:
            return

        stop_event = threading.Event()
        self._typing_stages[stage_id] = stop_event

        def _loop() -> None:
            while not stop_event.is_set():
                try:
                    self.send_chat_action(chat_id, "typing")
                except Exception:
                    pass
                stop_event.wait(interval)

        threading.Thread(target=_loop, daemon=True).start()


    def stop_typing_stage(self, stage_id: str) -> None:
        if not hasattr(self, "_typing_stages"):
            return

        stop_event = self._typing_stages.pop(stage_id, None)
        if stop_event:
            stop_event.set()
    def answer_callback_query(self, callback_query_id: str, text: str = "") -> Dict[str, Any]:
        if not self.token:
            raise RuntimeError("Missing JARVIS_TELEGRAM_BOT_TOKEN")

        payload = urllib.parse.urlencode(
            {
                "callback_query_id": callback_query_id,
                "text": text[:200],
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            self._api_url("answerCallbackQuery"),
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        return data

    def _api_url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.token}/{method}"

    def _load_state(self) -> Dict[str, Any]:
        if not self.state_path.exists():
            return {"offset": 0}
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return {"offset": 0}

    def _save_state(self, state: Dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def get_updates(self, timeout: int = 30, limit: int = 10) -> list[dict]:
        if not self.token:
            raise RuntimeError("Missing JARVIS_TELEGRAM_BOT_TOKEN")

        state = self._load_state()
        params = {
            "offset": int(state.get("offset", 0)),
            "timeout": timeout,
            "limit": limit,
            "allowed_updates": json.dumps(["message", "channel_post", "callback_query"]),
        }

        url = self._api_url("getUpdates") + "?" + urllib.parse.urlencode(params)

        with urllib.request.urlopen(url, timeout=timeout + 10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if not data.get("ok"):
            raise RuntimeError(f"Telegram getUpdates failed: {data}")

        updates = data.get("result", [])

        if updates:
            state["offset"] = max(int(u["update_id"]) for u in updates) + 1
            self._save_state(state)

        return updates
    def send_chat_action(self, chat_id: str | int, action: str = "typing") -> Dict[str, Any]:
        if not self.token:
            raise RuntimeError("Missing JARVIS_TELEGRAM_BOT_TOKEN")

        payload = urllib.parse.urlencode(
            {
                "chat_id": str(chat_id),
                "action": action,
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            self._api_url("sendChatAction"),
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if not data.get("ok"):
            raise RuntimeError(f"Telegram sendChatAction failed: {data}")

        return data
    def send_document(self, chat_id: str | int, content: bytes, filename: str, caption: str = "") -> Dict[str, Any]:
        boundary = "boundary_jarvis_doc"
        body: list[bytes] = []

        def part(name: str, value: str) -> None:
            body.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())

        part("chat_id", str(chat_id))
        if caption:
            part("caption", caption)

        body.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="{filename}"\r\n'
            f"Content-Type: application/json\r\n\r\n".encode()
        )
        body.append(content)
        body.append(f"\r\n--{boundary}--\r\n".encode())

        payload = b"".join(body)
        req = urllib.request.Request(
            self._api_url("sendDocument"),
            data=payload,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))

    # Any reply containing this marker (on its own line, dashes flexible) is
    # split and sent as SEPARATE Telegram messages. Skills and models can emit
    # "---next---" between sections to get multi-message output for free.
    _SPLIT_MARKER = re.compile(r"\s*\n\s*-{3,}\s*next\s*-{3,}\s*\n?\s*", re.IGNORECASE)
    _TELEGRAM_LIMIT = 3900

    @classmethod
    def _split_for_telegram(cls, text: str) -> list[str]:
        """Split on ---next--- markers, then chunk anything still over the
        Telegram limit at line boundaries (no more silent truncation)."""
        parts = [p.strip() for p in cls._SPLIT_MARKER.split(text) if p.strip()]

        chunks: list[str] = []
        for part in parts:
            while len(part) > cls._TELEGRAM_LIMIT:
                cut = part.rfind("\n", 0, cls._TELEGRAM_LIMIT)
                if cut < cls._TELEGRAM_LIMIT // 2:
                    cut = cls._TELEGRAM_LIMIT
                chunks.append(part[:cut].rstrip())
                part = part[cut:].lstrip()
            if part:
                chunks.append(part)
        return chunks

    def send_message(self, chat_id: str | int, text: str) -> Dict[str, Any]:
        if not self.token:
            raise RuntimeError("Missing JARVIS_TELEGRAM_BOT_TOKEN")

        data: Dict[str, Any] = {}
        pieces = self._split_for_telegram(text) or [""]
        for i, piece in enumerate(pieces):
            if i:
                time.sleep(0.3)   # keep ordering stable, stay under rate limits

            payload = urllib.parse.urlencode(
                {
                    "chat_id": str(chat_id),
                    "text": piece[: self._TELEGRAM_LIMIT],
                }
            ).encode("utf-8")

            req = urllib.request.Request(
                self._api_url("sendMessage"),
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            if not data.get("ok"):
                raise RuntimeError(f"Telegram sendMessage failed: {data}")

        return data

    def is_allowed(self, chat_id: str | int) -> bool:
        if not self.allowed_chat_ids:
            return True
        if str(chat_id) in self.allowed_chat_ids:
            return True
        # Users approved through the enrollment flow (telegram_users.py)
        try:
            from services import telegram_users
            return telegram_users.is_approved(chat_id)
        except Exception:
            return False

    def _handle_enrollment(self, chat_id, message: Dict[str, Any], text: str, emit_event=None) -> bool:
        """Self-introduction flow for unknown users. Returns True if handled."""
        try:
            from services import telegram_users
        except Exception:
            return False

        frm = message.get("from", {}) or {}
        user_id = str(frm.get("id") or chat_id)

        user = telegram_users.get_user(user_id)
        if user and user.get("status") == "pending":
            self.send_message(
                chat_id,
                f"Hi {user.get('name', '')} — still waiting for the owner's approval. "
                "I'll message you as soon as you're in.",
            )
            return True

        name = telegram_users.parse_intro(text or "")
        if not name:
            return False

        telegram_users.create_pending(user_id, name, frm.get("username", ""))
        self.send_message(
            chat_id,
            f"Nice to meet you, {name}! I've asked the owner to approve your access — "
            "I'll let you know when you're in.",
        )
        for owner_id in telegram_users.owner_chat_ids():
            try:
                self.send_message_with_buttons(
                    owner_id,
                    (
                        f"👤 New user request: {name}"
                        f" (@{frm.get('username', '') or '-'}, id {user_id})\n"
                        f"Message: {(text or '')[:200]}"
                    ),
                    [[
                        {"text": "✅ Approve", "callback_data": f"usr:approve:{user_id}"},
                        {"text": "❌ Deny", "callback_data": f"usr:deny:{user_id}"},
                    ]],
                )
            except Exception:
                pass
        if emit_event:
            emit_event(
                "telegram_enrollment",
                "New Telegram user pending approval",
                {"user_id": user_id, "name": name},
            )
        return True
    
    def send_audio(self, chat_id: str | int, wav_bytes: bytes, caption: str = "") -> Dict[str, Any]:
        """Send a WAV file as a Telegram audio message (voice note)."""
        boundary = "boundary_jarvis_audio"
        body: list[bytes] = []

        body.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{chat_id}\r\n".encode())
        if caption:
            body.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{caption[:200]}\r\n".encode())
        body.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"jarvis_reply.wav\"\r\nContent-Type: audio/wav\r\n\r\n".encode()
            + wav_bytes
            + b"\r\n"
        )
        body.append(f"--{boundary}--\r\n".encode())
        raw = b"".join(body)

        req = urllib.request.Request(
            f"https://api.telegram.org/bot{self.token}/sendAudio",
            data=raw,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _tts_wav(self, text: str, port: int = 5100) -> Optional[bytes]:
        """Call local Kokoro TTS. The server returns JSON with base64 PCM chunks —
        decode them and wrap in a WAV header. Returns WAV bytes or None."""
        import base64 as _b64
        import io
        import wave
        try:
            payload = json.dumps({"text": text, "voice": "af_heart", "speed": 1.0}).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/tts/speak",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())

            if data.get("status") != "ok":
                print(f"[TELEGRAM] Kokoro error: {data.get('error')}", flush=True)
                return None

            chunks = data.get("chunks", [])
            pcm = b"".join(
                _b64.b64decode(c["audio"]) for c in chunks if c.get("audio")
            )
            if not pcm:
                return None

            sample_rate = int(data.get("sample_rate", 24000))
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(pcm)
            return buf.getvalue()
        except Exception as e:
            print(f"[TELEGRAM] TTS failed: {e}", flush=True)
            return None

    def _handle_mobile_packet(
        self,
        raw_text: str,
        chat_id: str | int,
        handle_message: Callable[[str, Dict[str, Any]], str],
        update: Dict[str, Any],
        emit_event: Optional[Callable] = None,
    ) -> None:
        """Parse JARVIS_MOBILE packet, get reply from handle_message, respond with text + TTS audio."""
        try:
            packet = json.loads(raw_text[len("JARVIS_MOBILE "):])
        except Exception:
            return

        pkt_type = packet.get("type", "query")

        # TTS-only request: mobile local model replied, wants Kokoro voice
        if pkt_type == "tts":
            tts_text = packet.get("text", "").strip()
            if tts_text:
                wav = self._tts_wav(tts_text)
                if wav:
                    self.send_audio(chat_id, wav)
                    print(f"[TELEGRAM] TTS sent ({len(wav)} bytes)", flush=True)
                else:
                    print("[TELEGRAM] TTS requested but Kokoro unavailable", flush=True)
            return

        user_text = packet.get("text", "").strip()
        input_type = packet.get("input", "text")   # voice | text | image
        model_state = packet.get("model", "offline")  # offline | online | routed

        if not user_text:
            return

        if emit_event:
            emit_event("telegram_in", "Mobile query received",
                       {"chat_id": chat_id, "input": input_type, "model": model_state, "text": user_text[:200]})

        # Route through normal handle_message (Claude / skills / etc.)
        reply_text = handle_message(user_text, update)
        if not reply_text:
            return

        # Generate TTS first so the reply packet can carry an audio flag.
        # audio=true → mobile shows the text but does NOT speak it (the wav
        # that follows is the voice). audio=false → mobile speaks the text
        # itself. This is what prevents every answer speaking twice.
        wav = self._tts_wav(reply_text)
        reply_packet = json.dumps({
            "type": "reply",
            "text": reply_text,
            "audio": bool(wav),
        })
        self.send_message(chat_id, f"JARVIS_REPLY {reply_packet}")
        if wav:
            self.send_audio(chat_id, wav)

    def _describe_image(self, image_b64: str, question: str = "") -> str:
        """Describe a photo with the llama.cpp vision server (gemma + mmproj).
        Returns "" when the vision server is unavailable."""
        llama = os.environ.get("LLAMA_CPP_HOST", "http://127.0.0.1:8091").rstrip("/")
        focus = f" The user asked: {question}. Focus on what is relevant to that." if question else ""
        payload = json.dumps({
            "model": "gemma",
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                    {"type": "text",
                     "text": f"Describe what you see in this photo, concretely and concisely.{focus}"},
                ],
            }],
            "temperature": 0.2,
            "stream": False,
        }).encode("utf-8")
        try:
            req = urllib.request.Request(
                f"{llama}/v1/chat/completions",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
        except Exception as e:
            print(f"[TELEGRAM] vision describe failed: {e}", flush=True)
            return ""

    def _handle_photo(
        self,
        msg: Dict[str, Any],
        chat_id: str | int,
        handle_message: Callable[[str, Dict[str, Any]], str],
        update: Dict[str, Any],
        emit_event: Optional[Callable] = None,
    ) -> None:
        """Incoming photo (mobile camera frame or a photo sent in chat).
        Vision-describe it, then route question+description through the
        normal pipeline. Mobile packets get the JARVIS_REPLY audio contract."""
        photos = msg.get("photo") or []
        if not photos:
            return
        file_id = photos[-1]["file_id"]   # last entry = largest resolution
        caption = msg.get("caption", "") or ""

        packet = None
        if caption.startswith("JARVIS_PHOTO "):
            try:
                packet = json.loads(caption[len("JARVIS_PHOTO "):])
            except Exception:
                packet = None

        user_text = (packet or {}).get("text", "").strip()
        if not user_text and not caption.startswith("JARVIS_"):
            user_text = caption.strip()
        if not user_text:
            user_text = "What do you see in this image?"

        if emit_event:
            emit_event("telegram_in", "Photo received",
                       {"chat_id": chat_id, "text": user_text[:150], "mobile": packet is not None})

        # Download the photo bytes
        import base64 as _b64
        try:
            info_url = self._api_url("getFile") + f"?file_id={file_id}"
            with urllib.request.urlopen(info_url, timeout=15) as resp:
                file_path = json.loads(resp.read())["result"]["file_path"]
            photo_url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"
            with urllib.request.urlopen(photo_url, timeout=60) as resp:
                image_b64 = _b64.b64encode(resp.read()).decode()
        except Exception as e:
            print(f"[TELEGRAM] photo download failed: {e}", flush=True)
            return

        # Receipt capture: only attempted when the caption/text signals a
        # receipt (see looks_like_receipt_request) — everything else falls
        # through to the existing generic describe+chat behavior unchanged.
        # Wrapped defensively so any failure here never breaks normal photo
        # handling.
        try:
            from skills.raamat_receipt_capture import try_capture_receipt
            receipt_reply = try_capture_receipt(image_b64, user_text)
        except Exception as e:
            print(f"[TELEGRAM] receipt capture attempt failed: {e}", flush=True)
            receipt_reply = None
        if receipt_reply:
            if emit_event:
                emit_event("telegram_in", "Receipt captured", {"chat_id": chat_id})
            if packet is not None:
                wav = self._tts_wav(receipt_reply)
                self.send_message(chat_id, "JARVIS_REPLY " + json.dumps({
                    "type": "reply", "text": receipt_reply, "audio": bool(wav),
                }))
                if wav:
                    self.send_audio(chat_id, wav)
            else:
                self.send_message(chat_id, receipt_reply)
            return

        description = self._describe_image(image_b64, user_text)
        if not description:
            self.send_message(chat_id, "I received the photo but the vision server is unavailable right now.")
            return

        prompt = f"{user_text}\n\n[The user's camera image shows: {description}]"
        reply_text = handle_message(prompt, update)
        if not reply_text:
            return

        if packet is not None:
            # Mobile contract: audio flag + optional wav (see _handle_mobile_packet)
            wav = self._tts_wav(reply_text)
            self.send_message(chat_id, "JARVIS_REPLY " + json.dumps({
                "type": "reply", "text": reply_text, "audio": bool(wav),
            }))
            if wav:
                self.send_audio(chat_id, wav)
        else:
            self.send_message(chat_id, reply_text)

    def _handle_mobile_voice(
        self,
        file_id: str,
        caption: str,
        chat_id: str | int,
        handle_message: Callable[[str, Dict[str, Any]], str],
        update: Dict[str, Any],
        emit_event: Optional[Callable] = None,
    ) -> None:
        """Download voice from Telegram, transcribe with local Whisper.
        JARVIS_VOICE_TRANSCRIBE → send transcript back (mobile routes locally).
        JARVIS_VOICE_QUERY      → full reply + TTS audio."""
        import base64 as _b64
        transcribe_only = "JARVIS_VOICE_TRANSCRIBE" in caption
        try:
            # Resolve Telegram file path
            url = self._api_url("getFile") + f"?file_id={file_id}"
            with urllib.request.urlopen(url, timeout=10) as resp:
                file_info = json.loads(resp.read())
            file_path = file_info["result"]["file_path"]

            # Download audio bytes
            audio_url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"
            with urllib.request.urlopen(audio_url, timeout=30) as resp:
                audio_bytes = resp.read()

            # Transcribe via local Whisper at :7900
            audio_b64 = _b64.b64encode(audio_bytes).decode()
            payload = json.dumps({"audio": audio_b64}).encode()
            req = urllib.request.Request(
                "http://127.0.0.1:7900/transcribe",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
            transcript = result.get("text", "").strip()

            print(f"[TELEGRAM] voice transcript ({('transcribe_only' if transcribe_only else 'full')}): {transcript[:100]!r}", flush=True)

            if not transcript:
                self.send_message(chat_id, "JARVIS_REPLY " + json.dumps({"type": "reply", "text": "[no speech detected]"}))
                return

            if emit_event:
                emit_event("telegram_in", "Mobile voice", {"chat_id": chat_id, "mode": "transcribe" if transcribe_only else "full", "text": transcript[:200]})

            if transcribe_only:
                # Mobile has local model — just return the transcript
                self.send_message(chat_id, "JARVIS_TRANSCRIPT " + json.dumps({"text": transcript}))
                return

            # Full handling: route through Claude. Same audio-flag contract
            # as _handle_mobile_packet: wav attached → mobile shows text
            # silently and plays the wav; no wav → mobile speaks the text.
            reply_text = handle_message(transcript, update)
            if not reply_text:
                return
            wav = self._tts_wav(reply_text)
            self.send_message(chat_id, "JARVIS_REPLY " + json.dumps({
                "type": "reply",
                "text": reply_text,
                "audio": bool(wav),
            }))
            if wav:
                self.send_audio(chat_id, wav)

        except Exception as e:
            print(f"[TELEGRAM] voice handling error: {e}", flush=True)
            if emit_event:
                emit_event("telegram_error", "Voice handling error", {"error": str(e)})

    def _send_skills_export(self, chat_id: str | int) -> None:
        try:
            from skills.loader import get_all_skill_meta, get_loaded_skills
        except ImportError:
            self.send_message(chat_id, "⚠️ Skills not loaded yet.")
            return

        skill_meta = get_all_skill_meta()
        loaded = get_loaded_skills()

        # Build a skill-name → module description lookup
        skill_desc: Dict[str, str] = {}
        for s in loaded:
            for tool_name in s.get("tools", []):
                skill_desc[tool_name] = s.get("description", "")

        export: list[Dict[str, Any]] = []
        for tool_name, meta in skill_meta.items():
            tool_desc = meta.get("description", "") or skill_desc.get(tool_name, tool_name)
            # Route skills tell Gemma4 on mobile to dispatch to the desktop
            prompt = (
                f"When user asks about {tool_desc or tool_name}, reply with exactly "
                f"'ROUTE: {tool_name}' on the first line followed by any relevant details. "
                f"This dispatches the request to main Jarvis which will execute it."
            )
            export.append({
                "name": tool_name,
                "description": tool_desc or tool_name,
                "prompt": prompt,
                "source": "jarvis-desktop",
            })

        if not export:
            self.send_message(chat_id, "No skills loaded.")
            return

        payload = json.dumps(export, ensure_ascii=False, indent=2).encode("utf-8")
        try:
            self.send_document(chat_id, payload, "jarvis_skills.json", f"📦 {len(export)} skills from Jarvis desktop")
        except Exception as e:
            self.send_message(chat_id, f"⚠️ Failed to send skills: {e}")

    def poll_forever(
        self,
        handle_message: Callable[[str, Dict[str, Any]], str],
        emit_event: Optional[Callable[[str, str, Optional[Dict[str, Any]]], None]] = None,
        sleep_on_error: int = 5,
    ) -> None:
        while True:
            try:
                updates = self.get_updates(timeout=30, limit=10)

                for update in updates:
                    callback = update.get("callback_query")

                    if callback:
                        callback_id = callback.get("id")
                        message = callback.get("message") or {}
                        chat = message.get("chat") or {}
                        chat_id = chat.get("id")
                        data = callback.get("data", "")

                        if callback_id:
                            self.answer_callback_query(callback_id, "Received")

                        if emit_event:
                            emit_event(
                                "telegram_callback",
                                "Telegram button pressed",
                                {"chat_id": chat_id, "data": data},
                            )

                        # Action-queue buttons (apq:approve/confirm/deny <id>)
                        # resolve directly — they must not go through the LLM
                        if chat_id and data.startswith("apq:"):
                            try:
                                import sys as _sys
                                _scripts = str(Path(__file__).parent.parent / "scripts")
                                if _scripts not in _sys.path:
                                    _sys.path.insert(0, _scripts)
                                from action_queue import resolve as _apq_resolve
                                parts = data[4:].split()
                                verdict = parts[0] if parts else ""
                                pid = parts[1] if len(parts) > 1 else ""
                                reply = _apq_resolve(pid, verdict)
                            except Exception as e:
                                reply = f"Proposal handling failed: {e}"
                            if reply:
                                self.send_message(chat_id, reply)
                            continue

                        # User enrollment buttons (usr:approve:<id> / usr:deny:<id>)
                        # resolve directly — they must not go through the LLM
                        if chat_id and data.startswith("usr:"):
                            try:
                                from services import telegram_users
                                _, verdict, uid = data.split(":", 2)
                                reply = telegram_users.resolve_pending(uid, verdict)
                                if verdict == "approve":
                                    user = telegram_users.get_user(uid)
                                    self.send_message(
                                        uid,
                                        f"Welcome {user.get('name', '') if user else ''}! "
                                        "You now have access to JARVIS — just talk to me.",
                                    )
                                elif verdict == "deny":
                                    self.send_message(uid, "Access request was declined.")
                            except Exception as e:
                                reply = f"User approval handling failed: {e}"
                            if reply:
                                self.send_message(chat_id, reply)
                            continue

                        if chat_id and data:
                            reply = handle_message(data, update)
                            if reply:
                                self.send_message(chat_id, reply)

                        continue

                    # channel_post: bot-to-bot messaging only works via channels
                    # (Telegram never delivers group messages between bots)
                    message = update.get("message") or update.get("channel_post") or {}
                    chat = message.get("chat") or {}
                    chat_id = chat.get("id")
                    text = message.get("text", "")

                    if not chat_id:
                        continue

                    # Handle voice/audio messages from mobile (JARVIS_VOICE_QUERY)
                    voice_obj = message.get("voice") or message.get("audio")
                    if voice_obj and not text:
                        if self.is_allowed(chat_id):
                            caption = message.get("caption", "")
                            self._handle_mobile_voice(voice_obj["file_id"], caption, chat_id, handle_message, update, emit_event)
                        continue

                    # Photos: mobile camera frames (JARVIS_PHOTO caption) or
                    # photos sent directly in chat — vision-described + routed
                    if message.get("photo") and not text:
                        if self.is_allowed(chat_id):
                            self._handle_photo(message, chat_id, handle_message, update, emit_event)
                        continue

                    if not text:
                        continue

                    print(f"[TELEGRAM] chat_id={chat_id} text={text!r}", flush=True)

                    if not self.is_allowed(chat_id):
                        if self._handle_enrollment(chat_id, message, text, emit_event):
                            continue
                        self.send_message(
                            chat_id,
                            "This chat is not allowed to use this JARVIS bot. "
                            "If you know the owner, introduce yourself: \"Hi, this is <your name>\".",
                        )
                        username = message.get("from", {}).get("username", "")
                        first_name = message.get("from", {}).get("first_name", "")
                        alert = (
                            f"⚠️ Unauthorized access attempt\n"
                            f"chat_id: {chat_id}\n"
                            f"user: {first_name} (@{username})\n"
                            f"message: {text[:200]}"
                        )
                        for allowed_id in self.allowed_chat_ids:
                            try:
                                self.send_message(allowed_id, alert)
                            except Exception:
                                pass
                        if emit_event:
                            emit_event(
                                "telegram_unauthorized",
                                "Unauthorized Telegram access attempt",
                                {"chat_id": chat_id, "text": text[:200], "username": username},
                            )
                        print(f"[TELEGRAM] UNAUTHORIZED chat_id={chat_id} username={username} text={text[:100]!r}", flush=True)
                        continue

                    if text.strip().lower() in ("/skills", "/skills@jarvisbot"):
                        self._send_skills_export(chat_id)
                        continue

                    # Structured mobile packet — handle separately with TTS response
                    if text.startswith("JARVIS_MOBILE "):
                        self._handle_mobile_packet(text, chat_id, handle_message, update, emit_event)
                        continue

                    if emit_event:
                        emit_event(
                            "telegram_in",
                            "Telegram message received",
                            {"chat_id": chat_id, "text": text[:500]},
                        )

                    reply = handle_message(text, update)

                    if not reply:
                        continue

                    lower = reply.lower()
                    plan_match = re.search(r"PLAN_ID:\s*([A-Za-z0-9_-]+)", reply)

                    # render_plan() ends with "Reply:  proceed | modify | cancel"
                    # (it never emits "waiting_for:") — match both formats so
                    # the Proceed/Modify/Cancel buttons actually appear.
                    if plan_match and ("waiting_for" in lower or "proceed" in lower):
                        plan_id = plan_match.group(1)

                        self.send_message_with_buttons(
                            chat_id,
                            reply,
                            [
                                [
                                    {"text": "✅ Proceed", "callback_data": f"proceed {plan_id}"},
                                    {"text": "✏️ Modify", "callback_data": f"modify {plan_id}"},
                                ],
                                [
                                    {"text": "❌ Cancel", "callback_data": f"cancel {plan_id}"},
                                ],
                            ],
                        )
                    else:
                        self.send_message(chat_id, reply)

            except Exception as e:
                if emit_event:
                    emit_event("telegram_error", "Telegram polling error", {"error": str(e)})
                time.sleep(sleep_on_error)
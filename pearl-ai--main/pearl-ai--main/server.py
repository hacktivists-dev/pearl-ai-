import asyncio
import base64
import json
import os
import socket
from typing import Callable, List, Optional, Tuple
from urllib.parse import urlparse

import requests
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

try:
    from groq import AsyncGroq
except ImportError:
    AsyncGroq = None


app = FastAPI(title="PearlAI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
FRONTEND_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "Frontend"))
USERS_FILE = os.path.join(BASE_DIR, "users.json")
API_TIMEOUT = int(os.getenv("API_TIMEOUT_SECONDS", "30"))


def env_value(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


DEBUG_PROVIDERS = env_value("DEBUG_PROVIDERS", "false").lower() in {"1", "true", "yes"}


def looks_like_xai_key(api_key: str) -> bool:
    return api_key.startswith("xai")


def normalized_xai_key(api_key: str) -> str:
    if api_key.startswith("xai-"):
        return api_key
    if api_key.startswith("xai") and len(api_key) > 3:
        return f"xai-{api_key[3:]}"
    return api_key


def looks_like_openrouter_key(api_key: str) -> bool:
    return api_key.startswith("sk-or-")


def looks_like_openai_key(api_key: str) -> bool:
    return api_key.startswith("sk-") and not looks_like_openrouter_key(api_key)


def looks_like_gemini_key(api_key: str) -> bool:
    return api_key.startswith("AIza")


GROQ_API_KEY = env_value("GROQ_API_KEY", "xai-kdp4sdpwmc8BstboQ8wYreSgMabB0xqkINASWOGTlnrEaAlJe6jpw3MtRsfZwbWIx1jHeuv3iJP3AHWp")
GEMINI_API_KEY = env_value("GEMINI_API_KEY", "AQ.Ab8RN6JjkQGeLY6CYIWBljJBEHctcDh8d26xO3uHydenh95T-g")
MISTRAL_API_KEY = env_value("MISTRAL_API_KEY", "XcobP6L8MxG63Vm1uY4UP890jao91PQd")
OPENROUTER_API_KEY = env_value("OPENROUTER_API_KEY", "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")
VIRUSTOTAL_API_KEY = env_value("VIRUSTOTAL_API_KEY", "20a8bf5c6f517dc60a606284801da45879e23d4d6fc34be93dcbc2c26859389e")
SHODAN_API_KEY = env_value("SHODAN_API_KEY", "ZvPxyzETzay03HCnika6PMNj5he5gXb4")
XAI_API_KEY = env_value("XAI_API_KEY", normalized_xai_key(GROQ_API_KEY) if looks_like_xai_key(GROQ_API_KEY) else "")
OPENAI_API_KEY = env_value("OPENAI_API_KEY", OPENROUTER_API_KEY if looks_like_openai_key(OPENROUTER_API_KEY) else "")

GROQ_TEXT_MODEL = env_value("GROQ_TEXT_MODEL", "llama-3.3-70b-versatile")
GROQ_VISION_MODEL = env_value("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
GEMINI_TEXT_MODEL = env_value("GEMINI_TEXT_MODEL", "gemini-3.5-flash")
GEMINI_VISION_MODEL = env_value("GEMINI_VISION_MODEL", GEMINI_TEXT_MODEL)
MISTRAL_TEXT_MODEL = env_value("MISTRAL_TEXT_MODEL", "mistral-small-latest")
MISTRAL_VISION_MODEL = env_value("MISTRAL_VISION_MODEL", MISTRAL_TEXT_MODEL)
OPENROUTER_TEXT_MODEL = env_value("OPENROUTER_TEXT_MODEL", "openrouter/free")
OPENROUTER_VISION_MODEL = env_value("OPENROUTER_VISION_MODEL", OPENROUTER_TEXT_MODEL)
XAI_TEXT_MODEL = env_value("XAI_TEXT_MODEL", "grok-4.3")
XAI_VISION_MODEL = env_value("XAI_VISION_MODEL", XAI_TEXT_MODEL)
OPENAI_TEXT_MODEL = env_value("OPENAI_TEXT_MODEL", "gpt-5.4-mini")
OPENAI_VISION_MODEL = env_value("OPENAI_VISION_MODEL", OPENAI_TEXT_MODEL)

groq_client = AsyncGroq(api_key=GROQ_API_KEY) if AsyncGroq and GROQ_API_KEY and not looks_like_xai_key(GROQ_API_KEY) else None


def can_use_xai() -> bool:
    return bool(XAI_API_KEY and XAI_API_KEY.startswith("xai-"))


def can_use_groq() -> bool:
    return bool(GROQ_API_KEY and AsyncGroq and groq_client and not looks_like_xai_key(GROQ_API_KEY))


def can_use_gemini() -> bool:
    return bool(GEMINI_API_KEY and looks_like_gemini_key(GEMINI_API_KEY))


def can_use_mistral() -> bool:
    return bool(MISTRAL_API_KEY)


def can_use_openai() -> bool:
    return bool(OPENAI_API_KEY and looks_like_openai_key(OPENAI_API_KEY))


def can_use_openrouter() -> bool:
    return bool(OPENROUTER_API_KEY and looks_like_openrouter_key(OPENROUTER_API_KEY))


class ProviderError(RuntimeError):
    pass


def require_key(provider: str, api_key: str) -> None:
    if not api_key:
        raise ProviderError(f"{provider} API key is not configured")


def require_groq() -> None:
    require_key("Groq", GROQ_API_KEY)
    if looks_like_xai_key(GROQ_API_KEY):
        raise ProviderError("GROQ_API_KEY is an xAI key, so the xAI provider will use it instead")
    if AsyncGroq is None:
        raise ProviderError("Groq package is not installed")
    if groq_client is None:
        raise ProviderError("Groq client is not available")


def response_error_message(response: requests.Response) -> str:
    message = response.text.strip()
    try:
        error_json = response.json()
    except ValueError:
        return message

    if isinstance(error_json, dict):
        error_value = error_json.get("error")
        if isinstance(error_value, dict):
            return str(error_value.get("message") or error_value.get("type") or message)
        if isinstance(error_value, str):
            return error_value

        detail_value = error_json.get("detail")
        if isinstance(detail_value, str):
            return detail_value
        if isinstance(detail_value, list):
            return json.dumps(detail_value)

        message_value = error_json.get("message")
        if isinstance(message_value, str):
            return message_value

    return message


def request_json(provider: str, method: str, url: str, **kwargs) -> dict:
    try:
        response = requests.request(method, url, timeout=API_TIMEOUT, **kwargs)
    except requests.RequestException as exc:
        raise ProviderError(f"{provider} request failed: {exc}") from exc

    if response.status_code >= 400:
        message = response_error_message(response)
        raise ProviderError(f"{provider} returned HTTP {response.status_code}: {message[:300]}")

    try:
        return response.json()
    except ValueError as exc:
        raise ProviderError(f"{provider} returned invalid JSON") from exc


def unique_values(values: List[str]) -> List[str]:
    seen = set()
    result = []
    for value in values:
        value = (value or "").strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def model_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(
        marker in text
        for marker in (
            "model",
            "not found",
            "not available",
            "does not exist",
            "unsupported",
            "deprecat",
        )
    )


def extract_chat_completion_text(provider: str, data: dict) -> str:
    choices = data.get("choices") or []
    if not choices:
        raise ProviderError(f"{provider} returned no choices")

    content = (choices[0].get("message") or {}).get("content")
    if isinstance(content, list):
        content = "\n".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    if not isinstance(content, str) or not content.strip():
        raise ProviderError(f"{provider} returned an empty message")
    return content.strip()


def extract_gemini_text(data: dict) -> str:
    candidates = data.get("candidates") or []
    if not candidates:
        raise ProviderError("Gemini returned no candidates")

    parts = ((candidates[0].get("content") or {}).get("parts")) or []
    text = "\n".join(part.get("text", "") for part in parts if isinstance(part, dict))
    if not text.strip():
        finish_reason = candidates[0].get("finishReason", "unknown")
        raise ProviderError(f"Gemini returned an empty response, finish reason: {finish_reason}")
    return text.strip()


def load_users() -> dict:
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            print(f"Warning: error loading users.json: {exc}")
    return {"user@example.com": {"password": "pearl123", "name": "Admin"}}


def save_users(users: dict) -> None:
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=4)


class LoginInput(BaseModel):
    name: Optional[str] = None
    email: str
    password: str


class Message(BaseModel):
    role: str
    content: str


class ChatInput(BaseModel):
    message: str = ""
    history: List[Message] = Field(default_factory=list)
    image: Optional[str] = None


MOCK_USERS_DB = load_users()


def scan_virustotal(target: str) -> str:
    if not VIRUSTOTAL_API_KEY:
        return "VirusTotal API key is not configured. Set VIRUSTOTAL_API_KEY and restart the server."
    target = target.strip()
    if not target:
        return "Please provide a URL, domain, IP address, or file hash to scan."

    headers = {"x-apikey": VIRUSTOTAL_API_KEY}
    try:
        if target.startswith(("http://", "https://")):
            url_id = base64.urlsafe_b64encode(target.encode("utf-8")).decode("ascii").strip("=")
            endpoint = f"https://www.virustotal.com/api/v3/urls/{url_id}"
            data = request_json("VirusTotal", "GET", endpoint, headers=headers)
            stats = (data.get("data") or {}).get("attributes", {}).get("last_analysis_stats", {})
        else:
            endpoint = "https://www.virustotal.com/api/v3/search"
            data = request_json("VirusTotal", "GET", endpoint, headers=headers, params={"query": target})
            results = data.get("data") or []
            stats = results[0].get("attributes", {}).get("last_analysis_stats", {}) if results else {}
    except ProviderError as exc:
        if "HTTP 404" in str(exc):
            return f"No scan history was found for `{target}`."
        return f"VirusTotal API error: {exc}"

    if not stats:
        return f"No scan history or threat stats were found for `{target}`."

    malicious = stats.get("malicious", 0)
    suspicious = stats.get("suspicious", 0)
    harmless = stats.get("harmless", 0)

    result = f"**VirusTotal Scan Report for `{target}`:**\n\n"
    if malicious > 0:
        return result + f"**Alert:** {malicious} engines flagged this as malicious."
    if suspicious > 0:
        return result + f"**Warning:** {suspicious} engines flagged this as suspicious."
    return result + f"**Clean:** No engines detected threats. Harmless count: {harmless}."


def scan_shodan(target: str) -> str:
    if not SHODAN_API_KEY:
        return "Shodan API key is not configured. Set SHODAN_API_KEY and restart the server."
    target = target.strip()
    if not target:
        return "Please provide a domain or IP address to scan."

    try:
        clean_target = urlparse(target).netloc if target.startswith(("http://", "https://")) else target
        clean_target = clean_target.split("/")[0]
        ip_address = socket.gethostbyname(clean_target)
    except socket.gaierror:
        return f"Could not resolve `{target}` to an IP address."

    endpoint = f"https://api.shodan.io/shodan/host/{ip_address}"
    try:
        data = request_json("Shodan", "GET", endpoint, params={"key": SHODAN_API_KEY})
    except ProviderError as exc:
        if "HTTP 404" in str(exc):
            return f"No info was found in Shodan for `{clean_target}` (IP: {ip_address})."
        return f"Shodan API error: {exc}"

    org = data.get("org") or "Unknown"
    os_info = data.get("os") or "Unknown"
    ports = data.get("ports") or []
    vulns = data.get("vulns") or []
    result = (
        f"**Shodan Report for `{clean_target}` (IP: {ip_address}):**\n\n"
        f"**Org:** {org}\n"
        f"**OS:** {os_info}\n"
        f"**Ports:** {', '.join(map(str, ports)) if ports else 'None'}\n"
    )
    if vulns:
        result += f"\n**CVEs Detected:** {len(vulns)}\n" + ", ".join(list(vulns)[:5])
    else:
        result += "\nNo known vulnerabilities were returned by Shodan."
    return result


def call_openai_compatible_chat(
    provider: str,
    api_key: str,
    endpoint: str,
    models: List[str],
    messages: List[dict],
    token_field: str = "max_tokens",
    extra_headers: Optional[dict] = None,
) -> str:
    require_key(provider, api_key)
    errors = []

    for model in unique_values(models):
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if extra_headers:
            headers.update(extra_headers)

        body = {
            "model": model,
            "messages": messages,
            token_field: 1024,
        }
        try:
            data = request_json(provider, "POST", endpoint, headers=headers, json=body)
            return extract_chat_completion_text(provider, data)
        except ProviderError as exc:
            errors.append(f"{model}: {exc}")
            if not model_error(exc):
                break

    raise ProviderError("; ".join(errors))


async def call_groq_text(messages: List[dict]) -> str:
    require_groq()
    completion = await groq_client.chat.completions.create(
        model=GROQ_TEXT_MODEL,
        messages=messages,
        temperature=0.7,
        max_tokens=1024,
    )
    content = completion.choices[0].message.content
    if not content:
        raise ProviderError("Groq returned an empty response")
    return content


def call_xai_text(messages: List[dict]) -> str:
    return call_openai_compatible_chat(
        "xAI",
        XAI_API_KEY,
        "https://api.x.ai/v1/chat/completions",
        [XAI_TEXT_MODEL, "grok-4.3", "latest"],
        messages,
    )


def call_openai_text(messages: List[dict]) -> str:
    return call_openai_compatible_chat(
        "OpenAI",
        OPENAI_API_KEY,
        "https://api.openai.com/v1/chat/completions",
        [OPENAI_TEXT_MODEL, "gpt-5.4-mini", "gpt-5.5", "gpt-4.1-mini", "gpt-4o-mini"],
        messages,
        token_field="max_completion_tokens",
    )


def gemini_contents(messages: List[dict], img: Optional[str] = None) -> Tuple[Optional[str], List[dict]]:
    system_instruction = None
    contents = []

    for index, msg in enumerate(messages):
        role = msg.get("role", "user")
        content = msg.get("content") or ""
        if role == "system":
            system_instruction = content
            continue

        parts = [{"text": content or "Analyze the image."}]
        if img and index == len(messages) - 1:
            b64_data = img.split(",", 1)[1] if "," in img else img
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b64_data}})

        contents.append(
            {
                "role": "model" if role == "assistant" else "user",
                "parts": parts,
            }
        )

    return system_instruction, contents


def call_gemini_text(messages: List[dict]) -> str:
    require_key("Gemini", GEMINI_API_KEY)
    system_instruction, contents = gemini_contents(messages)
    payload = {"contents": contents}
    if system_instruction:
        payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

    errors = []
    for model in unique_values([GEMINI_TEXT_MODEL, "gemini-3.5-flash", "gemini-2.5-flash", "gemini-2.5-flash-lite"]):
        try:
            data = request_json(
                "Gemini",
                "POST",
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"},
                json=payload,
            )
            return extract_gemini_text(data)
        except ProviderError as exc:
            errors.append(f"{model}: {exc}")
            if not model_error(exc):
                break
    raise ProviderError("; ".join(errors))


def call_mistral_text(messages: List[dict]) -> str:
    require_key("Mistral", MISTRAL_API_KEY)
    errors = []
    for model in unique_values([MISTRAL_TEXT_MODEL, "mistral-small-latest", "mistral-medium-latest"]):
        try:
            data = request_json(
                "Mistral",
                "POST",
                "https://api.mistral.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json"},
                json={"model": model, "messages": messages, "max_tokens": 1024},
            )
            return extract_chat_completion_text("Mistral", data)
        except ProviderError as exc:
            errors.append(f"{model}: {exc}")
            if not model_error(exc):
                break
    raise ProviderError("; ".join(errors))


def call_openrouter_text(messages: List[dict]) -> str:
    require_key("OpenRouter", OPENROUTER_API_KEY)
    if looks_like_openai_key(OPENROUTER_API_KEY):
        raise ProviderError("OPENROUTER_API_KEY is an OpenAI key, so the OpenAI provider will use it instead")
    data = request_json(
        "OpenRouter",
        "POST",
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8000",
            "X-OpenRouter-Title": "PearlAI",
            "X-Title": "PearlAI",
        },
        json={"model": OPENROUTER_TEXT_MODEL, "messages": messages, "max_tokens": 1024},
    )
    return extract_chat_completion_text("OpenRouter", data)


async def call_groq_vision(messages: List[dict], img: str) -> str:
    require_groq()
    formatted = openai_vision_messages(messages, img)
    completion = await groq_client.chat.completions.create(
        model=GROQ_VISION_MODEL,
        messages=formatted,
        max_tokens=1024,
    )
    content = completion.choices[0].message.content
    if not content:
        raise ProviderError("Groq vision returned an empty response")
    return content


def openai_vision_messages(messages: List[dict], img: str) -> List[dict]:
    formatted = []
    image_url = img if img.startswith("data:image") else f"data:image/jpeg;base64,{img}"

    for index, msg in enumerate(messages):
        if msg.get("role") == "system":
            continue
        content = [{"type": "text", "text": msg.get("content") or "Analyze the image."}]
        if index == len(messages) - 1:
            content.append({"type": "image_url", "image_url": {"url": image_url}})
        formatted.append({"role": msg.get("role", "user"), "content": content})
    return formatted


def call_xai_vision(messages: List[dict], img: str) -> str:
    return call_openai_compatible_chat(
        "xAI",
        XAI_API_KEY,
        "https://api.x.ai/v1/chat/completions",
        [XAI_VISION_MODEL, "grok-4.3", "latest"],
        openai_vision_messages(messages, img),
    )


def call_openai_vision(messages: List[dict], img: str) -> str:
    return call_openai_compatible_chat(
        "OpenAI",
        OPENAI_API_KEY,
        "https://api.openai.com/v1/chat/completions",
        [OPENAI_VISION_MODEL, "gpt-5.4-mini", "gpt-5.5", "gpt-4.1-mini", "gpt-4o-mini"],
        openai_vision_messages(messages, img),
        token_field="max_completion_tokens",
    )


def call_gemini_vision(messages: List[dict], img: str) -> str:
    require_key("Gemini", GEMINI_API_KEY)
    system_instruction, contents = gemini_contents(messages, img)
    payload = {"contents": contents}
    if system_instruction:
        payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

    errors = []
    for model in unique_values([GEMINI_VISION_MODEL, GEMINI_TEXT_MODEL, "gemini-3.5-flash", "gemini-2.5-flash"]):
        try:
            data = request_json(
                "Gemini",
                "POST",
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"},
                json=payload,
            )
            return extract_gemini_text(data)
        except ProviderError as exc:
            errors.append(f"{model}: {exc}")
            if not model_error(exc):
                break
    raise ProviderError("; ".join(errors))


def call_mistral_vision(messages: List[dict], img: str) -> str:
    require_key("Mistral", MISTRAL_API_KEY)
    errors = []
    for model in unique_values([MISTRAL_VISION_MODEL, MISTRAL_TEXT_MODEL, "mistral-medium-latest", "mistral-small-latest"]):
        try:
            data = request_json(
                "Mistral",
                "POST",
                "https://api.mistral.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json"},
                json={"model": model, "messages": openai_vision_messages(messages, img), "max_tokens": 1024},
            )
            return extract_chat_completion_text("Mistral", data)
        except ProviderError as exc:
            errors.append(f"{model}: {exc}")
            if not model_error(exc):
                break
    raise ProviderError("; ".join(errors))


def call_openrouter_vision(messages: List[dict], img: str) -> str:
    require_key("OpenRouter", OPENROUTER_API_KEY)
    if looks_like_openai_key(OPENROUTER_API_KEY):
        raise ProviderError("OPENROUTER_API_KEY is an OpenAI key, so the OpenAI provider will use it instead")
    data = request_json(
        "OpenRouter",
        "POST",
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8000",
            "X-OpenRouter-Title": "PearlAI",
            "X-Title": "PearlAI",
        },
        json={"model": OPENROUTER_VISION_MODEL, "messages": openai_vision_messages(messages, img), "max_tokens": 1024},
    )
    return extract_chat_completion_text("OpenRouter", data)


async def first_successful_provider(providers: List[Tuple[str, Callable, bool]]) -> Tuple[str, str, List[str]]:
    if not providers:
        raise ProviderError("No usable AI provider keys are configured for this request")

    errors = []
    for name, provider_call, is_async in providers:
        try:
            if is_async:
                return name, await provider_call(), errors
            return name, await asyncio.to_thread(provider_call), errors
        except Exception as exc:
            error = f"{name}: {exc}"
            if DEBUG_PROVIDERS:
                print(f"Provider failed - {error}")
            errors.append(error)
    raise ProviderError("; ".join(errors))


def build_messages(data: ChatInput) -> List[dict]:
    system_prompt = {
        "role": "system",
        "content": (
            "You are Pearl AI, a smart assistant created by Sayak. "
            "You are helpful, clear, and practical. "
            "When asked about Bengali festivals such as Jamai Sasthi or Durga Puja, "
            "advise checking the Bengali Panji based on Tithi to avoid inaccuracies."
        ),
    }
    history = [
        {"role": msg.role if msg.role in {"user", "assistant", "system"} else "user", "content": msg.content}
        for msg in data.history
        if msg.content
    ]
    return [system_prompt] + history + [{"role": "user", "content": data.message.strip()}]


@app.get("/api/health")
async def api_health():
    return {
        "status": "ok",
        "configured": {
            "xai": can_use_xai(),
            "groq": can_use_groq(),
            "gemini": can_use_gemini(),
            "mistral": can_use_mistral(),
            "openai": can_use_openai(),
            "openrouter": can_use_openrouter(),
            "virustotal": bool(VIRUSTOTAL_API_KEY),
            "shodan": bool(SHODAN_API_KEY),
        },
        "models": {
            "xai_text": XAI_TEXT_MODEL,
            "xai_vision": XAI_VISION_MODEL,
            "groq_text": GROQ_TEXT_MODEL,
            "groq_vision": GROQ_VISION_MODEL,
            "gemini_text": GEMINI_TEXT_MODEL,
            "gemini_vision": GEMINI_VISION_MODEL,
            "mistral_text": MISTRAL_TEXT_MODEL,
            "mistral_vision": MISTRAL_VISION_MODEL,
            "openai_text": OPENAI_TEXT_MODEL,
            "openai_vision": OPENAI_VISION_MODEL,
            "openrouter_text": OPENROUTER_TEXT_MODEL,
            "openrouter_vision": OPENROUTER_VISION_MODEL,
        },
    }


@app.post("/chat")
async def chat(data: ChatInput):
    user_message = data.message.strip()
    user_message_lower = user_message.lower()

    if not user_message and not data.image:
        return {"reply": "Please enter a message first."}

    try:
        if user_message_lower.startswith("shodan "):
            return {"reply": await asyncio.to_thread(scan_shodan, user_message[7:])}
        if user_message_lower.startswith("scan "):
            return {"reply": await asyncio.to_thread(scan_virustotal, user_message[5:])}

        messages = build_messages(data)
        if data.image:
            providers = []
            if can_use_openai():
                providers.append(("OpenAI Vision", lambda: call_openai_vision(messages, data.image), False))
            if can_use_xai():
                providers.append(("xAI Vision", lambda: call_xai_vision(messages, data.image), False))
            if can_use_mistral():
                providers.append(("Mistral Vision", lambda: call_mistral_vision(messages, data.image), False))
            if can_use_gemini():
                providers.append(("Gemini Vision", lambda: call_gemini_vision(messages, data.image), False))
            if can_use_groq():
                providers.append(("Groq Vision", lambda: call_groq_vision(messages, data.image), True))
            if can_use_openrouter():
                providers.append(("OpenRouter Vision", lambda: call_openrouter_vision(messages, data.image), False))
            _, reply, errors = await first_successful_provider(
                providers
            )
        else:
            providers = []
            if can_use_mistral():
                providers.append(("Mistral", lambda: call_mistral_text(messages), False))
            if can_use_openai():
                providers.append(("OpenAI", lambda: call_openai_text(messages), False))
            if can_use_xai():
                providers.append(("xAI", lambda: call_xai_text(messages), False))
            if can_use_gemini():
                providers.append(("Gemini", lambda: call_gemini_text(messages), False))
            if can_use_groq():
                providers.append(("Groq", lambda: call_groq_text(messages), True))
            if can_use_openrouter():
                providers.append(("OpenRouter", lambda: call_openrouter_text(messages), False))
            _, reply, errors = await first_successful_provider(
                providers
            )

        if errors and DEBUG_PROVIDERS:
            print("Fallbacks used before success:", " | ".join(errors))
        return {"reply": reply}
    except ProviderError as exc:
        return {
            "reply": (
                "Pearl AI could not reach any configured AI provider. "
                "The provider wiring is configured, but each API rejected the current request. "
                f"Details: {exc}"
            )
        }


@app.post("/api/login")
async def api_login(data: LoginInput):
    email = str(data.email or "").strip().lower()
    password = str(data.password or "").strip()

    if not email or not password:
        return {"status": "error", "message": "Email and password are required."}

    user = MOCK_USERS_DB.get(email)
    if user and user.get("password") == password:
        return {
            "status": "success",
            "message": "Login successful",
            "user": {"name": user.get("name", "User"), "email": email},
        }

    return {"status": "error", "message": "Invalid email or password."}


@app.post("/api/register")
async def api_register(data: LoginInput):
    email = str(data.email or "").strip().lower()
    name = str(data.name or "").strip()
    password = str(data.password or "").strip()

    if not name:
        return {"status": "error", "message": "Name is required for registration."}
    if not email or "@" not in email:
        return {"status": "error", "message": "A valid email is required."}
    if not password:
        return {"status": "error", "message": "Password is required."}
    if email in MOCK_USERS_DB:
        return {"status": "error", "message": "This email is already registered. Please login instead."}

    MOCK_USERS_DB[email] = {"password": password, "name": name}
    save_users(MOCK_USERS_DB)
    return {"status": "success", "message": "Account created successfully"}


@app.get("/login")
async def serve_login():
    path = os.path.join(BASE_DIR, "login.html")
    if not os.path.exists(path):
        path = os.path.join(FRONTEND_DIR, "login.html")
    return FileResponse(path)


@app.get("/")
async def serve_index():
    path = os.path.join(BASE_DIR, "index.html")
    if not os.path.exists(path):
        path = os.path.join(FRONTEND_DIR, "index.html")
    return FileResponse(path)


app.mount("/static", StaticFiles(directory=BASE_DIR), name="static")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

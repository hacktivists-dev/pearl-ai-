import os
import requests
import json
import base64
import socket
from urllib.parse import urlparse 
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List
import uvicorn
from groq import AsyncGroq

app = FastAPI()

# Enable CORS
app.add_middleware(
    CORSMiddleware, 
    allow_origins=["*"], 
    allow_methods=["*"], 
    allow_headers=["*"], 
)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app.mount("/static", StaticFiles(directory=BASE_DIR), name="static")
FRONTEND_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "Frontend"))

# =====================================================================
# 🚨 ALL API KEYS SETUP
# =====================================================================
GROQ_API_KEY = "xai-kdp4sdpwmc8BstboQ8wYreSgMabB0xqkINASWOGTlnrEaAlJe6jpw3MtRsfZwbWIx1jHeuv3iJP3AHWp"
GEMINI_API_KEY = "AQ.Ab8RN6JjkQGeLY6CYIWBljJBEHctcDh8d26xO3uHydenh95T-g"
MISTRAL_API_KEY = "XcobP6L8MxG63Vm1uY4UP890jao91PQd"
OPENROUTER_API_KEY = "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"

VIRUSTOTAL_API_KEY = "20a8bf5c6f517dc60a606284801da45879e23d4d6fc34be93dcbc2c26859389e"
SHODAN_API_KEY = "ZvPxyzETzay03HCnika6PMNj5he5gXb4"

groq_client = AsyncGroq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

class Message(BaseModel):
    role: str
    content: str

class ChatInput(BaseModel):
    message: str 
    history: List[Message] = []  
    image: Optional[str] = None  

# =====================================================================
# 🛡️ CYBERSECURITY TOOLS (VirusTotal & Shodan)
# =====================================================================
def scan_virustotal(target: str):
    headers = {"x-apikey": VIRUSTOTAL_API_KEY}
    if target.startswith("http://") or target.startswith("https://"):
        url_id = base64.urlsafe_b64encode(target.encode()).decode().strip("=")
        endpoint = f"https://www.virustotal.com/api/v3/urls/{url_id}"
        is_search = False
    else:
        endpoint = f"https://www.virustotal.com/api/v3/search?query={target}"
        is_search = True
    try:
        response = requests.get(endpoint, headers=headers, timeout=15)
        if response.status_code == 404: return f"ℹ️ No scan history found for `{target}`."
        response.raise_for_status()
        data = response.json()
        stats = {}
        if is_search:
            if "data" in data and len(data["data"]) > 0: stats = data["data"][0].get("attributes", {}).get("last_analysis_stats", {})
        else:
            if "data" in data and "attributes" in data["data"]: stats = data["data"]["attributes"].get("last_analysis_stats", {})
        if stats:
            malicious = stats.get("malicious", 0)
            suspicious = stats.get("suspicious", 0)
            harmless = stats.get("harmless", 0)
            result_msg = f"**VirusTotal Scan Report for `{target}`:**\n\n"
            if malicious > 0: result_msg += f"🚨 **ALERT!** {malicious} engines flagged this as MALICIOUS.\n"
            elif suspicious > 0: result_msg += f"⚠️ **WARNING:** {suspicious} engines flagged this as SUSPICIOUS.\n"
            else: result_msg += f"✅ **CLEAN:** No engines detected threats. (Harmless: {harmless})\n"
            return result_msg
        else: return f"ℹ️ Scan completed, but no specific threat data found for `{target}`."
    except Exception as e: return f"❌ VirusTotal API Error: {e}"

def scan_shodan(target: str):
    clean_target = target
    try:
        if target.startswith("http://") or target.startswith("https://"):
            parsed_url = urlparse(target)
            clean_target = parsed_url.netloc
        else: clean_target = target.split('/')[0]
        ip_address = socket.gethostbyname(clean_target)
        url = f"https://api.shodan.io/shodan/host/{ip_address}?key={SHODAN_API_KEY}"
        response = requests.get(url, timeout=15)
        if response.status_code == 404: return f"ℹ️ No info found in Shodan for `{clean_target}` (IP: {ip_address})"
        response.raise_for_status()
        data = response.json()
        org = data.get("org", "Unknown"); os_info = data.get("os", "Unknown"); ports = data.get("ports", []); vulns = data.get("vulns", [])
        result_msg = f"**Shodan Report for `{clean_target}` (IP: {ip_address}):**\n\n🏢 **Org:** {org}\n💻 **OS:** {os_info}\n🔓 **Ports:** {', '.join(map(str, ports)) if ports else 'None'}\n"
        if vulns: result_msg += f"\n⚠️ **CVEs Detected:** {len(vulns)}\n" + ", ".join(vulns[:5])
        else: result_msg += "\n✅ No known vulnerabilities detected."
        return result_msg
    except Exception as e: return f"❌ Shodan Error: {e}"

# =====================================================================
# 🚀 4-LAYER TEXT ROUTING ENGINES
# =====================================================================
async def call_groq_text(messages):
    chat_completion = await groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile", messages=messages, temperature=0.7, max_tokens=1024
    )
    return chat_completion.choices[0].message.content

def call_gemini_text(messages):
    gemini_messages = []
    system_instruction = None
    for msg in messages:
        if msg["role"] == "system":
            system_instruction = {"role": "system", "parts": [{"text": msg["content"]}]}
        else:
            gemini_messages.append({"role": "model" if msg["role"] == "assistant" else "user", "parts": [{"text": msg["content"]}]})
    payload = {"contents": gemini_messages}
    if system_instruction: payload["systemInstruction"] = system_instruction
    response = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={GEMINI_API_KEY}", json=payload, timeout=15)
    response.raise_for_status()
    return response.json()["candidates"][0]["content"]["parts"][0]["text"]

def call_mistral_text(messages):
    response = requests.post(
        "https://api.mistral.ai/v1/chat/completions",
        headers={"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json"},
        json={"model": "mistral-small-latest", "messages": messages}, timeout=15
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]

def call_openrouter_text(messages):
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
        json={"model": "google/gemini-2.0-flash-exp:free", "messages": messages, "max_tokens": 1024}, timeout=15
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]

# =====================================================================
# 👁️ 4-LAYER VISION ROUTING ENGINES
# =====================================================================
async def call_groq_vision(messages, img):
    formatted = []
    for msg in messages:
        if msg["role"] == "system": continue 
        content = [{"type": "text", "text": msg["content"] or "Analyze image."}]
        if img and msg == messages[-1]:
            content.append({"type": "image_url", "image_url": {"url": img if img.startswith("data:image") else f"data:image/jpeg;base64,{img}"}})
        formatted.append({"role": msg["role"], "content": content})
    res = await groq_client.chat.completions.create(model="llama-3.2-11b-vision-preview", messages=formatted, max_tokens=1024)
    return res.choices[0].message.content

def call_gemini_vision(messages, img):
    gemini_messages = []; sys_inst = None
    for msg in messages:
        if msg["role"] == "system": sys_inst = {"role": "system", "parts": [{"text": msg["content"]}]}; continue
        parts = [{"text": msg["content"] or "Analyze image."}]
        if img and msg == messages[-1]:
            b64_data = img.split(",")[1] if "," in img else img
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b64_data}})
        gemini_messages.append({"role": "model" if msg["role"] == "assistant" else "user", "parts": parts})
    payload = {"contents": gemini_messages}
    if sys_inst: payload["systemInstruction"] = sys_inst
    res = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={GEMINI_API_KEY}", json=payload, timeout=20)
    res.raise_for_status()
    return res.json()["candidates"][0]["content"]["parts"][0]["text"]

def call_mistral_vision(messages, img):
    formatted = []
    for msg in messages:
        if msg["role"] == "system": continue 
        content = [{"type": "text", "text": msg["content"] or "Analyze image."}]
        if img and msg == messages[-1]:
            content.append({"type": "image_url", "image_url": {"url": img if img.startswith("data:image") else f"data:image/jpeg;base64,{img}"}})
        formatted.append({"role": msg["role"], "content": content})
    res = requests.post("https://api.mistral.ai/v1/chat/completions", headers={"Authorization": f"Bearer {MISTRAL_API_KEY}"}, json={"model": "pixtral-12b-2409", "messages": formatted, "max_tokens": 1024}, timeout=20)
    res.raise_for_status()
    return res.json()["choices"][0]["message"]["content"]

def call_openrouter_vision(messages, img):
    formatted = []
    for msg in messages:
        if msg["role"] == "system": continue 
        content = [{"type": "text", "text": msg["content"] or "Analyze image."}]
        if img and msg == messages[-1]:
            content.append({"type": "image_url", "image_url": {"url": img if img.startswith("data:image") else f"data:image/jpeg;base64,{img}"}})
        formatted.append({"role": msg["role"], "content": content})
    res = requests.post("https://openrouter.ai/api/v1/chat/completions", headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"}, json={"model": "meta-llama/llama-3.2-11b-vision-instruct:free", "messages": formatted, "max_tokens": 1024}, timeout=20)
    res.raise_for_status()
    return res.json()["choices"][0]["message"]["content"]

# =====================================================================
# 🧠 THE CORE CHAT ENDPOINT WITH ULTIMATE 4-LEVEL FALLBACK
# =====================================================================
@app.post("/chat")
async def chat(data: ChatInput):
    user_message = data.message.strip()
    user_message_lower = user_message.lower() 
    
    if user_message_lower.startswith("shodan "): return {"reply": scan_shodan(user_message[7:])}
    if user_message_lower.startswith("scan "): return {"reply": scan_virustotal(user_message[5:])}

    system_prompt = {
        "role": "system", 
        "content": """You are Pearl AI, a smart assistant created by Sayak. 
        IMPORTANT: When asked about Bengali festivals (like Jamai Sasthi, Durga Puja, etc.), 
        always advise checking the 'Bengali Panji' (Bengali Almanac) based on 'Tithi' to avoid inaccuracies."""
    }
    
    api_messages = [system_prompt] + [{"role": msg.role, "content": msg.content} for msg in data.history] + [{"role": "user", "content": user_message}]

    # 📸 IMAGE CASCADE (Groq -> Gemini -> Mistral -> OpenRouter Free)
    if data.image:
        try: return {"reply": await call_groq_vision(api_messages, data.image)}
        except Exception as e1:
            print(f"⚠️ Groq Vision Failed: {e1}. Trying Gemini...")
            try: return {"reply": call_gemini_vision(api_messages, data.image)}
            except Exception as e2:
                print(f"⚠️ Gemini Vision Failed: {e2}. Trying Mistral...")
                try: return {"reply": call_mistral_vision(api_messages, data.image)}
                except Exception as e3:
                    print(f"⚠️ Mistral Vision Failed: {e3}. Trying OpenRouter...")
                    try: return {"reply": call_openrouter_vision(api_messages, data.image)}
                    except Exception as e4:
                        return {"reply": f"Image Scan Error: All 4 Vision engines failed! Last error: {str(e4)}"}

    # 📝 TEXT CASCADE (Groq -> Gemini -> Mistral -> OpenRouter Free)
    try:
        return {"reply": await call_groq_text(api_messages)}
    except Exception as e1:
        print(f"⚠️ Groq Text Failed: {e1}. Trying Gemini...")
        try: return {"reply": call_gemini_text(api_messages)}
        except Exception as e2:
            print(f"⚠️ Gemini Text Failed: {e2}. Trying Mistral...")
            try: return {"reply": call_mistral_text(api_messages)}
            except Exception as e3:
                print(f"⚠️ Mistral Text Failed: {e3}. Trying OpenRouter...")
                try: return {"reply": call_openrouter_text(api_messages)}
                except Exception as e4:
                    return {"reply": "Pearl AI is currently experiencing delays across ALL 4 backup engines. Please try again!"}

@app.get("/")
async def serve_index():
    return FileResponse(os.path.join(BASE_DIR, "index.html"))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
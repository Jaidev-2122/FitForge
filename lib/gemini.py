"""Server-only Gemini 2.5 Flash wrapper (REST). Never called from the browser."""
import os
import json
import requests

MODEL = "gemini-2.5-flash"
ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"


def generate(system: str | None = None, parts: list | None = None,
             json_mode: bool = False, temperature: float = 0.7) -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    body: dict = {
        "contents": [{"role": "user", "parts": parts or []}],
        "generationConfig": {"temperature": temperature},
    }
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}

    resp = requests.post(f"{ENDPOINT}?key={key}", json=body, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"Gemini API error {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    parts_out = data["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts_out)


def parse_json(raw: str):
    cleaned = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(cleaned)

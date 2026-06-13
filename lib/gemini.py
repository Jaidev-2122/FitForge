"""Server-only Gemini 2.5 Flash wrapper (REST). Never called from the browser."""
import os
import json
import time
import requests

MODEL = "gemini-2.5-flash"
ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"


def generate(system: str | None = None, parts: list | None = None,
             json_mode: bool = False, temperature: float = 0.7,
             max_tokens: int = 1200) -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    body: dict = {
        "contents": [{"role": "user", "parts": parts or []}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,  # cap response size to save memory
        },
    }
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}

    # Retry transient failures (503 high-demand, 429 rate, 500, network blips).
    # Gemini under load is the #1 cause of onboarding dead-ending.
    last_err = ""
    for attempt in range(3):
        try:
            resp = requests.post(f"{ENDPOINT}?key={key}", json=body, timeout=90)
        except requests.RequestException as e:
            last_err = f"network error: {e}"
            time.sleep(1.5 * (attempt + 1))
            continue

        if resp.status_code == 200:
            data = resp.json()
            candidates = data.get("candidates") or []
            if not candidates:
                # Blocked or empty under load — retry, then fail clearly.
                last_err = "Gemini returned no candidates (possibly overloaded or content-filtered)"
                time.sleep(1.5 * (attempt + 1))
                continue
            parts_out = (candidates[0].get("content") or {}).get("parts") or []
            text = "".join(p.get("text", "") for p in parts_out)
            if not text.strip():
                last_err = "Gemini returned an empty response"
                time.sleep(1.5 * (attempt + 1))
                continue
            return text

        # Retry on transient status codes; fail fast on auth/bad-request (4xx).
        if resp.status_code in (429, 500, 502, 503, 504):
            last_err = f"Gemini API error {resp.status_code}: {resp.text[:200]}"
            time.sleep(1.5 * (attempt + 1))
            continue
        # 4xx like 400/403 won't fix themselves (bad/blocked key) — stop now.
        raise RuntimeError(f"Gemini API error {resp.status_code}: {resp.text[:300]}")

    raise RuntimeError(f"Gemini failed after retries. Last: {last_err}")


def parse_json(raw: str):
    cleaned = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(cleaned)

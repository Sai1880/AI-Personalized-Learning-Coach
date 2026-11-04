"""Thin wrapper around the LLM API (Gemini). All LLM calls go through here."""
import json
import os
import re
import time

from dotenv import load_dotenv

load_dotenv()


class AIServiceError(Exception):
    """API/network/config failure. Safe to show to the user; they can retry."""


class InvalidResponseError(Exception):
    """The model kept returning output that failed validation."""


def _call_llm(prompt: str) -> str:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise AIServiceError("GEMINI_API_KEY is missing. Copy .env.example to .env and add your key.")
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise AIServiceError("The 'google-genai' package is not installed. Run: pip install -r requirements.txt") from exc

    client = genai.Client(api_key=api_key)
    last = None
    for attempt in range(2):  # one quick retry for transient network errors
        try:
            resp = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json", temperature=0.4),
            )
            if not resp.text:
                raise ValueError("empty response")
            return resp.text
        except Exception as exc:  # SDK raises various exception types
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise AIServiceError(f"The AI service could not be reached ({type(last).__name__}). Please try again.")


def parse_json(text: str):
    """Parse JSON, tolerating markdown code fences. Raises ValueError if invalid."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    return json.loads(cleaned)  # JSONDecodeError subclasses ValueError


def generate_structured(prompt: str, validator, max_attempts: int = 3):
    """Call the LLM and return validator(parsed_json).

    If the output is not valid JSON or fails validation (validator raises ValueError),
    retry with the error fed back to the model. API failures are raised immediately.
    """
    error = None
    for _ in range(max_attempts):
        full = prompt
        if error:
            full += f"\n\nYour previous reply was rejected: {error}\nReturn corrected JSON only."
        text = _call_llm(full)  # may raise AIServiceError
        try:
            return validator(parse_json(text))
        except ValueError as exc:
            error = str(exc)
    raise InvalidResponseError(
        f"The AI returned an invalid response after {max_attempts} tries ({error}). Please try again.")

import os
import json
import uuid
import sqlite3
import hashlib
import hmac
import time
from datetime import datetime, timezone

import requests
from flask import Flask, request, jsonify, make_response, render_template_string
from flask_cors import CORS


# ============================================================
# VEYA
# Multi-provider AI platform
# ============================================================

APP_NAME = "Veya"
VERSION = "13.0"

PORT = int(os.getenv("PORT", "10000"))
DB_PATH = os.getenv("DATABASE_PATH", "veya.db")
SECRET_KEY = os.getenv("SECRET_KEY", "change-this-in-production")

app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY

CORS(app)


# ============================================================
# PLANS
# ============================================================

PLANS = {
    "free": {
        "name": "Free",
        "price_inr": 0,
        "monthly_provider_budget_usd": 0.0,
        "daily_messages": 20,
        "providers": [
            "google",
            "local",
        ],
        "frontier": False,
        "model_picker": False,
    },

    "core": {
        "name": "Veya Core",
        "price_inr": 199,
        "monthly_provider_budget_usd": 1.25,
        "daily_messages": 100,
        "providers": [
            "openai",
            "google",
            "anthropic",
        ],
        "frontier": True,
        "model_picker": True,
    },

    "all_ai": {
        "name": "Veya All AI",
        "price_inr": 599,
        "monthly_provider_budget_usd": 4.00,
        "daily_messages": 300,
        "providers": [
            "openai",
            "google",
            "anthropic",
            "xai",
            "deepseek",
            "mistral",
            "nvidia",
            "microsoft",
            "meta",
            "groq",
        ],
        "frontier": True,
        "model_picker": True,
    },

    "ultra": {
        "name": "Veya Ultra",
        "price_inr": 1499,
        "monthly_provider_budget_usd": 10.00,
        "daily_messages": 1000,
        "providers": [
            "openai",
            "google",
            "anthropic",
            "xai",
            "deepseek",
            "mistral",
            "nvidia",
            "microsoft",
            "meta",
            "groq",
        ],
        "frontier": True,
        "model_picker": True,
    },
}


# ============================================================
# API KEYS
#
# NEVER put actual API keys directly into this file.
# Put them into Render Environment Variables.
# ============================================================

API_KEYS = {
    "openai": os.getenv("OPENAI_API_KEY", "").strip(),
    "anthropic": os.getenv("ANTHROPIC_API_KEY", "").strip(),
    "google": os.getenv("GOOGLE_API_KEY", "").strip(),
    "xai": os.getenv("XAI_API_KEY", "").strip(),
    "deepseek": os.getenv("DEEPSEEK_API_KEY", "").strip(),
    "mistral": os.getenv("MISTRAL_API_KEY", "").strip(),
    "nvidia": os.getenv("NVIDIA_API_KEY", "").strip(),
    "microsoft": os.getenv("MICROSOFT_API_KEY", "").strip(),
    "meta": os.getenv("META_API_KEY", "").strip(),
    "groq": os.getenv("GROQ_API_KEY", "").strip(),
}


# ============================================================
# BASE URLS
# ============================================================

BASE_URLS = {
    "openai": os.getenv(
        "OPENAI_BASE_URL",
        "https://api.openai.com/v1",
    ),

    "anthropic": os.getenv(
        "ANTHROPIC_BASE_URL",
        "https://api.anthropic.com",
    ),

    "google": os.getenv(
        "GOOGLE_BASE_URL",
        "https://generativelanguage.googleapis.com/v1beta",
    ),

    "xai": os.getenv(
        "XAI_BASE_URL",
        "https://api.x.ai/v1",
    ),

    "deepseek": os.getenv(
        "DEEPSEEK_BASE_URL",
        "https://api.deepseek.com",
    ),

    "mistral": os.getenv(
        "MISTRAL_BASE_URL",
        "https://api.mistral.ai/v1",
    ),

    "nvidia": os.getenv(
        "NVIDIA_BASE_URL",
        "https://integrate.api.nvidia.com/v1",
    ),

    "microsoft": os.getenv(
        "MICROSOFT_BASE_URL",
        "",
    ),

    "meta": os.getenv(
        "META_BASE_URL",
        "",
    ),

    "groq": os.getenv(
        "GROQ_BASE_URL",
        "https://api.groq.com/openai/v1",
    ),
}


# ============================================================
# OPTIONAL MODEL OVERRIDES
#
# You can set:
#
# OPENAI_MODELS=model1,model2
# GROQ_MODELS=model1,model2
#
# If not provided, Veya attempts model discovery.
# ============================================================

def env_list(name):
    raw = os.getenv(name, "").strip()

    if not raw:
        return []

    return [
        item.strip()
        for item in raw.split(",")
        if item.strip()
    ]


MODEL_OVERRIDES = {
    provider: env_list(
        f"{provider.upper()}_MODELS"
    )
    for provider in API_KEYS
}


# ============================================================
# MODEL DISCOVERY CACHE
# ============================================================

MODEL_CACHE = {}

MODEL_CACHE_SECONDS = int(
    os.getenv(
        "MODEL_CACHE_SECONDS",
        "300",
    )
)


def cache_get(provider):
    item = MODEL_CACHE.get(provider)

    if not item:
        return None

    timestamp, models = item

    if time.time() - timestamp > MODEL_CACHE_SECONDS:
        return None

    return models


def cache_set(provider, models):
    MODEL_CACHE[provider] = (
        time.time(),
        models,
    )


# ============================================================
# DATABASE
# ============================================================

def db():
    conn = sqlite3.connect(
        DB_PATH,
        timeout=30,
    )

    conn.row_factory = sqlite3.Row

    return conn


def utc_now():
    return datetime.now(
        timezone.utc
    ).isoformat()


def init_db():
    conn = db()

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            plan TEXT NOT NULL DEFAULT 'free',
            created_at TEXT NOT NULL,
            stripe_customer_id TEXT,
            stripe_subscription_id TEXT
        );

        CREATE TABLE IF NOT EXISTS chats (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            provider TEXT,
            model TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            provider TEXT,
            model TEXT,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            estimated_cost_usd REAL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        """
    )

    conn.commit()
    conn.close()


# ============================================================
# USER
# ============================================================

def get_user_id():
    uid = request.cookies.get(
        "veya_user"
    )

    if not uid:
        uid = str(uuid.uuid4())

    conn = db()

    row = conn.execute(
        "SELECT id FROM users WHERE id = ?",
        (uid,),
    ).fetchone()

    if not row:
        conn.execute(
            """
            INSERT INTO users(
                id,
                plan,
                created_at
            )
            VALUES (?, 'free', ?)
            """,
            (
                uid,
                utc_now(),
            ),
        )

        conn.commit()

    conn.close()

    return uid


def get_plan(user_id):
    conn = db()

    row = conn.execute(
        """
        SELECT plan
        FROM users
        WHERE id = ?
        """,
        (user_id,),
    ).fetchone()

    conn.close()

    if not row:
        return "free"

    plan = row["plan"]

    if plan not in PLANS:
        return "free"

    return plan


# ============================================================
# 5000 VIRTUAL SPECIALIST ROLES
#
# These are orchestration roles.
# They are NOT 5000 separate foundation models.
# ============================================================

BASE_ROLES = [
    "researcher",
    "coder",
    "debugger",
    "mathematician",
    "scientist",
    "writer",
    "editor",
    "planner",
    "analyst",
    "fact_checker",
    "critic",
    "summarizer",
    "translator",
    "teacher",
    "product_designer",
    "business_analyst",
    "security_reviewer",
    "data_analyst",
    "architect",
    "strategist",
]


def build_virtual_agents(count=5000):
    agents = []

    for i in range(count):
        base = BASE_ROLES[
            i % len(BASE_ROLES)
        ]

        agents.append(
            {
                "id": f"veya-agent-{i + 1:04d}",
                "role": (
                    f"{base}-"
                    f"{(i // len(BASE_ROLES)) + 1}"
                ),
                "index": i + 1,
            }
        )

    return agents


VIRTUAL_AGENTS = build_virtual_agents(
    5000
)


# ============================================================
# PROVIDER CONFIGURATION
# ============================================================

def provider_configured(provider):
    if provider == "local":
        return bool(
            os.getenv(
                "LOCAL_BASE_URL",
                "",
            ).strip()
        )

    if provider in (
        "microsoft",
        "meta",
    ):
        return (
            bool(API_KEYS.get(provider))
            and bool(
                BASE_URLS.get(provider)
            )
        )

    return bool(
        API_KEYS.get(provider)
    )


# ============================================================
# HTTP HELPERS
# ============================================================

def request_json(
    method,
    url,
    headers=None,
    params=None,
    payload=None,
    timeout=60,
):
    response = requests.request(
        method,
        url,
        headers=headers or {},
        params=params or {},
        json=payload,
        timeout=timeout,
    )

    if not response.ok:
        raise RuntimeError(
            f"HTTP {response.status_code}: "
            f"{response.text[:1000]}"
        )

    if not response.text.strip():
        return {}

    return response.json()


# ============================================================
# MODEL DISCOVERY
# ============================================================

def discover_openai_compatible_models(
    provider
):
    cached = cache_get(provider)

    if cached is not None:
        return cached

    if not provider_configured(provider):
        return []

    base = BASE_URLS.get(
        provider,
        "",
    ).rstrip("/")

    if not base:
        return []

    headers = {
        "Authorization":
            f"Bearer {API_KEYS[provider]}",
    }

    data = request_json(
        "GET",
        base + "/models",
        headers=headers,
        timeout=30,
    )

    result = []

    for item in data.get(
        "data",
        [],
    ):
        model_id = item.get("id")

        if model_id:
            result.append(
                model_id
            )

    result = list(
        dict.fromkeys(result)
    )

    cache_set(
        provider,
        result,
    )

    return result


def discover_anthropic_models():
    provider = "anthropic"

    cached = cache_get(provider)

    if cached is not None:
        return cached

    if not provider_configured(
        provider
    ):
        return []

    headers = {
        "x-api-key":
            API_KEYS[provider],

        "anthropic-version":
            "2023-06-01",
    }

    data = request_json(
        "GET",
        BASE_URLS[provider].rstrip("/")
        + "/v1/models",
        headers=headers,
        timeout=30,
    )

    result = []

    for item in data.get(
        "data",
        [],
    ):
        model_id = item.get("id")

        if model_id:
            result.append(
                model_id
            )

    result = list(
        dict.fromkeys(result)
    )

    cache_set(
        provider,
        result,
    )

    return result


def discover_google_models():
    provider = "google"

    cached = cache_get(provider)

    if cached is not None:
        return cached

    if not provider_configured(
        provider
    ):
        return []

    url = (
        BASE_URLS[provider].rstrip("/")
        + "/models"
    )

    data = request_json(
        "GET",
        url,
        params={
            "key":
                API_KEYS[provider],
        },
        timeout=30,
    )

    result = []

    for item in data.get(
        "models",
        [],
    ):
        name = item.get(
            "name",
            "",
        )

        methods = item.get(
            "supportedGenerationMethods",
            [],
        )

        if (
            name
            and (
                not methods
                or "generateContent"
                in methods
            )
        ):
            if name.startswith(
                "models/"
            ):
                name = name[
                    len("models/") :
                ]

            result.append(name)

    result = list(
        dict.fromkeys(result)
    )

    cache_set(
        provider,
        result,
    )

    return result


def discover_models(provider):
    override = MODEL_OVERRIDES.get(
        provider,
        [],
    )

    if override:
        return override

    if provider == "google":
        try:
            return discover_google_models()
        except Exception:
            return []

    if provider == "anthropic":
        try:
            return discover_anthropic_models()
        except Exception:
            return []

    if provider in (
        "openai",
        "xai",
        "deepseek",
        "mistral",
        "nvidia",
        "microsoft",
        "meta",
        "groq",
    ):
        try:
            return discover_openai_compatible_models(
                provider
            )
        except Exception:
            return []

    return []


# ============================================================
# MODEL RANKING
# ============================================================

def model_score(
    provider,
    model,
    task,
):
    name = model.lower()

    score = 0

    if task == "coding":
        if any(
            x in name
            for x in [
                "code",
                "coder",
                "reason",
                "reasoning",
            ]
        ):
            score += 10

    elif task == "research":
        if any(
            x in name
            for x in [
                "pro",
                "reason",
                "thinking",
                "research",
            ]
        ):
            score += 10

    elif task == "math":
        if any(
            x in name
            for x in [
                "reason",
                "thinking",
                "pro",
            ]
        ):
            score += 10

    elif task == "writing":
        if any(
            x in name
            for x in [
                "opus",
                "sonnet",
                "pro",
                "large",
            ]
        ):
            score += 8

    else:
        if any(
            x in name
            for x in [
                "pro",
                "large",
                "reason",
                "thinking",
                "opus",
                "sonnet",
            ]
        ):
            score += 5

    if provider == "openai":
        score += 3

    if provider == "anthropic":
        score += 3

    if provider == "google":
        score += 2

    return score


# ============================================================
# AVAILABLE MODELS FOR PLAN
# ============================================================

def available_models_for_plan(
    plan
):
    result = []

    for provider in PLANS[
        plan
    ]["providers"]:

        if provider == "local":
            continue

        if not provider_configured(
            provider
        ):
            continue

        models = discover_models(
            provider
        )

        for model in models:
            result.append(
                {
                    "provider":
                        provider,

                    "model":
                        model,

                    "available":
                        True,
                }
            )

    return result


# ============================================================
# FREE MODEL
# ============================================================

def free_model():
    if provider_configured(
        "google"
    ):
        models = discover_models(
            "google"
        )

        if models:
            return (
                "google",
                models[0],
            )

    if provider_configured(
        "groq"
    ):
        models = discover_models(
            "groq"
        )

        if models:
            return (
                "groq",
                models[0],
            )

    local_url = os.getenv(
        "LOCAL_BASE_URL",
        "",
    )

    if local_url:
        return (
            "local",
            os.getenv(
                "LOCAL_MODEL",
                "local-model",
            ),
        )

    return None, None


# ============================================================
# OPENAI
# ============================================================

def call_openai(
    model,
    messages,
):
    key = API_KEYS["openai"]

    payload = {
        "model": model,
        "input": messages,
    }

    data = request_json(
        "POST",
        BASE_URLS["openai"].rstrip("/")
        + "/responses",
        headers={
            "Authorization":
                f"Bearer {key}",

            "Content-Type":
                "application/json",
        },
        payload=payload,
        timeout=180,
    )

    text = data.get(
        "output_text",
        "",
    )

    if not text:
        chunks = []

        for item in data.get(
            "output",
            [],
        ):
            for content in item.get(
                "content",
                [],
            ):
                if (
                    content.get("type")
                    == "output_text"
                ):
                    chunks.append(
                        content.get(
                            "text",
                            "",
                        )
                    )

        text = "\n".join(
            chunks
        ).strip()

    usage = data.get(
        "usage",
        {},
    )

    return (
        text
        or "The model returned no text.",
        int(
            usage.get(
                "input_tokens",
                0,
            )
        ),
        int(
            usage.get(
                "output_tokens",
                0,
            )
        ),
    )


# ============================================================
# ANTHROPIC
# ============================================================

def call_anthropic(
    model,
    messages,
):
    key = API_KEYS[
        "anthropic"
    ]

    system_parts = []

    clean_messages = []

    for message in messages:
        if message["role"] == "system":
            system_parts.append(
                message["content"]
            )
        else:
            clean_messages.append(
                {
                    "role":
                        message["role"],

                    "content":
                        message["content"],
                }
            )

    payload = {
        "model": model,
        "max_tokens": 4096,
        "messages": clean_messages,
    }

    if system_parts:
        payload["system"] = "\n".join(
            system_parts
        )

    data = request_json(
        "POST",
        BASE_URLS["anthropic"].rstrip("/")
        + "/v1/messages",
        headers={
            "x-api-key": key,

            "anthropic-version":
                "2023-06-01",

            "Content-Type":
                "application/json",
        },
        payload=payload,
        timeout=180,
    )

    chunks = []

    for block in data.get(
        "content",
        [],
    ):
        if block.get("type") == "text":
            chunks.append(
                block.get(
                    "text",
                    "",
                )
            )

    usage = data.get(
        "usage",
        {},
    )

    return (
        "\n".join(
            chunks
        ).strip()
        or "The model returned no text.",

        int(
            usage.get(
                "input_tokens",
                0,
            )
        ),

        int(
            usage.get(
                "output_tokens",
                0,
            )
        ),
    )


# ============================================================
# GOOGLE GEMINI
# ============================================================

def call_google(
    model,
    messages,
):
    key = API_KEYS[
        "google"
    ]

    contents = []

    system_parts = []

    for message in messages:
        role = message["role"]

        if role == "system":
            system_parts.append(
                message["content"]
            )
            continue

        if role == "assistant":
            role = "model"

        contents.append(
            {
                "role": role,
                "parts": [
                    {
                        "text":
                            message["content"]
                    }
                ],
            }
        )

    payload = {
        "contents": contents,
        "generationConfig": {
            "maxOutputTokens":
                4096,
        },
    }

    if system_parts:
        payload[
            "systemInstruction"
        ] = {
            "parts": [
                {
                    "text":
                        "\n".join(
                            system_parts
                        )
                }
            ]
        }

    url = (
        BASE_URLS["google"].rstrip("/")
        + f"/models/{model}:generateContent"
    )

    data = request_json(
        "POST",
        url,
        params={
            "key": key,
        },
        headers={
            "Content-Type":
                "application/json",
        },
        payload=payload,
        timeout=180,
    )

    chunks = []

    for candidate in data.get(
        "candidates",
        [],
    ):
        content = candidate.get(
            "content",
            {},
        )

        for part in content.get(
            "parts",
            [],
        ):
            if part.get("text"):
                chunks.append(
                    part["text"]
                )

    usage = data.get(
        "usageMetadata",
        {},
    )

    return (
        "\n".join(
            chunks
        ).strip()
        or "The model returned no text.",

        int(
            usage.get(
                "promptTokenCount",
                0,
            )
        ),

        int(
            usage.get(
                "candidatesTokenCount",
                0,
            )
        ),
    )


# ============================================================
# OPENAI-COMPATIBLE PROVIDERS
#
# Used by:
# xAI
# DeepSeek
# Mistral
# NVIDIA
# Microsoft-compatible endpoints
# Meta-compatible endpoints
# Groq
# ============================================================

def call_openai_compatible(
    provider,
    model,
    messages,
):
    base = BASE_URLS.get(
        provider,
        "",
    )

    if not base:
        raise RuntimeError(
            f"{provider} base URL is not configured."
        )

    key = API_KEYS.get(
        provider,
        "",
    )

    if not key:
        raise RuntimeError(
            f"{provider} API key is not configured."
        )

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 4096,
    }

    data = request_json(
        "POST",
        base.rstrip("/")
        + "/chat/completions",
        headers={
            "Authorization":
                f"Bearer {key}",

            "Content-Type":
                "application/json",
        },
        payload=payload,
        timeout=180,
    )

    choices = data.get(
        "choices",
        [],
    )

    if not choices:
        raise RuntimeError(
            f"{provider} returned no choices."
        )

    message = choices[0].get(
        "message",
        {},
    )

    content = message.get(
        "content",
        "",
    )

    if isinstance(
        content,
        list,
    ):
        parts = []

        for part in content:
            if isinstance(
                part,
                dict,
            ):
                if part.get("text"):
                    parts.append(
                        part["text"]
                    )

        content = "\n".join(
            parts
        )

    usage = data.get(
        "usage",
        {},
    )

    return (
        content
        or "The model returned no text.",

        int(
            usage.get(
                "prompt_tokens",
                0,
            )
        ),

        int(
            usage.get(
                "completion_tokens",
                0,
            )
        ),
    )


# ============================================================
# LOCAL
# ============================================================

def call_local(
    model,
    messages,
):
    base = os.getenv(
        "LOCAL_BASE_URL",
        "",
    ).strip()

    if not base:
        raise RuntimeError(
            "LOCAL_BASE_URL is not configured."
        )

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 4096,
    }

    data = request_json(
        "POST",
        base.rstrip("/")
        + "/chat/completions",
        headers={
            "Content-Type":
                "application/json",
        },
        payload=payload,
        timeout=180,
    )

    choices = data.get(
        "choices",
        [],
    )

    if not choices:
        raise RuntimeError(
            "Local provider returned no choices."
        )

    message = choices[0].get(
        "message",
        {},
    )

    text = message.get(
        "content",
        "",
    )

    usage = data.get(
        "usage",
        {},
    )

    return (
        text
        or "The model returned no text.",

        int(
            usage.get(
                "prompt_tokens",
                0,
            )
        ),

        int(
            usage.get(
                "completion_tokens",
                0,
            )
        ),
    )


# ============================================================
# UNIFIED PROVIDER CALL
# ============================================================

def call_provider(
    provider,
    model,
    messages,
):
    if provider == "openai":
        return call_openai(
            model,
            messages,
        )

    if provider == "anthropic":
        return call_anthropic(
            model,
            messages,
        )

    if provider == "google":
        return call_google(
            model,
            messages,
        )

    if provider == "local":
        return call_local(
            model,
            messages,
        )

    return call_openai_compatible(
        provider,
        model,
        messages,
    )


# ============================================================
# ROUTER
# ============================================================

def route_task(text):
    lower = text.lower()

    if any(
        word in lower
        for word in [
            "code",
            "python",
            "javascript",
            "program",
            "debug",
            "api",
            "docker",
        ]
    ):
        return "coding"

    if any(
        word in lower
        for word in [
            "math",
            "equation",
            "calculate",
            "proof",
        ]
    ):
        return "math"

    if any(
        word in lower
        for word in [
            "research",
            "latest",
            "current",
            "news",
            "today",
        ]
    ):
        return "research"

    if any(
        word in lower
        for word in [
            "write",
            "story",
            "article",
            "email",
        ]
    ):
        return "writing"

    return "general"


# ============================================================
# MODEL CHOICE
# ============================================================

def choose_model(
    plan,
    requested_provider=None,
    requested_model=None,
    task="general",
):
    models = available_models_for_plan(
        plan
    )

    if (
        requested_provider
        and requested_model
    ):
        for item in models:
            if (
                item["provider"]
                == requested_provider
                and item["model"]
                == requested_model
            ):
                return (
                    requested_provider,
                    requested_model,
                )

        raise RuntimeError(
            "That model is unavailable "
            "for your plan or is not "
            "configured on the server."
        )

    if not models:
        raise RuntimeError(
            "No configured provider/model "
            "is available for this plan."
        )

    ranked = sorted(
        models,
        key=lambda item:
            model_score(
                item["provider"],
                item["model"],
                task,
            ),
        reverse=True,
    )

    return (
        ranked[0]["provider"],
        ranked[0]["model"],
    )


# ============================================================
# STYLE PRESETS
# ============================================================

STYLE_PRESETS = {
    "balanced": (
        "Answer clearly, accurately and naturally. "
        "Prefer useful structure without unnecessary verbosity."
    ),

    "reasoning": (
        "Think carefully before answering. "
        "Check assumptions, edge cases and contradictions. "
        "Give a concise but rigorous final answer."
    ),

    "coding": (
        "Act as a senior software engineer. "
        "Prefer correct, maintainable and testable code. "
        "Point out important implementation risks."
    ),

    "writing": (
        "Write naturally and clearly. "
        "Use strong organization and good explanations."
    ),

    "anthropic_style": (
        "Use a calm, careful and thoughtful writing style. "
        "Be precise and transparent about uncertainty. "
        "This is a Veya style preset and is not Claude."
    ),
}


SYSTEM_PROMPT = """
You are Veya, a multi-provider AI platform.

Rules:

- Never falsely claim to be another company's model.
- Only identify a provider/model when that actual provider/model
  is being used.
- Never invent provider access.
- Be honest about uncertainty.
- Give useful and accurate answers.
"""


# ============================================================
# USAGE
# ============================================================

def month_start():
    now = datetime.now(
        timezone.utc
    )

    return now.strftime(
        "%Y-%m"
    )


def monthly_cost(
    user_id
):
    conn = db()

    row = conn.execute(
        """
        SELECT COALESCE(
            SUM(estimated_cost_usd),
            0
        )
        FROM usage
        WHERE user_id = ?
        AND substr(
            created_at,
            1,
            7
        ) = ?
        """,
        (
            user_id,
            month_start(),
        ),
    ).fetchone()

    conn.close()

    return float(
        row[0] or 0
    )


def daily_message_count(
    user_id
):
    today = (
        datetime.now(
            timezone.utc
        ).strftime("%Y-%m-%d")
    )

    conn = db()

    row = conn.execute(
        """
        SELECT COUNT(*)
        FROM messages m
        JOIN chats c
          ON c.id = m.chat_id
        WHERE c.user_id = ?
        AND m.role = 'user'
        AND substr(
            m.created_at,
            1,
            10
        ) = ?
        """,
        (
            user_id,
            today,
        ),
    ).fetchone()

    conn.close()

    return int(
        row[0] or 0
    )


def estimate_cost(
    model,
    input_tokens,
    output_tokens,
):
    # Conservative internal estimate.
    # Actual provider billing can differ.
    return (
        (
            float(
                input_tokens or 0
            )
            / 1_000_000
        )
        * 2.0
        +
        (
            float(
                output_tokens or 0
            )
            / 1_000_000
        )
        * 8.0
    )


def record_usage(
    user_id,
    provider,
    model,
    input_tokens,
    output_tokens,
):
    cost = estimate_cost(
        model,
        input_tokens,
        output_tokens,
    )

    conn = db()

    conn.execute(
        """
        INSERT INTO usage(
            user_id,
            provider,
            model,
            input_tokens,
            output_tokens,
            estimated_cost_usd,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            provider,
            model,
            input_tokens,
            output_tokens,
            cost,
            utc_now(),
        ),
    )

    conn.commit()
    conn.close()

    return cost


# ============================================================
# CHAT HELPERS
# ============================================================

def create_chat(
    user_id,
    title="New chat",
):
    chat_id = str(
        uuid.uuid4()
    )

    now = utc_now()

    conn = db()

    conn.execute(
        """
        INSERT INTO chats(
            id,
            user_id,
            title,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            chat_id,
            user_id,
            title,
            now,
            now,
        ),
    )

    conn.commit()
    conn.close()

    return chat_id


def ensure_chat(
    user_id,
    chat_id,
):
    conn = db()

    row = conn.execute(
        """
        SELECT id
        FROM chats
        WHERE id = ?
        AND user_id = ?
        """,
        (
            chat_id,
            user_id,
        ),
    ).fetchone()

    conn.close()

    if not row:
        raise RuntimeError(
            "Chat not found."
        )

    return chat_id


def save_message(
    chat_id,
    role,
    content,
    provider=None,
    model=None,
):
    now = utc_now()

    conn = db()

    conn.execute(
        """
        INSERT INTO messages(
            chat_id,
            role,
            content,
            provider,
            model,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            chat_id,
            role,
            content,
            provider,
            model,
            now,
        ),
    )

    conn.execute(
        """
        UPDATE chats
        SET updated_at = ?
        WHERE id = ?
        """,
        (
            now,
            chat_id,
        ),
    )

    conn.commit()
    conn.close()


def get_messages(
    chat_id,
    limit=30,
):
    conn = db()

    rows = conn.execute(
        """
        SELECT
            role,
            content,
            provider,
            model,
            created_at
        FROM messages
        WHERE chat_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (
            chat_id,
            limit,
        ),
    ).fetchall()

    conn.close()

    rows = list(
        reversed(rows)
    )

    return [
        dict(row)
        for row in rows
    ]


# ============================================================
# ROUTES
# ============================================================

@app.get("/api/health")
def health():
    return jsonify(
        {
            "ok": True,
            "app": APP_NAME,
            "version": VERSION,
            "time": utc_now(),
        }
    )


@app.get("/api/me")
def me():
    uid = get_user_id()
    plan = get_plan(uid)

    response = jsonify(
        {
            "user_id": uid,
            "plan": plan,
            "plan_info": PLANS[plan],
            "monthly_cost_usd":
                monthly_cost(uid),
        }
    )

    response.set_cookie(
        "veya_user",
        uid,
        httponly=True,
        samesite="Lax",
    )

    return response


@app.get("/api/plans")
def plans():
    return jsonify(
        PLANS
    )


@app.get("/api/providers")
def providers():
    output = []

    for provider in API_KEYS:
        output.append(
            {
                "provider": provider,
                "configured":
                    provider_configured(
                        provider
                    ),
                "models":
                    discover_models(
                        provider
                    ),
            }
        )

    return jsonify(
        output
    )


@app.get("/api/models")
def models():
    uid = get_user_id()

    plan = get_plan(uid)

    return jsonify(
        {
            "plan": plan,

            "model_picker":
                PLANS[plan][
                    "model_picker"
                ],

            "models":
                available_models_for_plan(
                    plan
                ),
        }
    )


@app.get("/api/agents")
def agents():
    return jsonify(
        {
            "count":
                len(VIRTUAL_AGENTS),

            "agents":
                VIRTUAL_AGENTS[:100],

            "note":
                "These are virtual orchestration "
                "roles, not 5000 independent "
                "foundation models.",
        }
    )


@app.get("/api/chats")
def chats():
    uid = get_user_id()

    conn = db()

    rows = conn.execute(
        """
        SELECT
            id,
            title,
            created_at,
            updated_at
        FROM chats
        WHERE user_id = ?
        ORDER BY updated_at DESC
        """,
        (uid,),
    ).fetchall()

    conn.close()

    return jsonify(
        [
            dict(row)
            for row in rows
        ]
    )


@app.get(
    "/api/chats/<chat_id>"
)
def chat_detail(
    chat_id
):
    uid = get_user_id()

    ensure_chat(
        uid,
        chat_id,
    )

    return jsonify(
        {
            "chat_id":
                chat_id,

            "messages":
                get_messages(
                    chat_id
                ),
        }
    )


@app.post(
    "/api/chats/new"
)
def new_chat():
    uid = get_user_id()

    chat_id = create_chat(
        uid
    )

    return jsonify(
        {
            "chat_id":
                chat_id
        }
    )


# ============================================================
# CHAT
# ============================================================

@app.post("/api/chat")
def chat():
    uid = get_user_id()

    plan = get_plan(uid)

    plan_data = PLANS[plan]

    body = (
        request.get_json(
            silent=True
        )
        or {}
    )

    text = str(
        body.get(
            "message",
            "",
        )
    ).strip()

    if not text:
        return jsonify(
            {
                "error":
                    "Message is required."
            }
        ), 400

    if len(text) > 30000:
        return jsonify(
            {
                "error":
                    "Message is too long."
            }
        ), 400

    # Daily message limit
    if (
        daily_message_count(uid)
        >= plan_data[
            "daily_messages"
        ]
    ):
        return jsonify(
            {
                "error":
                    "Your daily message limit "
                    "has been reached."
            }
        ), 429

    chat_id = body.get(
        "chat_id"
    )

    if not chat_id:
        chat_id = create_chat(
            uid,
            title=text[:60],
        )

    ensure_chat(
        uid,
        chat_id,
    )

    requested_provider = body.get(
        "provider"
    )

    requested_model = body.get(
        "model"
    )

    style = body.get(
        "style",
        "balanced",
    )

    if style not in STYLE_PRESETS:
        style = "balanced"

    if plan == "free":
        requested_provider = None
        requested_model = None

    task = route_task(
        text
    )

    try:
        if plan == "free":
            provider, model = free_model()

            if not provider:
                return jsonify(
                    {
                        "error":
                            "No free model is "
                            "configured. Add a "
                            "configured provider "
                            "or LOCAL_BASE_URL."
                    }
                ), 503

        else:
            provider, model = choose_model(
                plan,
                requested_provider,
                requested_model,
                task,
            )

    except Exception as exc:
        return jsonify(
            {
                "error":
                    str(exc)
            }
        ), 403

    current_cost = monthly_cost(
        uid
    )

    budget = plan_data[
        "monthly_provider_budget_usd"
    ]

    if (
        budget > 0
        and current_cost >= budget
    ):
        return jsonify(
            {
                "error":
                    "Your monthly AI usage "
                    "budget has been reached."
            }
        ), 402

    history = get_messages(
        chat_id,
        limit=20,
    )

    messages = [
        {
            "role": "system",
            "content":
                SYSTEM_PROMPT
                + "\n\n"
                + STYLE_PRESETS[style],
        }
    ]

    for item in history:
        if item["role"] in (
            "user",
            "assistant",
        ):
            messages.append(
                {
                    "role":
                        item["role"],

                    "content":
                        item["content"],
                }
            )

    messages.append(
        {
            "role": "user",
            "content": text,
        }
    )

    save_message(
        chat_id,
        "user",
        text,
    )

    try:
        answer, input_tokens, output_tokens = (
            call_provider(
                provider,
                model,
                messages,
            )
        )

    except Exception as exc:
        return jsonify(
            {
                "error":
                    (
                        f"{provider}/{model} failed: "
                        f"{str(exc)}"
                    ),

                "provider":
                    provider,

                "model":
                    model,
            }
        ), 502

    cost = record_usage(
        uid,
        provider,
        model,
        input_tokens,
        output_tokens,
    )

    save_message(
        chat_id,
        "assistant",
        answer,
        provider,
        model,
    )

    return jsonify(
        {
            "chat_id":
                chat_id,

            "answer":
                answer,

            "provider":
                provider,

            "model":
                model,

            "usage":
                {
                    "input_tokens":
                        input_tokens,

                    "output_tokens":
                        output_tokens,

                    "estimated_cost_usd":
                        cost,

                    "monthly_cost_usd":
                        monthly_cost(uid),

                    "monthly_budget_usd":
                        budget,
                },
        }
    )


# ============================================================
# MODEL HEALTH TEST
# ============================================================

@app.post(
    "/api/test-model"
)
def test_model():
    uid = get_user_id()

    plan = get_plan(uid)

    body = (
        request.get_json(
            silent=True
        )
        or {}
    )

    provider = body.get(
        "provider"
    )

    model = body.get(
        "model"
    )

    if not provider or not model:
        return jsonify(
            {
                "error":
                    "provider and model "
                    "are required."
            }
        ), 400

    if provider not in PLANS[
        plan
    ]["providers"]:
        return jsonify(
            {
                "error":
                    "Provider is not "
                    "available for this plan."
            }
        ), 403

    if not provider_configured(
        provider
    ):
        return jsonify(
            {
                "ok":
                    False,

                "error":
                    "Server-side API key "
                    "or base URL is not configured.",
            }
        ), 503

    try:
        answer, input_tokens, output_tokens = (
            call_provider(
                provider,
                model,
                [
                    {
                        "role":
                            "system",

                        "content":
                            "You are a model "
                            "health check. "
                            "Reply with exactly OK.",
                    },

                    {
                        "role":
                            "user",

                        "content":
                            "Reply with exactly OK.",
                    },
                ],
            )
        )

        return jsonify(
            {
                "ok":
                    True,

                "provider":
                    provider,

                "model":
                    model,

                "answer":
                    answer,

                "input_tokens":
                    input_tokens,

                "output_tokens":
                    output_tokens,
            }
        )

    except Exception as exc:
        return jsonify(
            {
                "ok":
                    False,

                "provider":
                    provider,

                "model":
                    model,

                "error":
                    str(exc),
            }
        ), 502


# ============================================================
# STRIPE
# ============================================================

STRIPE_SECRET_KEY = os.getenv(
    "STRIPE_SECRET_KEY",
    "",
).strip()

STRIPE_WEBHOOK_SECRET = os.getenv(
    "STRIPE_WEBHOOK_SECRET",
    "",
).strip()

PUBLIC_BASE_URL = os.getenv(
    "PUBLIC_BASE_URL",
    "http://localhost:10000",
).rstrip("/")


def stripe_request(
    method,
    path,
    data=None,
):
    if not STRIPE_SECRET_KEY:
        raise RuntimeError(
            "STRIPE_SECRET_KEY is not configured."
        )

    response = requests.request(
        method,
        "https://api.stripe.com/v1"
        + path,

        auth=(
            STRIPE_SECRET_KEY,
            "",
        ),

        data=data or {},

        timeout=60,
    )

    if not response.ok:
        raise RuntimeError(
            f"Stripe {response.status_code}: "
            f"{response.text[:1000]}"
        )

    return response.json()


@app.post(
    "/api/upgrade"
)
def upgrade():
    uid = get_user_id()

    body = (
        request.get_json(
            silent=True
        )
        or {}
    )

    plan = body.get(
        "plan"
    )

    if plan not in (
        "core",
        "all_ai",
        "ultra",
    ):
        return jsonify(
            {
                "error":
                    "Invalid paid plan."
            }
        ), 400

    if not STRIPE_SECRET_KEY:
        return jsonify(
            {
                "configured":
                    False,

                "message":
                    "Stripe is not configured yet.",

                "plan":
                    plan,
            }
        )

    plan_info = PLANS[
        plan
    ]

    data = {
        "mode":
            "subscription",

        "success_url":
            PUBLIC_BASE_URL
            + "/?payment=success",

        "cancel_url":
            PUBLIC_BASE_URL
            + "/?payment=cancelled",

        "line_items[0][price_data][currency]":
            "inr",

        "line_items[0][price_data][unit_amount]":
            str(
                plan_info[
                    "price_inr"
                ] * 100
            ),

        "line_items[0][price_data][product_data][name]":
            plan_info[
                "name"
            ],

        "line_items[0][price_data][recurring][interval]":
            "month",

        "line_items[0][quantity]":
            "1",

        "metadata[user_id]":
            uid,

        "metadata[plan]":
            plan,
    }

    session = stripe_request(
        "POST",
        "/checkout/sessions",
        data,
    )

    return jsonify(
        {
            "configured":
                True,

            "checkout_url":
                session.get(
                    "url"
                ),
        }
    )


# ============================================================
# STRIPE WEBHOOK
# ============================================================

def verify_stripe_signature(
    payload,
    signature,
):
    if not STRIPE_WEBHOOK_SECRET:
        return False

    parts = {}

    for item in signature.split(","):
        if "=" in item:
            key, value = item.split(
                "=",
                1,
            )

            parts.setdefault(
                key,
                [],
            ).append(value)

    timestamps = parts.get(
        "t",
        [],
    )

    signatures = parts.get(
        "v1",
        [],
    )

    if not timestamps or not signatures:
        return False

    timestamp = timestamps[0]

    try:
        timestamp_int = int(
            timestamp
        )
    except ValueError:
        return False

    if abs(
        time.time()
        - timestamp_int
    ) > 300:
        return False

    signed_payload = (
        timestamp
        + "."
        + payload.decode(
            "utf-8"
        )
    )

    expected = hmac.new(
        STRIPE_WEBHOOK_SECRET.encode(),
        signed_payload.encode(),
        hashlib.sha256,
    ).hexdigest()

    return any(
        hmac.compare_digest(
            expected,
            value,
        )
        for value in signatures
    )


@app.post(
    "/api/stripe/webhook"
)
def stripe_webhook():
    payload = request.get_data()

    signature = request.headers.get(
        "Stripe-Signature",
        "",
    )

    if not verify_stripe_signature(
        payload,
        signature,
    ):
        return (
            "Invalid signature",
            400,
        )

    event = (
        request.get_json(
            silent=True
        )
        or {}
    )

    event_type = event.get(
        "type"
    )

    obj = (
        event.get(
            "data",
            {},
        )
        .get(
            "object",
            {},
        )
    )

    metadata = obj.get(
        "metadata",
        {},
    )

    uid = metadata.get(
        "user_id"
    )

    plan = metadata.get(
        "plan"
    )

    if (
        uid
        and plan in PLANS
        and plan != "free"
        and event_type in (
            "checkout.session.completed",
            "customer.subscription.created",
            "customer.subscription.updated",
        )
    ):
        conn = db()

        conn.execute(
            """
            UPDATE users
            SET
                plan = ?,
                stripe_customer_id = ?,
                stripe_subscription_id = ?
            WHERE id = ?
            """,
            (
                plan,

                obj.get(
                    "customer"
                ),

                obj.get(
                    "subscription"
                ),

                uid,
            ),
        )

        conn.commit()
        conn.close()

    return jsonify(
        {
            "received":
                True
        }
    )


# ============================================================
# FRONTEND
# ============================================================

HTML = r"""
<!doctype html>

<html>

<head>

<meta charset="utf-8">

<meta name="viewport"
      content="width=device-width,initial-scale=1">

<title>Veya</title>

<style>

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    font-family:
        Inter,
        system-ui,
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        sans-serif;

    background: #ffffff;
    color: #171717;
}

button,
textarea,
input,
select {
    font: inherit;
}

button {
    cursor: pointer;
}

#app {
    height: 100vh;
    display: flex;
    overflow: hidden;
}

#sidebar {
    position: fixed;
    left: 0;
    top: 0;
    bottom: 0;

    width: 285px;

    background: #f7f7f8;

    border-right:
        1px solid #e7e7e7;

    transform:
        translateX(-100%);

    transition:
        transform .22s ease;

    z-index: 30;

    display: flex;
    flex-direction: column;
}

#sidebar.open {
    transform:
        translateX(0);
}

.sidebar-top {
    padding: 18px;
}

.new-chat {
    width: 100%;

    border:
        1px solid #ddd;

    background: white;

    border-radius: 12px;

    padding: 12px;

    text-align: left;
}

.history {
    flex: 1;

    overflow-y: auto;

    padding: 10px;
}

.history-item {
    padding: 11px 12px;

    border-radius: 9px;

    cursor: pointer;

    white-space: nowrap;

    overflow: hidden;

    text-overflow: ellipsis;
}

.history-item:hover {
    background: #ececef;
}

.sidebar-bottom {
    padding: 14px;

    border-top:
        1px solid #e3e3e3;
}

#overlay {
    position: fixed;

    inset: 0;

    background:
        rgba(0,0,0,.22);

    display: none;

    z-index: 20;
}

#overlay.show {
    display: block;
}

#main {
    width: 100%;

    height: 100vh;

    display: flex;

    flex-direction: column;
}

.topbar {
    height: 68px;

    display: flex;

    align-items: center;

    gap: 12px;

    padding: 10px 18px;

    border-bottom:
        1px solid #eee;

    background:
        rgba(255,255,255,.94);
}

.icon-btn {
    width: 42px;

    height: 42px;

    border: none;

    background:
        transparent;

    border-radius: 10px;

    font-size: 24px;
}

.icon-btn:hover {
    background: #f1f1f1;
}

.brand {
    font-weight: 700;

    font-size: 20px;
}

.spacer {
    flex: 1;
}

.upgrade {
    border: none;

    background: #9bd0ff;

    padding:
        10px 19px;

    border-radius: 22px;

    font-weight: 700;
}

.chat-area {
    flex: 1;

    overflow-y: auto;

    padding:
        28px 18px 150px;
}

.message {
    max-width: 850px;

    margin:
        0 auto 20px;

    line-height: 1.65;
}

.user-message {
    background: #f4f4f4;

    padding:
        13px 16px;

    border-radius: 18px;

    margin-left: auto;

    max-width: 700px;
}

.assistant-message {
    padding: 4px 0;
}

.model-tag {
    font-size: 12px;

    color: #777;

    margin-bottom: 5px;
}

.composer-wrap {
    position: fixed;

    left: 0;
    right: 0;
    bottom: 0;

    padding: 15px;

    background:
        linear-gradient(
            transparent,
            white 25%
        );
}

.composer {
    max-width: 850px;

    margin: auto;

    background: white;

    border:
        1px solid #d9d9d9;

    border-radius: 24px;

    padding: 9px;

    box-shadow:
        0 5px 25px
        rgba(0,0,0,.07);
}

.composer-row {
    display: flex;

    align-items: flex-end;

    gap: 8px;
}

.plus {
    width: 42px;

    height: 42px;

    border: none;

    background:
        transparent;

    font-size: 27px;

    border-radius: 50%;
}

.plus:hover {
    background: #f1f1f1;
}

textarea {
    flex: 1;

    border: none;

    outline: none;

    resize: none;

    min-height: 42px;

    max-height: 150px;

    padding:
        11px 5px;
}

.send {
    width: 42px;

    height: 42px;

    border-radius: 50%;

    border: none;

    background: #111;

    color: white;
}

.model-picker {
    display: none;

    padding: 10px;

    border-top:
        1px solid #eee;
}

.model-picker.open {
    display: block;
}

.model-select {
    width: 100%;

    border:
        1px solid #ddd;

    border-radius: 12px;

    padding: 10px;
}

.modal {
    position: fixed;

    inset: 0;

    background:
        rgba(0,0,0,.45);

    display: none;

    align-items: center;

    justify-content: center;

    z-index: 100;

    padding: 20px;
}

.modal.show {
    display: flex;
}

.modal-box {
    width:
        min(1050px, 100%);

    max-height: 90vh;

    overflow-y: auto;

    background: white;

    border-radius: 24px;

    padding: 24px;
}

.close {
    float: right;

    border: none;

    background:
        transparent;

    font-size: 25px;
}

.plans {
    display: grid;

    grid-template-columns:
        repeat(3, 1fr);

    gap: 15px;

    margin-top: 25px;
}

.plan {
    border:
        1px solid #ddd;

    border-radius: 18px;

    padding: 20px;
}

.plan.recommended {
    border:
        2px solid #111;
}

.plan h3 {
    margin-top: 0;
}

.price {
    font-size: 30px;

    font-weight: 800;

    margin: 12px 0;
}

.plan button {
    width: 100%;

    border: none;

    border-radius: 12px;

    padding: 12px;

    background: #111;

    color: white;
}

@media(max-width:700px) {

    .plans {
        grid-template-columns:
            1fr;
    }

    .brand {
        font-size: 18px;
    }

    .upgrade {
        padding:
            9px 13px;
    }
}

</style>

</head>

<body>

<div id="app">

<aside id="sidebar">

<div class="sidebar-top">

<button
    class="new-chat"
    onclick="newChat()">

＋ New chat

</button>

</div>

<div
    id="history"
    class="history">
</div>

<div class="sidebar-bottom">

<div id="account">
Free plan
</div>

</div>

</aside>


<div
    id="overlay"
    onclick="toggleSidebar()">
</div>


<main id="main">

<header class="topbar">

<button
    class="icon-btn"
    onclick="toggleSidebar()">

☰

</button>

<div class="brand">
Veya
</div>

<div class="spacer"></div>

<button
    class="upgrade"
    onclick="openUpgrade()">

Upgrade

</button>

</header>


<section
    id="chat"
    class="chat-area">
</section>


<div class="composer-wrap">

<div class="composer">

<div
    id="modelPicker"
    class="model-picker">

<select
    id="modelSelect"
    class="model-select">
</select>

</div>


<div class="composer-row">

<button
    class="plus"
    onclick="toggleModelPicker()">

+

</button>


<textarea
    id="input"
    placeholder="Message Veya..."
    onkeydown="handleKey(event)">
</textarea>


<button
    class="send"
    onclick="sendMessage()">

↑

</button>

</div>

</div>

</div>

</main>

</div>


<div
    id="upgradeModal"
    class="modal">

<div class="modal-box">

<button
    class="close"
    onclick="closeUpgrade()">

×

</button>

<h2>
Upgrade Veya
</h2>

<p>
Choose the amount of model access you need.
</p>


<div class="plans">

<div class="plan">

<h3>
Veya Core
</h3>

<div class="price">
₹199
<small>/mo</small>
</div>

<p>
OpenAI + Google + Anthropic
</p>

<p>
Model selector included
</p>

<button
    onclick="upgrade('core')">

Choose Core

</button>

</div>


<div class="plan recommended">

<h3>
Veya All AI
</h3>

<div class="price">
₹599
<small>/mo</small>
</div>

<p>
All configured providers
</p>

<p>
Advanced model selection
</p>

<button
    onclick="upgrade('all_ai')">

Choose All AI

</button>

</div>


<div class="plan">

<h3>
Veya Ultra
</h3>

<div class="price">
₹1,499
<small>/mo</small>
</div>

<p>
Frontier/top configured models
</p>

<p>
Highest usage limits
</p>

<button
    onclick="upgrade('ultra')">

Choose Ultra

</button>

</div>

</div>

</div>

</div>


<script>

let currentChat = null;
let currentPlan = "free";
let models = [];


async function api(
    url,
    options = {}
) {

    const response =
        await fetch(
            url,
            {
                credentials:
                    "same-origin",

                ...options,

                headers: {
                    "Content-Type":
                        "application/json",

                    ...(options.headers || {})
                }
            }
        );

    const data =
        await response.json();

    if (!response.ok) {

        throw new Error(
            data.error
            || "Request failed"
        );
    }

    return data;
}


function toggleSidebar() {

    const sidebar =
        document.getElementById(
            "sidebar"
        );

    const overlay =
        document.getElementById(
            "overlay"
        );

    sidebar.classList.toggle(
        "open"
    );

    overlay.classList.toggle(
        "show",
        sidebar.classList.contains(
            "open"
        )
    );
}


function openUpgrade() {

    document
        .getElementById(
            "upgradeModal"
        )
        .classList.add(
            "show"
        );
}


function closeUpgrade() {

    document
        .getElementById(
            "upgradeModal"
        )
        .classList.remove(
            "show"
        );
}


async function loadMe() {

    const data =
        await api(
            "/api/me"
        );

    currentPlan =
        data.plan;

    document
        .getElementById(
            "account"
        )
        .textContent =
        data.plan_info.name;

    await loadModels();
}


async function loadModels() {

    const data =
        await api(
            "/api/models"
        );

    models =
        data.models || [];

    const picker =
        document.getElementById(
            "modelPicker"
        );

    const select =
        document.getElementById(
            "modelSelect"
        );

    select.innerHTML = "";

    if (!data.model_picker) {

        picker.classList.remove(
            "open"
        );

        return;
    }

    if (!models.length) {

        const option =
            document.createElement(
                "option"
            );

        option.textContent =
            "No configured models";

        select.appendChild(
            option
        );

        return;
    }

    for (
        const item
        of models
    ) {

        const option =
            document.createElement(
                "option"
            );

        option.value =
            JSON.stringify({
                provider:
                    item.provider,

                model:
                    item.model
            });

        option.textContent =
            item.provider.toUpperCase()
            + " — "
            + item.model;

        select.appendChild(
            option
        );
    }
}


function toggleModelPicker() {

    if (
        currentPlan ===
        "free"
    ) {

        openUpgrade();

        return;
    }

    document
        .getElementById(
            "modelPicker"
        )
        .classList.toggle(
            "open"
        );
}


async function loadHistory() {

    const data =
        await api(
            "/api/chats"
        );

    const history =
        document.getElementById(
            "history"
        );

    history.innerHTML = "";

    for (
        const item
        of data
    ) {

        const div =
            document.createElement(
                "div"
            );

        div.className =
            "history-item";

        div.textContent =
            item.title;

        div.onclick =
            () => openChat(
                item.id
            );

        history.appendChild(
            div
        );
    }
}


async function newChat() {

    const data =
        await api(
            "/api/chats/new",
            {
                method:
                    "POST"
            }
        );

    currentChat =
        data.chat_id;

    document
        .getElementById(
            "chat"
        )
        .innerHTML = "";

    await loadHistory();

    if (
        window.innerWidth < 700
    ) {
        toggleSidebar();
    }
}


async function openChat(
    id
) {

    currentChat = id;

    const data =
        await api(
            "/api/chats/"
            + id
        );

    const chat =
        document.getElementById(
            "chat"
        );

    chat.innerHTML = "";

    for (
        const message
        of data.messages
    ) {

        addMessage(
            message.role,
            message.content,
            message.provider,
            message.model
        );
    }

    if (
        window.innerWidth < 700
    ) {
        toggleSidebar();
    }
}


function addMessage(
    role,
    content,
    provider,
    model
) {

    const chat =
        document.getElementById(
            "chat"
        );

    const wrapper =
        document.createElement(
            "div"
        );

    wrapper.className =
        "message "
        + (
            role === "user"
            ? "user-message"
            : "assistant-message"
        );

    if (
        role === "assistant"
        && provider
        && model
    ) {

        const tag =
            document.createElement(
                "div"
            );

        tag.className =
            "model-tag";

        tag.textContent =
            provider.toUpperCase()
            + " · "
            + model;

        wrapper.appendChild(
            tag
        );
    }

    const body =
        document.createElement(
            "div"
        );

    body.textContent =
        content;

    wrapper.appendChild(
        body
    );

    chat.appendChild(
        wrapper
    );

    chat.scrollTop =
        chat.scrollHeight;
}


function handleKey(
    event
) {

    if (
        event.key === "Enter"
        && !event.shiftKey
    ) {

        event.preventDefault();

        sendMessage();
    }
}


async function sendMessage() {

    const input =
        document.getElementById(
            "input"
        );

    const text =
        input.value.trim();

    if (!text) {
        return;
    }

    input.value = "";

    addMessage(
        "user",
        text
    );

    let selected = null;

    if (
        currentPlan !== "free"
        && models.length
    ) {

        try {

            selected =
                JSON.parse(
                    document
                        .getElementById(
                            "modelSelect"
                        )
                        .value
                );

        } catch (
            error
        ) {}
    }

    try {

        const data =
            await api(
                "/api/chat",
                {
                    method:
                        "POST",

                    body:
                        JSON.stringify(
                            {
                                chat_id:
                                    currentChat,

                                message:
                                    text,

                                provider:
                                    selected
                                    ? selected.provider
                                    : null,

                                model:
                                    selected
                                    ? selected.model
                                    : null,

                                style:
                                    "balanced"
                            }
                        )
                }
            );

        currentChat =
            data.chat_id;

        addMessage(
            "assistant",
            data.answer,
            data.provider,
            data.model
        );

        await loadHistory();

    } catch (
        error
    ) {

        addMessage(
            "assistant",
            "Error: "
            + error.message
        );
    }
}


async function upgrade(
    plan
) {

    try {

        const data =
            await api(
                "/api/upgrade",
                {
                    method:
                        "POST",

                    body:
                        JSON.stringify({
                            plan:
                                plan
                        })
                }
            );

        if (
            data.configured
            && data.checkout_url
        ) {

            window.location.href =
                data.checkout_url;

            return;
        }

        alert(
            data.message
            || "Payment is not configured yet."
        );

    } catch (
        error
    ) {

        alert(
            error.message
        );
    }
}


async function boot() {

    try {

        await loadMe();

        await loadHistory();

    } catch (
        error
    ) {

        addMessage(
            "assistant",
            "Startup error: "
            + error.message
        );
    }
}


boot();

</script>

</body>

</html>
"""


# ============================================================
# HOME
# ============================================================

@app.get("/")
def home():
    uid = get_user_id()

    response = make_response(
        render_template_string(
            HTML
        )
    )

    response.set_cookie(
        "veya_user",
        uid,
        httponly=True,
        samesite="Lax",
    )

    return response


# ============================================================
# START
# ============================================================

init_db()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False,
    )
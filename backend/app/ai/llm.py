from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI

from app.core.config import settings

_OPENROUTER_BASE = "https://openrouter.ai/api/v1"


def get_llm():
    provider = settings.llm_provider.lower()

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model="gemini-2.0-flash",
            google_api_key=settings.gemini_api_key,
            temperature=0.1,
        )
    if provider == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(model="llama3.1", temperature=0.1)
    if provider == "groq":
        return ChatGroq(
            model="llama-3.3-70b-versatile",
            api_key=settings.groq_api_key,
            temperature=0.1,
        )
    if provider == "openrouter":
        return ChatOpenAI(
            model="meta-llama/llama-3.3-70b-instruct",
            openai_api_key=settings.openrouter_api_key,
            openai_api_base=_OPENROUTER_BASE,
            temperature=0.1,
        )
    raise ValueError(
        f"Unknown LLM_PROVIDER '{settings.llm_provider}' — set to gemini | groq | ollama | openrouter"
    )


def get_fast_llm():
    """Fast/cheap LLM for classification, grading, and hallucination-check nodes."""
    provider = settings.llm_provider.lower()

    if provider == "openrouter":
        return ChatOpenAI(
            model="meta-llama/llama-3.1-8b-instruct",
            openai_api_key=settings.openrouter_api_key,
            openai_api_base=_OPENROUTER_BASE,
            temperature=0.1,
        )
    if provider == "groq":
        return ChatGroq(
            model="llama-3.1-8b-instant",
            api_key=settings.groq_api_key,
            temperature=0.1,
        )
    # fallback: Gemini Flash (lazy import — only if langchain_google_genai is installed)
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model="gemini-2.0-flash",
            google_api_key=settings.gemini_api_key,
            temperature=0.1,
        )
    except ImportError:
        return ChatGroq(
            model="llama-3.1-8b-instant",
            api_key=settings.groq_api_key,
            temperature=0.1,
        )

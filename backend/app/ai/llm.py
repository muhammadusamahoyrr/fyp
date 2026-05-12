from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from langchain_ollama import ChatOllama

from app.core.config import settings


def get_llm():
    provider = settings.llm_provider.lower()

    if provider == "gemini":
        return ChatGoogleGenerativeAI(
            model="gemini-2.0-flash",
            google_api_key=settings.gemini_api_key,
            temperature=0.1,
        )
    if provider == "ollama":
        return ChatOllama(model="llama3.1", temperature=0.1)
    if provider == "groq":
        return ChatGroq(
            model="llama-3.3-70b-versatile",
            api_key=settings.groq_api_key,
            temperature=0.1,
        )
    raise ValueError(
        f"Unknown LLM_PROVIDER '{settings.llm_provider}' — set to gemini | ollama | groq"
    )


def get_fast_llm():
    """Gemini 2.0 Flash for lightweight classification/grading nodes.

    Always uses Gemini Flash regardless of LLM_PROVIDER so triage, grading,
    hallucination checks, and intent detection stay fast and cheap while
    generation_node keeps the full Groq 70B model.
    """
    return ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
        google_api_key=settings.gemini_api_key,
        temperature=0.1,
    )

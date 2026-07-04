from dataclasses import dataclass
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv:
    load_dotenv()


@dataclass(frozen=True)
class Settings:
    app_name: str = "FinFX AI Assistant"
    data_dir: Path = Path("data")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./finfx.db")
    default_base_currency: str = "GBP"
    default_quote_currencies: tuple[str, ...] = ("EUR", "USD", "AUD", "CAD", "INR")
    live_fx_base_url: str = "https://api.frankfurter.dev/v2"
    live_fx_timeout_seconds: float = 4.0
    llm_provider: str = os.getenv("LLM_PROVIDER", "ollama").lower()
    ollama_base_url: str = "http://localhost:11434"
    ollama_chat_model: str = "llama3.2:3b"
    ollama_embedding_model: str = "nomic-embed-text"
    ollama_timeout_seconds: float = 45.0
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    openai_chat_model: str = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
    anthropic_base_url: str = "https://api.anthropic.com/v1"
    anthropic_api_key: str | None = os.getenv("ANTHROPIC_API_KEY")
    anthropic_chat_model: str = os.getenv("ANTHROPIC_CHAT_MODEL", "claude-3-5-haiku-latest")
    rag_top_k: int = 3
    rag_min_vector_score: float = float(os.getenv("RAG_MIN_VECTOR_SCORE", "0.55"))
    alpha_vantage_base_url: str = "https://www.alphavantage.co/query"
    alpha_vantage_api_key: str | None = os.getenv("ALPHA_VANTAGE_API_KEY")
    fred_base_url: str = "https://api.stlouisfed.org/fred"
    fred_api_key: str | None = os.getenv("FRED_API_KEY")
    provider_timeout_seconds: float = 8.0


settings = Settings()

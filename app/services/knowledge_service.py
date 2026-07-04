import math
import re
from dataclasses import dataclass
from functools import lru_cache

from app.core.config import settings
from app.services.ollama_client import OllamaClient


@dataclass(frozen=True)
class KnowledgeChunk:
    id: str
    source: str
    heading: str
    text: str


@dataclass(frozen=True)
class EmbeddedChunk:
    chunk: KnowledgeChunk
    embedding: tuple[float, ...]


class KnowledgeService:
    def __init__(
        self, ollama_client: OllamaClient | None = None, database_service=None
    ) -> None:
        self.knowledge_dir = settings.data_dir / "knowledge"
        self.ollama_client = ollama_client or OllamaClient()
        self.database_service = database_service

    @lru_cache(maxsize=1)
    def chunks(self) -> tuple[KnowledgeChunk, ...]:
        """Load synthetic markdown knowledge and split it into small retrievable sections."""
        chunks: list[KnowledgeChunk] = []
        for path in sorted(self.knowledge_dir.glob("*.md")):
            content = path.read_text(encoding="utf-8")
            for index, section in enumerate(re.split(r"\n(?=## )", content)):
                cleaned = section.strip()
                if not cleaned:
                    continue
                heading = self._extract_heading(cleaned)
                chunks.append(
                    KnowledgeChunk(
                        id=f"{path.stem}-{index}",
                        source=path.name,
                        heading=heading,
                        text=cleaned,
                    )
                )
        return tuple(chunks)

    @lru_cache(maxsize=1)
    def embedded_chunks(self) -> tuple[EmbeddedChunk, ...]:
        """Create local in-memory embeddings as a fallback when pgvector is unavailable."""
        embedded: list[EmbeddedChunk] = []
        for chunk in self.chunks():
            embedding = self.ollama_client.embed(chunk.text)
            if embedding:
                embedded.append(EmbeddedChunk(chunk=chunk, embedding=tuple(embedding)))
        return tuple(embedded)

    def answer(self, question: str, use_llm: bool = True) -> dict:
        """Retrieve relevant knowledge chunks, then optionally ask the LLM for a grounded answer."""
        retrieved, retrieval_mode = self.retrieve(question)
        if not retrieved:
            return {
                "answer": (
                    "I could not find relevant FinFX knowledge for that question. "
                    "I can help with transfers, verification policy, compliance checks, FX rates, and transaction reports."
                ),
                "citations": [],
                "mode": "no-context",
                "retrieved_chunks": [],
                "llm_available": False,
            }

        generated_answer = None
        if use_llm:
            generated_answer = self._generate_grounded_answer(
                question, [chunk for _, chunk in retrieved]
            )

        if generated_answer:
            mode = (
                "ollama-pgvector-rag"
                if retrieval_mode == "supabase-pgvector-rag"
                else "ollama-rag"
            )
            answer = generated_answer
            llm_available = True
        else:
            mode = retrieval_mode
            answer = self._extractive_answer([chunk for _, chunk in retrieved])
            llm_available = False

        citations = [chunk.source for _, chunk in retrieved]
        return {
            "answer": answer,
            "citations": citations,
            "mode": mode,
            "llm_available": llm_available,
            "retrieved_chunks": [
                {
                    "source": chunk.source,
                    "heading": chunk.heading,
                    "score": round(score, 4),
                    "preview": self._preview(chunk.text),
                }
                for score, chunk in retrieved
            ],
        }

    def index_vector_store(self) -> dict:
        """Embed markdown knowledge and persist it into Supabase pgvector for RAG search."""
        if not self.database_service:
            return {
                "indexed": False,
                "message": "No database service is configured for vector indexing.",
                "chunks_indexed": 0,
            }

        indexed = 0
        skipped = 0
        status = self.database_service.vector_status()
        if not status["available"]:
            return {"indexed": False, "chunks_indexed": 0, "database_status": status}

        for chunk in self.chunks():
            embedding = self.ollama_client.embed(chunk.text)
            if not embedding:
                skipped += 1
                continue
            self.database_service.upsert_knowledge_chunk(
                {
                    "id": chunk.id,
                    "source": chunk.source,
                    "heading": chunk.heading,
                    "text": chunk.text,
                },
                embedding,
            )
            indexed += 1

        return {
            "indexed": indexed > 0,
            "chunks_indexed": indexed,
            "chunks_skipped": skipped,
            "database_status": self.database_service.vector_status(),
        }

    def vector_status(self) -> dict:
        if not self.database_service:
            return {
                "available": False,
                "message": "No database service is configured for vector search.",
            }
        return self.database_service.vector_status()

    def retrieve(self, question: str) -> tuple[list[tuple[float, KnowledgeChunk]], str]:
        """Search pgvector first, then fall back to local semantic search or keyword matching."""
        query_embedding = self.ollama_client.embed(question)
        if query_embedding and self.database_service:
            vector_result = self.database_service.search_knowledge_chunks(
                query_embedding, settings.rag_top_k
            )
            vector_chunks = [
                (
                    float(row["score"]),
                    KnowledgeChunk(
                        id=row["id"],
                        source=row["source"],
                        heading=row["heading"],
                        text=row["text"],
                    ),
                )
                for row in vector_result.get("chunks", [])
            ]
            if vector_chunks:
                return (
                    self._filter_relevant_chunks(vector_chunks),
                    "supabase-pgvector-rag",
                )

        embedded = self.embedded_chunks() if query_embedding else ()

        if query_embedding and embedded:
            scored = [
                (
                    self._cosine_similarity(
                        tuple(query_embedding), embedded_chunk.embedding
                    ),
                    embedded_chunk.chunk,
                )
                for embedded_chunk in embedded
            ]
            scored.sort(key=lambda item: item[0], reverse=True)
            return (
                self._filter_relevant_chunks(scored[: settings.rag_top_k]),
                "semantic-retrieval",
            )

        return self._keyword_retrieve(question), "keyword-retrieval"

    def _generate_grounded_answer(
        self, question: str, chunks: list[KnowledgeChunk]
    ) -> str | None:
        context = "\n\n".join(
            f"Source: {chunk.source} | Section: {chunk.heading}\n{chunk.text}"
            for chunk in chunks
        )
        prompt = f"""You are FinFX AI Assistant, a fintech operations copilot.
Answer the user's question using only the context below.
If the context is insufficient, say what is missing.
Keep the answer concise, practical, and suitable for a payments operations user.
Mention source filenames at the end under 'Sources'.

Context:
{context}

Question: {question}

Answer:"""
        return self.ollama_client.generate(prompt)

    def _keyword_retrieve(self, question: str) -> list[tuple[float, KnowledgeChunk]]:
        query_terms = self._tokenize(question)
        scored = []
        for chunk in self.chunks():
            chunk_terms = self._tokenize(chunk.text)
            score = len(query_terms.intersection(chunk_terms))
            if score:
                scored.append((float(score), chunk))
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored[: settings.rag_top_k]

    @staticmethod
    def _filter_relevant_chunks(
        scored_chunks: list[tuple[float, KnowledgeChunk]],
    ) -> list[tuple[float, KnowledgeChunk]]:
        return [
            (score, chunk)
            for score, chunk in scored_chunks
            if score >= settings.rag_min_vector_score
        ]

    @staticmethod
    def _extractive_answer(chunks: list[KnowledgeChunk]) -> str:
        return " ".join(chunk.text.replace("\n", " ") for chunk in chunks)

    @staticmethod
    def _extract_heading(section: str) -> str:
        first_line = section.splitlines()[0].strip("# ").strip()
        return first_line or "Knowledge section"

    @staticmethod
    def _preview(text: str) -> str:
        normalized = " ".join(text.split())
        return normalized[:220] + ("..." if len(normalized) > 220 else "")

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        stop_words = {
            "the",
            "is",
            "a",
            "an",
            "to",
            "for",
            "and",
            "or",
            "of",
            "in",
            "what",
            "how",
        }
        return {
            token
            for token in re.findall(r"[a-zA-Z0-9]+", text.lower())
            if token not in stop_words
        }

    @staticmethod
    def _cosine_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
        if len(left) != len(right) or not left or not right:
            return 0.0
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(a * a for a in left))
        right_norm = math.sqrt(sum(b * b for b in right))
        if not left_norm or not right_norm:
            return 0.0
        return dot / (left_norm * right_norm)

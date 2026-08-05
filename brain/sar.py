"""
brain/sar.py — Semantically Aware Reasoning (SAR) Engine for EMO
================================================================
Implements a dual-process architecture inspired by the paper:
"Enhancing Large Language Models: Alleviating Knowledge Deficiency with SAR"

System 1 = LLM (fast, fluent language generation)
System 2 = SAR (semantic grounding in a curated knowledge base)

The SAR engine uses TF-IDF + cosine similarity to match user queries
against a curated knowledge base, returning the best-matching answer
to inject as context into the LLM prompt. This grounds EMO's responses
in verified facts, reducing hallucination.

Lightweight: pure Python with sklearn. No GPU needed.
"""

import os
import re
import json
import math
from pathlib import Path
from collections import Counter

# ── Paths ────────────────────────────────────────────────────────────────────
HERE = Path(__file__).resolve().parent
KB_PATH = HERE / "knowledge_base.json"

# ── Confidence threshold ────────────────────────────────────────────────────
# Queries scoring above this are considered "grounded" matches.
SAR_THRESHOLD = 0.58


# ══════════════════════════════════════════════════════════════════════════════
# LIGHTWEIGHT TF-IDF ENGINE (no sklearn dependency needed)
# ══════════════════════════════════════════════════════════════════════════════

# Common English stop words to ignore in similarity matching
_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "it", "of", "in", "to", "and", "or", "for",
    "on", "at", "by", "you", "your", "my", "me", "i", "we", "us",
    "he", "she", "they", "them", "this", "that", "what", "which", "who",
    "how", "can", "could", "will", "would", "should", "may", "be", "been",
    "being", "have", "has", "had", "was", "were", "are", "am", "does",
    "did", "do", "not", "no", "but", "if", "so", "as", "with", "about", "from",
    "up", "out", "just", "also", "very", "too", "more", "than", "then",
    "there", "here", "all", "some", "any", "each", "every", "own",
    "please", "tell", "know", "give", "show", "get", "way",
})

# Direct phrase mapping for ultra-short queries that get stripped by stop words
_PHRASE_MAPPINGS = {
    "who are you": "What is EMO?",
    "what are you": "What is EMO?",
    "who made you": "Who created EMO?",
    "who built you": "Who created EMO?",
    "who is your creator": "Who created EMO?",
    "are you an ai": "Are you an AI?",
    "are you ai": "Are you an AI?",
    "are you chatgpt": "Are you an AI?",
    "are you a chatbot": "Are you an AI?",
    "what can you do": "What can EMO do?",
    "what are your features": "What can EMO do?",
}


def _tokenize(text: str) -> list[str]:
    """Lowercase, strip non-alphanumeric, remove stop words."""
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return [t for t in tokens if t not in _STOP_WORDS and len(t) > 1]


def _build_idf(documents: list[list[str]]) -> dict[str, float]:
    """Compute inverse document frequency for each term."""
    n = len(documents)
    if n == 0:
        return {}
    df = Counter()
    for doc in documents:
        df.update(set(doc))
    return {term: math.log((n + 1) / (freq + 1)) + 1 for term, freq in df.items()}


def _tfidf_vector(tokens: list[str], idf: dict[str, float]) -> dict[str, float]:
    """Compute TF-IDF vector for a single document."""
    tf = Counter(tokens)
    total = len(tokens) if tokens else 1
    return {term: (count / total) * idf.get(term, 1.0) for term, count in tf.items()}


def _cosine_similarity(v1: dict[str, float], v2: dict[str, float]) -> float:
    """Cosine similarity between two sparse TF-IDF vectors."""
    shared_terms = set(v1.keys()) & set(v2.keys())
    if not shared_terms:
        return 0.0
    dot = sum(v1[t] * v2[t] for t in shared_terms)
    mag1 = math.sqrt(sum(x * x for x in v1.values()))
    mag2 = math.sqrt(sum(x * x for x in v2.values()))
    if mag1 == 0 or mag2 == 0:
        return 0.0
    return dot / (mag1 * mag2)


# ══════════════════════════════════════════════════════════════════════════════
# SAR ENGINE CLASS
# ══════════════════════════════════════════════════════════════════════════════

class SAREngine:
    """
    Semantically Aware Reasoning engine.
    
    Loads a curated knowledge base and matches user queries against it
    using TF-IDF cosine similarity. Returns the best answer + confidence.
    """

    def __init__(self, kb_path: str | Path = KB_PATH):
        self.entries: list[dict] = []
        self._doc_tokens: list[list[str]] = []  # tokenized questions for each entry
        self._idf: dict[str, float] = {}
        self._doc_vectors: list[dict[str, float]] = []
        self._loaded = False

        if Path(kb_path).exists():
            self.load(kb_path)

    def load(self, kb_path: str | Path = KB_PATH):
        """Load knowledge base from JSON and build TF-IDF index."""
        try:
            with open(kb_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.entries = data.get("entries", [])
            self._build_index()
            self._loaded = True
            print(f"[SAR] Loaded {len(self.entries)} knowledge entries from {kb_path}")
        except Exception as e:
            print(f"[SAR] Failed to load knowledge base: {e}")
            self.entries = []
            self._loaded = False

    def _build_index(self):
        """Build TF-IDF index from all questions (original + alternatives)."""
        self._doc_tokens = []
        self._doc_map = []  # Index -> parent entry index
        for entry_idx, entry in enumerate(self.entries):
            all_questions = [entry.get("q", "")]
            all_questions.extend(entry.get("alt_q", []))
            for q_str in all_questions:
                if q_str.strip():
                    tokens = _tokenize(q_str)
                    if tokens:
                        self._doc_tokens.append(tokens)
                        self._doc_map.append(entry_idx)

        self._idf = _build_idf(self._doc_tokens)
        self._doc_vectors = [_tfidf_vector(doc, self._idf) for doc in self._doc_tokens]

    def query(self, user_text: str, threshold: float = SAR_THRESHOLD) -> tuple[str | None, float, dict | None]:
        """
        Match a user query against the knowledge base.

        Returns:
            (answer, confidence, entry) — the best match, or (None, 0.0, None) if below threshold.
        """
        if not self._loaded or not self.entries or not self._doc_vectors:
            return None, 0.0, None

        # 1. Fast Phrase Mapping check
        clean_raw = re.sub(r"[^\w\s]", "", user_text.lower()).strip()
        if clean_raw in _PHRASE_MAPPINGS:
            target_q = _PHRASE_MAPPINGS[clean_raw]
            for entry in self.entries:
                if entry.get("q") == target_q:
                    return entry.get("a", ""), 1.0, entry

        query_tokens = _tokenize(user_text)
        if not query_tokens:
            return None, 0.0, None

        query_vec = _tfidf_vector(query_tokens, self._idf)

        best_score = 0.0
        best_doc_idx = -1

        for i, doc_vec in enumerate(self._doc_vectors):
            score = _cosine_similarity(query_vec, doc_vec)
            if score > best_score:
                best_score = score
                best_doc_idx = i

        if best_score >= threshold and best_doc_idx >= 0:
            parent_entry_idx = self._doc_map[best_doc_idx]
            entry = self.entries[parent_entry_idx]
            return entry.get("a", ""), best_score, entry

        return None, best_score, None

    def add_entry(self, q: str, a: str, alt_q: list[str] | None = None, tags: list[str] | None = None):
        """Add a new entry to the knowledge base at runtime and rebuild the index."""
        entry = {"q": q, "a": a}
        if alt_q:
            entry["alt_q"] = alt_q
        if tags:
            entry["tags"] = tags
        self.entries.append(entry)
        self._build_index()

    def save(self, kb_path: str | Path = KB_PATH):
        """Persist the current knowledge base to JSON."""
        try:
            with open(kb_path, "w", encoding="utf-8") as f:
                json.dump({"entries": self.entries}, f, indent=2, ensure_ascii=False)
            print(f"[SAR] Saved {len(self.entries)} entries to {kb_path}")
        except Exception as e:
            print(f"[SAR] Failed to save knowledge base: {e}")

    def get_context_for_llm(self, user_text: str) -> str:
        """
        Get SAR knowledge context to inject into the LLM prompt.
        
        Returns a context string if a match is found, or empty string.
        This implements the System 2 reasoning from the SAR paper —
        grounding the LLM (System 1) in verified facts.
        """
        answer, confidence, entry = self.query(user_text)
        if answer:
            tags = ", ".join(entry.get("tags", [])) if entry else ""
            return (
                f"\n\n[KNOWLEDGE CONTEXT (SAR confidence={confidence:.2f}, tags={tags})]:\n"
                f"{answer}\n"
                f"Use this grounded knowledge to inform your response. "
                f"Do not contradict this information."
            )
        return ""


# ── Module-level singleton ──────────────────────────────────────────────────
# Import this directly: `from brain.sar import engine`
engine = SAREngine()

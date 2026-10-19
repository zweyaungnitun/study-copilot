from typing import Any, Dict, List, Optional
from app.core.rag_store import rag_store


class RAGService:
    SIMILARITY_THRESHOLD = 0.65

    @classmethod
    def query_user_knowledge(
        cls,
        user_id: str,
        query: str,
        top_k: int = 3,
    ) -> Dict[str, Any]:
        """
        Dual-source retrieval logic:
        Checks uploaded materials first. If similarity score >= 0.65, attributes to user's notes.
        Otherwise falls back to general knowledge.
        """
        matches = rag_store.search(
            user_id=user_id,
            query=query,
            top_k=top_k,
            similarity_threshold=cls.SIMILARITY_THRESHOLD,
        )

        if matches:
            sources = [
                {
                    "filename": m["filename"],
                    "page_number": m["page_number"],
                    "score": m["score"],
                    "citation": f"[File: {m['filename']}, Page: {m['page_number']}]",
                }
                for m in matches
            ]
            context_blocks = "\n\n".join(
                f"--- Excerpt from {m['filename']} (p. {m['page_number']}) ---\n{m['text']}"
                for m in matches
            )
            return {
                "badge": "📚 From your notes",
                "is_grounded_in_notes": True,
                "sources": sources,
                "context_text": context_blocks,
                "top_score": matches[0]["score"],
            }

        return {
            "badge": "🌐 General knowledge",
            "is_grounded_in_notes": False,
            "sources": [],
            "context_text": "",
            "top_score": 0.0,
        }

    @classmethod
    def build_prompt_with_grounding(
        cls,
        user_id: str,
        query: str,
        system_instruction: str,
    ) -> Dict[str, Any]:
        """Wrap system prompt and user query with retrieved student notes context."""
        retrieval = cls.query_user_knowledge(user_id=user_id, query=query)

        if retrieval["is_grounded_in_notes"]:
            augmented_instruction = (
                f"{system_instruction}\n\n"
                f"<STUDENT_NOTES>\n"
                f"The student uploaded the following verified course materials. "
                f"PRIORITIZE these notes when answering, and cite the file and page number:\n"
                f"{retrieval['context_text']}\n"
                f"</STUDENT_NOTES>"
            )
        else:
            augmented_instruction = system_instruction

        return {
            "augmented_instruction": augmented_instruction,
            "badge": retrieval["badge"],
            "sources": retrieval["sources"],
            "is_grounded": retrieval["is_grounded_in_notes"],
        }

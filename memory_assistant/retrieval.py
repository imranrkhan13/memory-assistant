
"""Phase 3 retrieval with Phase 4 relevance corrections."""

import re

from .storage import DEFAULT_USER_ID, get_connection

UNKNOWN = "I don't know"
CONTEXT_BUDGET = 2000

STOP_WORDS = {
    "a", "an", "the", "is", "are", "was", "were",
    "i", "my", "me", "you", "your", "did", "do",
    "does", "what", "when", "where", "why", "how",
    "which", "who", "of", "to", "in", "on", "at",
    "for", "and", "or", "it", "that", "this",
    "because", "with", "from", "have", "has",
    "about", "tell", "please", "fictional",
    "sample", "saved", "remember",
}

ADVICE_TOPICS = {
    "medical", "medicine", "diagnose", "diagnosis",
    "treatment", "legal", "lawsuit", "lawyer",
    "investment", "invest", "financial", "tax",
    "prescribe", "should",
}


def tokens(text):
    return {
        word
        for word in re.findall(r"[a-z0-9]+", text.lower())
        if word not in STOP_WORDS
    }


def retrieve(question, user_id=DEFAULT_USER_ID):
    """Rank active facts using their original source notes."""
    query_words = tokens(question)

    if not query_words:
        return []

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT f.id AS fact_id,
                   f.statement,
                   f.note_id,
                   n.raw_text,
                   n.created_at,
                   f.confidence
            FROM facts f
            JOIN notes n
              ON n.id = f.note_id
             AND n.user_id = f.user_id
            WHERE f.user_id = ?
              AND f.status = 'active'
            ORDER BY f.id
            """,
            (user_id,),
        ).fetchall()

    matches = []

    for row in rows:
        fact = dict(row)

        # The original note is authoritative for relevance.
        # Do not use generated fixture text to match a question.
        source_words = tokens(fact["raw_text"])
        overlap = query_words & source_words

        if not overlap:
            continue

        fact["score"] = len(overlap)
        matches.append(fact)

    matches.sort(
        key=lambda item: (-item["score"], item["fact_id"])
    )

    return matches


def select_context(matches, budget=CONTEXT_BUDGET):
    """Select source material within a character budget."""
    if budget < 0:
        raise ValueError("Context budget cannot be negative.")

    selected = []
    dropped = []
    used = 0

    for fact in matches:
        size = len(fact["statement"]) + len(fact["raw_text"])

        if used + size <= budget:
            selected.append(fact)
            used += size
        else:
            dropped.append(fact["fact_id"])

    return {
        "selected": selected,
        "dropped": dropped,
        "used": used,
        "budget": budget,
    }


def supported_claim(statement, source):
    """Conservative lexical check, not semantic verification."""
    claim_words = tokens(statement)
    source_words = tokens(source)

    if not claim_words:
        return False

    return claim_words.issubset(source_words)


def validate_answer(response, retrieved):
    """Reject absent, invented or lexically unsupported claims."""
    if not isinstance(response, dict):
        return False, "Invalid response format"

    claims = response.get("claims")

    if not isinstance(claims, list) or not claims:
        return False, "Missing claims or citations"

    allowed = {
        item["note_id"]: item
        for item in retrieved
    }

    for claim in claims:
        if not isinstance(claim, dict):
            return False, "Invalid claim"

        note_id = claim.get("note_id")
        statement = claim.get("statement")

        if (
            not isinstance(note_id, int)
            or isinstance(note_id, bool)
            or note_id not in allowed
        ):
            return False, "Invented or missing citation"

        if not isinstance(statement, str) or not statement.strip():
            return False, "Empty claim"

        source = allowed[note_id]

        if not supported_claim(statement, source["raw_text"]):
            return False, "Unsupported claim"

    return True, "Valid"


def is_advice_question(question):
    return bool(tokens(question) & ADVICE_TOPICS)


def ask(
    question,
    provider,
    user_id=DEFAULT_USER_ID,
    budget=CONTEXT_BUDGET,
):
    """Return source-linked claims or exactly 'I don't know'."""
    matches = retrieve(question, user_id)
    context = select_context(matches, budget)

    result = {
        "answer": UNKNOWN,
        "sources": [],
        "context": {
            "included": [
                item["fact_id"]
                for item in context["selected"]
            ],
            "dropped": context["dropped"],
            "characters": context["used"],
            "budget": context["budget"],
        },
        "validation": "No relevant active facts",
    }

    if not context["selected"]:
        return result

    response = provider.answer(
        question,
        context["selected"],
    )

    valid, reason = validate_answer(
        response,
        context["selected"],
    )

    if not valid:
        result["validation"] = reason
        return result

    claims = response["claims"]

    # Construct the answer only from validated claims.
    result["answer"] = " ".join(
        claim["statement"] for claim in claims
    )

    selected_by_note = {
        item["note_id"]: item
        for item in context["selected"]
    }

    seen = set()

    for claim in claims:
        note_id = claim["note_id"]

        if note_id in seen:
            continue

        seen.add(note_id)
        source = selected_by_note[note_id]

        result["sources"].append({
            "note_id": note_id,
            "date": source["created_at"],
            "text": source["raw_text"],
        })

    if is_advice_question(question):
        result["answer"] += (
            " I can retrieve saved notes, but cannot provide "
            "medical, legal, or financial advice."
        )

    result["validation"] = "Passed rough lexical support check"

    return result

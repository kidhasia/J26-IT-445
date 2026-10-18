"""Evidence-grounded question answering.

A tiny, rule-based feature: it answers simple factual questions about ONE analysis result that the caller supplies
(the JSON that POST /api/v1/analyze returned). It uses no language model, makes no network calls, stores nothing, and
never answers from anything except the supplied evidence. It is not a medical chatbot.
"""

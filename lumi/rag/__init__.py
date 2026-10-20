"""Extractive retrieval demo (phase 1 of a retrieval-augmented question answering feature).

What it is: a local TF-IDF search over a small, listed set of LUMI project documents. It returns the best-matching
passages word for word, with a citation for each. No language model writes any text, nothing is sent over the network,
and nothing is stored.

What it is not: a generative RAG system, a medical knowledge base, or medical advice. The documents are the project's
own write-ups, not approved clinical sources.
"""

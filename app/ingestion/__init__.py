"""Knowledge-base ingestion: source files in, retrievable chunks out.

Deliberately independent of any embedding provider. Ingestion can be built,
tested and re-run thousands of times during the chunking experiments (KAN-19)
without an API key or a penny of cost. Embeddings attach to the stored chunks
in KAN-20.
"""

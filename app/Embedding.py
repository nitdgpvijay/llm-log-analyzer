import os
from langchain_openai import OpenAIEmbeddings

def getEmbeddings():
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small", dimensions=1536, chunk_size=50,
     api_key=os.getenv("OPENAI_API_KEY"), retry_min_seconds=2)
    return embeddings
import os
from langchain_openai import ChatOpenAI

def get_llm(model="gpt-4o-mini", temperature=0):
    if not os.environ.get("OPENAI_API_KEY"):
        raise ValueError("OPENAI_API_KEY is not set")
    return ChatOpenAI(model=model, temperature=temperature, api_key=os.environ.get("OPENAI_API_KEY"))
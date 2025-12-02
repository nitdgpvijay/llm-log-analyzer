import os
from dotenv import load_dotenv  

def main():
    load_dotenv()
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        raise ValueError("OPENAI_API_KEY is not set")
    print("Hello from langchain-course!")


if __name__ == "__main__":
    main()

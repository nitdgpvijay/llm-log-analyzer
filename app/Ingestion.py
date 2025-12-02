import hashlib, json, time, os
from langchain_pinecone import PineconeVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from Embedding import getEmbeddings
from dotenv import load_dotenv
from LogsProvider import LogsProvider

splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)

def make_point_id(line_text, ts, labels, idx):
    h = hashlib.sha1()
    h.update((str(ts) + json.dumps(labels, sort_keys=True) + line_text[:200]).encode())
    h.update(str(idx).encode())
    return h.hexdigest()


def ingest_logs(logs):
    print(f"Ingesting {len(logs)} logs")
    # build chunks
    docs = []
    metadatas = []
    ids = []
    for i, l in enumerate(logs):
        print(f"Ingesting log {i}: {l}")
        chunks = splitter.split_text(l["message"])
        for j, chunk in enumerate(chunks):
            meta = {"orig_ts": l["timestamp"], "labels": l["level"]}
            docs.append(chunk)
            metadatas.append(meta)
            ids.append(make_point_id(chunk, l["timestamp"], l["level"], j))

    if not docs:
        print("No documents to ingest")
        return

    #chroma_client = Chroma(persist_directory="chroma_db", embedding_function=getEmbeddings())
    # ingest into Pinecone
    PineconeVectorStore.from_texts(texts=docs, embedding=getEmbeddings(), index_name=os.getenv("PINECONE_INDEX_NAME"), metadatas=metadatas, ids=ids, namespace=os.getenv("PINECONE_NAMESPACE"), text_key="text" )
    return {"indexed": len(docs)}


def main():
    load_dotenv()
    logs_provider = LogsProvider(os.getenv("LOKI_API_KEY"), os.getenv("LOKI_URL"))
    state = {"query": '{namespace="dev-group2", app="cloud-radius"}'}
    logs = logs_provider.get_logs(state)
    logs_provider.normalize_logs(state)
    result = ingest_logs(state["clean_logs"])
    print(result)

if __name__ == "__main__":
    main()
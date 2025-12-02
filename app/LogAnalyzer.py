import os
from LogsProvider import LogsProvider
from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END
from langchain_openai import ChatOpenAI
from IPython.display import Markdown, display
from llm import get_llm
from Embedding import getEmbeddings

class LogAnalyzer:
    def __init__(self):
        self.loki_url = os.getenv("LOKI_URL")
        self.loki_api_key = os.getenv("LOKI_API_KEY", "Bearer ")
        self.logs_provider = LogsProvider(self.loki_api_key, self.loki_url)
        self.embedding = getEmbeddings()
    def anomaly_detector(self, state):
        errors = []
        for line in state["clean_logs"]:
            if "Exception" in line or "ERROR" in line:
                errors.append(line)
        state["anomalies"] = errors
        return state


    def rca_model(self, state):
        messages = [
            ("system", "You are an expert cloud debugging assistant."),
            ("user", f"Logs:\n{state['clean_logs']}\nAnomalies:\n{state['anomalies']}")
        ]
        result = state["llm"].invoke(messages)
        state["answer"] = result
        return state

def main():
    load_dotenv()
    log_analyzer = LogAnalyzer()
    workflow = StateGraph(dict)
    workflow.add_node("get_logs", log_analyzer.logs_provider.get_logs)
    workflow.add_node("normalize_logs", log_analyzer.logs_provider.normalize_logs)
    workflow.add_node("anomaly_detector", log_analyzer.anomaly_detector)
    workflow.add_node("rca_model", log_analyzer.rca_model)

    workflow.set_entry_point("get_logs")
    workflow.add_edge("get_logs", "normalize_logs")
    workflow.add_edge("normalize_logs", "anomaly_detector")
    workflow.add_edge("anomaly_detector", "rca_model")
    workflow.set_finish_point("rca_model")
    graphApp = workflow.compile()

    llm = get_llm()
    result = graphApp.invoke({
        "query": '{namespace="dev-group2", app="cloud-radius"}',
        "llm": llm,
    })
    markdown_content = Markdown(result.get("answer").content).data
    with open("log_analysis_result.md", "w", encoding="utf-8") as f:
        f.write(markdown_content)
if __name__ == "__main__":
    main()
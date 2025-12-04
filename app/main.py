from dotenv import load_dotenv  
import streamlit as st
from Chain import query_logs

# Load environment variables
load_dotenv()
st.header("AI-Powered Unified Log Tracing for Cloud Services")

if "user_prompt_history" not in st.session_state:
    st.session_state.user_prompt_history = []

if "query_ans_history" not in st.session_state:
    st.session_state.query_ans_history = []

def analyze_logs(query: str) -> str:
    result = query_logs(query)
    st.session_state.user_prompt_history.append(query)
    st.session_state.query_ans_history.append(result)
    return result

def main():
    query = st.text_input("Query", placeholder="Enter your query here..")
    if query:
        with st.spinner("Analyzing..."):
            analyze_logs(query)

    for query, result in zip(
        reversed(st.session_state.user_prompt_history),
        reversed(st.session_state.query_ans_history)
    ):
        st.chat_message("user").markdown(query)
        st.chat_message("assistant").markdown(result)

if __name__ == "__main__":
    main()

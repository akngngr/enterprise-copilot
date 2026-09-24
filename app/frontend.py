import streamlit as st
import requests
import os

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")

st.set_page_config(
    page_title="Enterprise Copilot",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Tailwind-inspired CSS injection for a sleek, React/SaaS aesthetic
st.markdown("""
    <style>
        .stApp {
            background-color: #0e1117;
            color: #f3f4f6;
        }
        .app-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 1rem 1.5rem;
            background: #161b22;
            border-radius: 12px;
            border: 1px solid #30363d;
            margin-bottom: 2rem;
        }
        .stChatMessage {
            background-color: #161b22;
            border: 1px solid #30363d;
            border-radius: 12px;
            padding: 1rem;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        }
        [data-testid="stSidebar"] {
            background-color: #0d1117;
            border-right: 1px solid #30363d;
        }
        [data-testid="stMetric"] {
            background-color: #161b22;
            padding: 12px;
            border-radius: 8px;
            border: 1px solid #30363d;
        }
    </style>
""", unsafe_allow_html=True)

# Sleek SaaS Header Component
st.markdown("""
    <div class="app-header">
        <div>
            <h2 style="margin: 0; font-size: 1.5rem; font-weight: 600; color: #ffffff;">⚡ Enterprise Copilot</h2>
            <p style="margin: 0; font-size: 0.85rem; color: #8b949e;">Secure RAG Intelligence & Knowledge Engine</p>
        </div>
    </div>
""", unsafe_allow_html=True)

# Sidebar Design
with st.sidebar:
    st.markdown("### 🎛️ Control Center")
    
    try:
        requests.get(f"{API_BASE_URL}/docs", timeout=2)
        st.metric(label="API Gateway", value="Online", delta="Operational")
    except Exception:
        st.metric(label="API Gateway", value="Offline", delta="Disconnected", delta_color="inverse")

    st.divider()
    
    st.markdown("### 📂 Data Ingestion")
    uploaded_file = st.file_uploader("Upload PDF Reference", type=["pdf"], label_visibility="collapsed")

    if uploaded_file is not None:
        if st.button("🚀 Ingest & Vectorize", use_container_width=True):
            with st.spinner("Processing document chunks..."):
                try:
                    files = {"file": (uploaded_file.name, uploaded_file.getvalue(), "application/pdf")}
                    response = requests.post(f"{API_BASE_URL}/ingest/", files=files)
                    if response.status_code == 200:
                        st.success(f"Indexed: {uploaded_file.name}")
                    else:
                        st.error(f"Error: {response.json().get('detail', response.text)}")
                except Exception as e:
                    st.error(f"Connection failed: {str(e)}")

    st.divider()
    if st.button("🗑️ Clear Session", use_container_width=True):
        st.session_state.messages = []
        st.rerun()

# Chat Workspace with Modern Avatars
if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    avatar = "👤" if message["role"] == "user" else "✨"
    with st.chat_message(message["role"], avatar=avatar):
        st.markdown(message["content"])

if prompt := st.chat_input("Ask anything about your internal knowledge base..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user", avatar="👤"):
        st.markdown(prompt)

    with st.chat_message("assistant", avatar="✨"):
        with st.spinner("Retrieving context & synthesizing response..."):
            try:
                history_payload = [
                    {"role": msg["role"], "content": msg["content"]}
                    for msg in st.session_state.messages[:-1]
                ]

                response = requests.post(
                    f"{API_BASE_URL}/ask/", 
                    json={"question": prompt, "history": history_payload}
                )

                if response.status_code == 200:
                    data = response.json()
                    answer = data.get("answer", "No answer returned.")
                    sources = data.get("sources", [])

                    st.markdown(answer)

                    if sources:
                        with st.expander("🔗 Verified Knowledge Sources"):
                            for idx, src in enumerate(sources):
                                st.markdown(f"**[{idx+1}] {src['source_filename']}** (Chunk {src['chunk_index']})")
                                st.caption(f"Relevance Score: {src['similarity']:.2f}")
                                st.code(src['content'], language="text")
                                st.divider()

                    st.session_state.messages.append({"role": "assistant", "content": answer})
                else:
                    st.error(f"Error: {response.json().get('detail', response.text)}")
            except Exception as e:
                st.error(f"Network error: {e}")
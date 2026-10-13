import os
import time
from urllib.parse import urlparse

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
api_url = urlparse(API_BASE_URL)
if not api_url.hostname or (
    api_url.scheme != "https"
    and api_url.hostname not in {"localhost", "127.0.0.1", "::1"}
):
    raise RuntimeError("API_BASE_URL must use HTTPS outside local development")

st.set_page_config(
    page_title="Enterprise Copilot",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

if not st.user.is_logged_in:
    st.title("Enterprise Copilot")
    st.write("Sign in to access your private knowledge context.")
    if st.button("Sign in", type="primary"):
        st.login()
    st.stop()

user_info = st.user.to_dict()
expires_at = user_info.get("exp")
if expires_at and time.time() >= float(expires_at):
    st.logout()
    st.stop()

try:
    id_token = st.user.tokens["id"]
except KeyError:
    st.error("The identity provider did not return an ID token.")
    st.stop()

subject = user_info.get("sub")
if not isinstance(subject, str) or not subject:
    st.error("The identity provider did not return a user subject.")
    st.logout()
    st.stop()

if st.session_state.get("context_owner") != subject:
    st.session_state.context_owner = subject
    st.session_state.messages = []

AUTH_HEADERS = {"Authorization": f"Bearer {id_token}"}


def api_request(method: str, path: str, **kwargs):
    return requests.request(
        method,
        f"{API_BASE_URL}{path}",
        headers=AUTH_HEADERS,
        timeout=120,
        **kwargs,
    )


def response_detail(response) -> str:
    try:
        return response.json().get("detail", response.text)
    except ValueError:
        return response.text


st.markdown(
    """
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
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="app-header">
        <div>
            <h2 style="margin: 0; font-size: 1.5rem; font-weight: 600; color: #ffffff;">⚡ Enterprise Copilot</h2>
            <p style="margin: 0; font-size: 0.85rem; color: #8b949e;">Secure RAG Intelligence & Knowledge Engine</p>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown("### 🎛️ Control Center")
    st.caption(f"Signed in as {user_info.get('email', subject)}")

    # Probe /health, not /docs. /docs answers whenever uvicorn is alive, so it
    # reported "Online" through a dead database. /health checks the database and
    # the generator, and returns 503 when either is down.
    api_state = "Offline"
    api_note = "Disconnected"
    try:
        probe = requests.get(f"{API_BASE_URL}/health", timeout=5)
        report = probe.json()
        if report.get("status") == "ok":
            api_state, api_note = "Online", "Operational"
        else:
            broken = [
                name
                for name in ("database", "generator")
                if report.get(name, {}).get("status") == "error"
            ]
            api_state = "Degraded"
            api_note = f"{', '.join(broken)} unreachable"
    except (requests.RequestException, ValueError):
        pass

    st.metric(
        label="API Gateway",
        value=api_state,
        delta=api_note,
        delta_color="normal" if api_state == "Online" else "inverse",
    )

    st.divider()
    st.markdown("### 📂 Data Ingestion")
    st.caption(
        "Your workspace. Uploading a PDF replaces the default profile, and it "
        "stays private to your account."
    )
    uploaded_file = st.file_uploader(
        "Upload PDF Reference",
        type=["pdf"],
        label_visibility="collapsed",
    )

    if uploaded_file is not None and st.button(
        "🚀 Ingest & Vectorize",
        use_container_width=True,
    ):
        with st.spinner("Processing document chunks..."):
            try:
                files = {
                    "file": (
                        uploaded_file.name,
                        uploaded_file.getvalue(),
                        "application/pdf",
                    )
                }
                response = api_request("POST", "/ingest/", files=files)
                if response.status_code == 200:
                    st.success(f"Indexed: {uploaded_file.name}")
                else:
                    st.error(f"Error: {response_detail(response)}")
            except requests.RequestException as error:
                st.error(f"Connection failed: {error}")

    st.divider()
    st.markdown("### 🗃️ Saved Context")
    documents = []
    try:
        response = api_request("GET", "/documents/")
        if response.status_code == 200:
            documents = response.json()
        else:
            st.error(f"Error: {response_detail(response)}")
    except requests.RequestException as error:
        st.error(f"Connection failed: {error}")

    if documents:
        for document in documents:
            with st.container(border=True):
                st.write(document["source_filename"])
                if st.button(
                    "Delete",
                    key=f"delete-document-{document['id']}",
                    use_container_width=True,
                ):
                    response = api_request(
                        "DELETE",
                        f"/documents/{document['id']}",
                    )
                    if response.status_code == 204:
                        st.success("Document deleted from the database")
                        st.rerun()
                    else:
                        st.error(f"Error: {response_detail(response)}")
    else:
        st.caption("No saved documents")

    st.divider()
    if st.button("Clear Chat", use_container_width=True):
        st.session_state.messages = []
        st.rerun()

    if st.button(
        "Clear Saved Context",
        use_container_width=True,
        disabled=not documents,
    ):
        response = api_request("DELETE", "/documents/")
        if response.status_code == 200:
            st.session_state.messages = []
            st.success("All saved context deleted from the database")
            st.rerun()
        else:
            st.error(f"Error: {response_detail(response)}")

    if st.button("Log out", use_container_width=True):
        st.logout()

if "messages" not in st.session_state:
    st.session_state.messages = []

WELCOME = """👋 **Welcome — this is a retrieval-augmented copilot.**

Every answer is generated **only** from documents in your own workspace, and
every reply cites the exact source chunks it used, so you can check any claim
against its origin.

**Two ways to start:**

1. **Ask about Akin.** A profile document is already loaded in your workspace.
   Ask anything about his experience, the systems he has built, or the
   measurable results.
2. **Bring your own document.** Upload a PDF from the sidebar and it replaces
   the default profile — your document becomes the only thing this copilot can
   answer from.

---

🔒 **On privacy:** this app is behind Google sign-in, and every document,
every chunk and every retrieval query is scoped to your authenticated account.
What you upload is not visible to anyone else using this instance. That is
enforced in the API rather than in this interface, and it is covered by tests.
"""

STARTER_QUESTIONS = [
    "What does Akin Gungor specialise in?",
    "What measurable results are documented?",
    "Which cloud and AI services does he work with?",
    "Describe the RAG system he built at Akumina",
]

if not st.session_state.messages:
    with st.chat_message("assistant", avatar="✨"):
        st.markdown(WELCOME)
        st.caption("Try one of these:")
        for index, question in enumerate(STARTER_QUESTIONS):
            if st.button(
                question,
                key=f"starter-{index}",
                use_container_width=False,
            ):
                st.session_state.pending_prompt = question
                st.rerun()

for message in st.session_state.messages:
    avatar = "👤" if message["role"] == "user" else "✨"
    with st.chat_message(message["role"], avatar=avatar):
        st.markdown(message["content"])

# A starter button sets pending_prompt and reruns; drain it here so the same
# question runs through exactly one code path as a typed one.
prompt = st.session_state.pop("pending_prompt", None)
if not prompt:
    prompt = st.chat_input("Ask a question, or upload your own PDF from the sidebar...")

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user", avatar="👤"):
        st.markdown(prompt)

    with st.chat_message("assistant", avatar="✨"):
        with st.spinner("Retrieving context & synthesizing response..."):
            try:
                history_payload = [
                    {"role": message["role"], "content": message["content"]}
                    for message in st.session_state.messages[:-1]
                ]
                response = api_request(
                    "POST",
                    "/ask/",
                    json={"question": prompt, "history": history_payload},
                )

                if response.status_code == 200:
                    data = response.json()
                    answer = data.get("answer", "No answer returned.")
                    sources = data.get("sources", [])

                    st.markdown(answer)

                    if sources:
                        with st.expander("🔗 Verified Knowledge Sources"):
                            for index, source in enumerate(sources):
                                st.markdown(
                                    f"**[{index + 1}] {source['source_filename']}** "
                                    f"(Chunk {source['chunk_index']})"
                                )
                                st.caption(f"Relevance Score: {source['similarity']:.2f}")
                                st.code(source["content"], language="text")
                                st.divider()

                    st.session_state.messages.append(
                        {"role": "assistant", "content": answer}
                    )
                else:
                    st.error(f"Error: {response_detail(response)}")
            except requests.RequestException as error:
                st.error(f"Network error: {error}")

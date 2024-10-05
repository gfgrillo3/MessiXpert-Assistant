import streamlit as st
from PIL import Image
from langchain.memory import ConversationBufferMemory
from time import time
import uuid
import sys
import os

# Add scripts filepath for importing the rag functions
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'scripts')))

from rag import generate_answer
from db import save_answer, save_feedback
from dotenv import load_dotenv

from sentence_transformers import SentenceTransformer
from elasticsearch import Elasticsearch

# Loading the environment variables.
load_dotenv()

# Global configuration of the page
st.set_page_config(page_title="MessiXpert Assistant", page_icon="⚽")

# Initialize the embeddings model
embeddings_model = SentenceTransformer('all-MiniLM-L6-v2')

# Initialize the Elasticsearch client
es_client = Elasticsearch("http://localhost:9200")

# ElasticSearch Index names
es_index_name = "messixpert_cosine"


# Function to apply a custom css style to some components of the app.
def apply_custom_style():
    st.markdown("""
    <style>
    .stApp {
        background-color: #1E1E1E;
        color: white;
    }
    .stTextInput > div > div > input {
        background-color: #2D2D2D;
        color: white;
    }
    .stButton > button {
        background-color: #4CAF50;
        color: white;
    }
    .chat-message {
        padding: 1.5rem; border-radius: 0.5rem; margin-bottom: 1rem; display: flex
    }
    .chat-message.user {
        background-color: #2D2D2D
    }
    .chat-message.bot {
        background-color: #1E1E1E
    }
    .chat-message .avatar {
        width: 20%;
    }
    .chat-message .avatar img {
        max-width: 78px;
        max-height: 78px;
        border-radius: 50%;
        object-fit: cover;
    }
    .chat-message .message {
        width: 80%;
        padding: 0 1.5rem;
    }
    </style>
    """, unsafe_allow_html=True)

apply_custom_style()


# Title and image
col1, col2, col3 = st.columns([1, 3, 1])
with col2:
    st.title("MessiXpert Assistant")


messi_image = Image.open("../assets/messi-logo-1.png")
col1, col2, col3 = st.columns([1, 1.25, 1])
with col2:
    st.image(messi_image, width=200)


# Initialize session state
if 'chat_history' not in st.session_state:
    st.session_state.chat_history = []
if 'likes' not in st.session_state:
    st.session_state.likes = {}
if 'memory' not in st.session_state:
    st.session_state.memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)
if 'conversations_id' not in st.session_state:
    st.session_state.conversations_id = {}
if 'api_key' not in st.session_state:
    st.session_state.api_key = ""


# Function to insert feedback to the database
def insert_feedback_to_db(conversation_id, feedback):
    try:
        save_feedback(conversation_id, feedback, timestamp=None)
        return True
    except Exception as e:
        print(f"Error inserting feedback: {e}")
        return False


# Function to insert an answer to the database
def insert_answer_to_db(answer_data, conversation_id):
    try:
        save_answer(conversation_id, answer_data, timestamp=None)
        return True
    except Exception as e:
        print(f"Error inserting answer: {e}")
        return False


# Function for asking the Knowledge database
def ask_to_vectorDB(question, es_client, es_index_name):
    start_time = time()
    memory = st.session_state.memory
    answer, costs, tokens = generate_answer(question, es_client, es_index_name, memory)
    
    memory.save_context({"user": question}, {"assistant": answer})
    end_time = time()
    total_time = end_time - start_time 

    answer_data = {
        "question": question,
        "answer": answer,
        "model_used": "gpt-4o-mini",
        "response_time": total_time,
        "relevance": "UNKNOWN",
        "relevance_explanation": "UNKNOWN",
        "prompt_tokens": tokens.get("input_tokens"),
        "completion_tokens": tokens.get("output_tokens"),
        "total_tokens": tokens.get("total_tokens"),
        "eval_prompt_tokens": 0,
        "eval_completion_tokens": 0,
        "eval_total_tokens": 0,
        "openai_cost": costs.get("total_cost"),
    }

    answer_id = str(uuid.uuid4())
    st.session_state.conversations_id[len(st.session_state.conversations_id)] = answer_id
    insert_answer_to_db(answer_data, answer_id)

    return answer


# Function to handle feedback
def handle_feedback(index, feedback):
    st.session_state.likes[index] = feedback
    conversation_id = st.session_state.conversations_id.get(index)
    if conversation_id:
        insert_feedback_to_db(conversation_id, 1 if feedback == 'like' else -1)


# Display chat messages
def display_chat_message(message, is_user=False, index=None):
    with st.chat_message("user" if is_user else "assistant"):
        st.markdown(message["content"])
        
        if not is_user and index is not None:
            col1, col2, col3 = st.columns([1, 1, 8])
            if index not in st.session_state.likes:
                with col1:
                    if st.button("👍", key=f"like_{index}", on_click=handle_feedback, args=(index, "like")):
                        st.rerun()
                with col2:
                    if st.button("👎", key=f"dislike_{index}", on_click=handle_feedback, args=(index, "dislike")):
                        st.rerun()
            else:
                with col3:
                    st.write(f"Feedback: {'👍' if st.session_state.likes[index] == 'like' else '👎'}")


# Main app logic
def main():
    # API Key input
    if not st.session_state.api_key:
        st.session_state.api_key = st.text_input("Add your OpenAI API Key to use the RAG", type="password")
        if st.session_state.api_key:
            st.success("API Key added successfully!")
            st.rerun()

    if st.session_state.api_key:
        # Display chat history
        for i, message in enumerate(st.session_state.chat_history):
            display_chat_message(message, is_user=(message["role"] == "user"), index=i)

        # Chat input
        if prompt := st.chat_input("Write your question here"):
            st.session_state.chat_history.append({"role": "user", "content": prompt})
            display_chat_message({"role": "user", "content": prompt}, is_user=True)

            with st.spinner("Thinking..."):
                response = ask_to_vectorDB(prompt, es_client, es_index_name)
            
            st.session_state.chat_history.append({"role": "assistant", "content": response})
            display_chat_message({"role": "assistant", "content": response}, index=len(st.session_state.chat_history)-1)

        # Clean chat button
        if st.button("Clean chat"):
            st.session_state.chat_history = []
            st.session_state.likes = {}
            st.session_state.conversations_id = {}
            st.rerun()


if __name__ == "__main__":
    main()
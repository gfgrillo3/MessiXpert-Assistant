from dotenv import load_dotenv

from sentence_transformers import SentenceTransformer

from openai import OpenAI

from langchain.memory import ConversationBufferMemory




# Loading the environment variables
load_dotenv()

# Instantiating the OpenAI Client
OpenAI_client = OpenAI()

# Initialize the embeddings model
embeddings_model = SentenceTransformer('all-MiniLM-L6-v2') 


#############################################################################################
######################################### Functions #########################################
#############################################################################################



# Function to make a text search to the Elastic Search client
def text_search(user_query, es_client, index):
    query = {
        "size": 5,  
        "query": {
            "bool": {
                "must": [
                    {
                        "match": {
                            "content": user_query  # Search in the content field
                        }
                    }
                ]
            }
        }
    }

    results = es_client.search(index=index, body=query)
    
    return results["hits"]["hits"]



# Function to make a KNN search to the Elastic Search client
def knn_search(user_query, es_client, index, embeddings_model):

    user_query = embeddings_model.encode(user_query)

    query = {
        "k": 5,  
        "field": "content_embeddings",
        "query_vector": user_query
    }

    results = es_client.search(index=index, knn=query)

    return results["hits"]["hits"]



# Function to make an hybrid search using the text search and knn search
def hybrid_search(user_query, es_client, index, embeddings_model):

    text_results = text_search(user_query=user_query, es_client=es_client, index=index)
    knn_results = knn_search(user_query=user_query, es_client=es_client, index=index, embeddings_model=embeddings_model)
        
    combined_results = text_results + knn_results
    
    return combined_results



# Function for get the text content of the answers
def get_answers_content(answers):

    retrieved_texts = [hit["_source"]["content"] for hit in answers]

    return retrieved_texts
    


# Function for building the prompt of the assistant
def build_prompt(query, search_results_text_list, conversation_history):
    
    prompt_template = """
You are an expert biographer on the life and career of Lionel Messi, with deep knowledge of his entire history and statistics. 
Your task is to answer users questions based solely on the context provided to you. 
Answer respectfully and in a warm way, as if you are an assistant.
Answer in the same language that you are asked, if you are asked in english then answer in english, but if you are asked in spanish then answer in spanish.
Use only the data from the context to answer the question. 
If you cannot answer the question with the provided information, respond: “I’m sorry, but I don’t have enough information to answer that. Is there anything else I can help you with?”

Here is the conversation history so far:
{conversation_history}

CONTEXT: {context}

QUESTION: 
{question}
""".strip()

    context = ""
    
    for text in search_results_text_list:
        context = context + f"{text}\n\n"
    prompt = prompt_template.format(question=query, context=context, conversation_history=conversation_history.load_memory_variables({})).strip()
    return prompt



# Function for calculate the cost of the interaction with the llm
def calculate_cost(response):

    input_tokens = response.usage.prompt_tokens
    output_tokens = response.usage.completion_tokens

    input_tokens_cost_per_1k = 0.00015
    output_tokens_cost_per_1k = 0.0006

    input_tokens_cost = input_tokens_cost_per_1k * (input_tokens / 1000)
    output_tokens_cost = output_tokens_cost_per_1k * (output_tokens / 1000)
    total_cost = input_tokens_cost + output_tokens_cost

    costs = {"input_tokens_cost":input_tokens_cost,
             "output_tokens_cost":output_tokens_cost,
             "total_cost":total_cost}
    
    tokens = {"input_tokens":input_tokens,
              "output_tokens":output_tokens,
              "total_tokens":input_tokens+output_tokens}
    #print("------------------------------------")
    #print(f"Input Tokens: {input_tokens}       Cost: ${input_tokens_cost:.8f}")
    #print(f"Completion Tokens: {output_tokens}       Cost: ${output_tokens_cost:.8f}")
    #print(f"Total Cost: ${total_cost:.8f}")
    #print("------------------------------------")

    return costs, tokens



# Function for generate the answer with the LLM
def llm_generate_answer(prompt, open_ai_client):
    response = open_ai_client.chat.completions.create(
        model='gpt-4o-mini',
        messages=[{"role": "user", "content": prompt}]
    )
    
    costs, tokens = calculate_cost(response)

    print(f"COSTS = {costs}")

    return response.choices[0].message.content, costs, tokens



# Function that handles the request of generate the answer. Including the retrieval, prompt building and all the steps.
def generate_answer(question, es_client, index_name, memory, embeddings_model=embeddings_model, search_function=hybrid_search, open_ai_client=OpenAI_client):

    top_k_chunks = search_function(user_query=question, es_client=es_client, index=index_name, embeddings_model=embeddings_model)

    answers = get_answers_content(top_k_chunks)
    
    builded_prompt = build_prompt(query=question, search_results_text_list=answers, conversation_history=memory)
    
    answer, costs, tokens = llm_generate_answer(builded_prompt, open_ai_client=open_ai_client)

    return answer, costs, tokens





#############################################################################################
###################################### End of Functions #####################################
#############################################################################################




if __name__ == "__main__":
    
    print("RAG PREPARED")








import os
import re
import time
from io import StringIO

from dotenv import load_dotenv

import pandas as pd

from tqdm.auto import tqdm

import requests
from bs4 import BeautifulSoup

from sentence_transformers import SentenceTransformer

import tiktoken

from elasticsearch import Elasticsearch







#############################################################################################
######################################### Functions #########################################
#############################################################################################



# Function for scrapping any wikipedia page and save the raw html data
def scrape_wikipedia_page(url,raw_data_filepath='../data/raw/'):

    response = requests.get(url)

    raw_data_filename = re.search(r'wiki/(.*)', url).group().replace('/', '_')
    raw_file_path = f'{raw_data_filepath}{raw_data_filename}.html'

    os.makedirs('data/raw', exist_ok=True)
    with open(raw_file_path, 'w', encoding='utf-8') as file:
        file.write(response.text)


    return response.text



# Function for scrapping any html from wikipedia and extract each content with it related format (Headers, Paragraphs and tables)
def scrape_wikipedia_html(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Extracting the main content of the wiki
    content = soup.find('div', {'class': 'mw-parser-output'})
    
    # Extracting all the formats of the content
    extracted_content = content.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'table'])
    
    return extracted_content



# Function for standard text cleaning. Cleaning special characters and normalizing the text.
def clean_text(text):

    clean_text = re.sub(r'\s+', ' ', text)  # Cleaning extra whitespaces
    #clean_text = re.sub(r'[^\w\s]', '', clean_text)  # Cleaning special characters
    clean_text = clean_text.strip() # Cleaning whitespaces at the start and at the end

    return clean_text



# Function for counting tokens in a text
def count_tokens(text, encoding):
    """Función para contar el número de tokens en un texto."""
    return len(encoding.encode(text))



# Aux function for processing the headers when chunking an HTML.
# The headers will be used as an important feature to store with the chunk content for improving the RAG accuracy-
def chunking_processing_HTML_headers(elem, current_headers):
    level = int(elem.name[1])
    current_headers[f'h{level}'] = elem.text.strip()
    
    # Cleaning headers with less level
    for i in range(level + 1, 7):
        current_headers[f'h{i}'] = ''

    return current_headers



# Aux function for processing  the paragraphs when chunking an HTML.
# It needs the info of the actual chunk, actual chunk size, max chunk size and headers.
# It process the paragraph. If the chunk size with the current paragraph will be larger than the max chunk size,
# the current chunk is stored with the relevant info, and a new chunk is created is created from the actual paragraph info. 
# If the chunk size is smaller than the max chunk size, then the paragraph is appended to the current chunk, updating the relevant info.
def chunking_processing_HTML_paragraphs(paragraph, current_headers, current_chunk, current_token_count, max_chunk_size, chunks, ingestion_timestamp, chunk_incremental_counter, source_url, encoding):

    headers_concat = " > ".join([current_headers[f'h{i}'] for i in range(1, 7) if current_headers[f'h{i}']])
    chunk_text = paragraph

    tokens_in_chunk = count_tokens(chunk_text, encoding)
    
    if current_token_count + tokens_in_chunk <= max_chunk_size:
        current_chunk += chunk_text + " "
        current_token_count += tokens_in_chunk
    else:
        # Add the chunk for storing and reset the information
        chunks.append({
            "content": current_chunk.strip(),             
            "headers_concat": headers_concat,  
            "chunk_size": current_token_count+tokens_in_chunk,     
            "source_url": source_url,                 
            "content_type": "paragraph",
            "ingestion_date": ingestion_timestamp,
            "chunk_id": f"{ingestion_timestamp}_{chunk_incremental_counter:06d}"
            })
        
        chunk_incremental_counter+=1
        current_chunk = chunk_text + " "
        current_token_count = tokens_in_chunk

    return current_chunk, current_token_count, chunks, headers_concat, chunk_incremental_counter



# Aux function for processing  the tables when chunking an HTML.
# It needs the info of the actual chunk, actual chunk size, max chunk size and headers.
# It process the table in a single chunk for avoiding a splitting of the table that could generate misinformation and errors.
def chunking_processing_HTML_tables(table_html, current_headers, current_chunk, current_token_count, max_chunk_size, chunks, ingestion_timestamp, chunk_incremental_counter, source_url, encoding):
    try:
        table_df = pd.read_html(StringIO(table_html))[0]
        table_text = table_df.to_string(index=False)
        headers_concat = " > ".join([current_headers[f'h{i}'] for i in range(1, 7) if current_headers[f'h{i}']])
        chunk_text = table_text

        tokens_in_chunk = count_tokens(chunk_text, encoding)

        # Handling the chunk with the objective of mantaining the table in a single chunk.
        if current_chunk and current_token_count + tokens_in_chunk > max_chunk_size:
            # If the chunk will be larger, then we will store it first, before storing the table.
            # Add the chunk for storing and reset the information
            chunks.append({
                "content": current_chunk.strip(),             
                "headers_concat": headers_concat,  
                "chunk_size": current_token_count+tokens_in_chunk,     
                "source_url": source_url,                 
                "content_type": "paragraph",
                "ingestion_date": ingestion_timestamp,
                "chunk_id": f"{ingestion_timestamp}_{chunk_incremental_counter:06d}"
                })
            chunk_incremental_counter+=1
            current_chunk = ""  
            current_token_count = 0

        # Add the whole table content in the same chunk
        # Add the chunk for storing and reset the information
        chunks.append({
            "content": chunk_text.strip(),             
            "headers_concat": headers_concat,  
            "chunk_size": current_token_count+tokens_in_chunk,     
            "source_url": source_url,                 
            "content_type": "paragraph+table",
            "ingestion_date": ingestion_timestamp,
            "chunk_id": f"{ingestion_timestamp}_{chunk_incremental_counter:06d}"
            })
        
        chunk_incremental_counter+=1
        current_chunk = ""  # Reset the chunk after adding the table
        current_token_count = 0

    except ValueError:
        headers_concat = " > ".join([current_headers[f'h{i}'] for i in range(1, 7) if current_headers[f'h{i}']])
        chunks.append({'content': 'Error processing the table', 'headers_concat': headers_concat})

    return current_chunk, current_token_count, chunks, headers_concat, chunk_incremental_counter
    


    # Function for processing an html and generating chunks in an strategic way based on the best practices.
# It could recieve the max_chunk_size parameter. If a chunk is going to be larger than it, then the chunk will be splitted.

def create_chunks_with_headers(elements, source_url, encoding, max_chunk_size=500):

    # Generating the variables used to store with the chunk content.
    ingestion_timestamp = time.strftime("%Y%m%d%H%M%S")
    chunk_incremental_counter = 0


    ################################################
    chunks = []
    current_headers = {f'h{i}': '' for i in range(1, 7)}
    current_chunk = ""
    current_token_count = 0

    # Iterating over the HTML elements and processing the headers, paragraphs, and tables in different ways.
    for elem in elements:

        # If it's a header, we should update the current_header info.
        if elem.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            current_headers = chunking_processing_HTML_headers(elem, current_headers)

        # If it's a paragraph, whe should update the chubk content info, considering the chunk_size and actual chunk info and size.
        elif elem.name == 'p':
            paragraph = clean_text(elem.text)
            current_chunk, current_token_count, chunks, headers_concat, chunk_incremental_counter = chunking_processing_HTML_paragraphs(paragraph, current_headers, 
                                                                                                                                        current_chunk, current_token_count, 
                                                                                                                                        max_chunk_size, chunks,
                                                                                                                                        ingestion_timestamp, chunk_incremental_counter,
                                                                                                                                        source_url, encoding)

        elif elem.name == 'table':
            table_html = str(elem)
            current_chunk, current_token_count, chunks, headers_concat, chunk_incremental_counter = chunking_processing_HTML_tables(table_html, current_headers, 
                                                                                                                                    current_chunk, current_token_count, 
                                                                                                                                    max_chunk_size, chunks,
                                                                                                                                    ingestion_timestamp, chunk_incremental_counter,
                                                                                                                                    source_url, encoding)

    # Adding the last chunk
    if current_chunk:
        chunks.append({'content': current_chunk.strip(), 'headers_concat': headers_concat})

    return chunks



#############################################################################################
###################################### End of Functions #####################################
#############################################################################################




if __name__ == "__main__":

    
    # Loading the environment variables
    load_dotenv()

    # standard encoding for the tiktoken tokens count
    encoding = tiktoken.encoding_for_model("gpt-4o-mini")

    # url to be processed for the ingestion
    url = "https://es.wikipedia.org/wiki/Lionel_Messi"



    # Starting the processing of the knowledge source
    html_content = scrape_wikipedia_page(url)
    processed_html_content = scrape_wikipedia_html(html_content)

    # Chunk the wiki page
    chunks = create_chunks_with_headers(processed_html_content, source_url=url, encoding=encoding, max_chunk_size=500)

    # Initialize the embeddings model
    embeddings_model = SentenceTransformer('all-MiniLM-L6-v2')


    # Adding the embedding for each chunk content
    for chunk in tqdm(chunks):

        # Generating the embeddings
        embedding = embeddings_model.encode(chunk['content']).tolist()
        
        # Adding the embeddings to the original dict
        chunk['content_embeddings'] = embedding




    # Initialize the Elasticsearch client
    es_client = Elasticsearch("http://localhost:9200")


    # Creating the index settings for the vectorDB.
    index_settings_cosine = {
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0
        },
        "mappings": {
            "properties": {
                "content": {"type": "text"},
                "headers_concat": {"type": "text"},
                "chunk_size": {"type": "integer"},
                "source_url": {"type": "text"} ,
                "content_type": {"type": "text"} ,
                "ingestion_date": {"type": "date"} ,
                "content_embeddings": {"type": "dense_vector", "dims": 384, "index": True, "similarity": "cosine"},
            }
        }
    }



    # Creating the index in ElasticSearch
    index_name_cosine = "messixpert_cosine"

    es_client.indices.create(index=index_name_cosine, body=index_settings_cosine)


    for chunk in tqdm(chunks):
        try:
            es_client.index(index=index_name_cosine, document=chunk)
        except Exception as e:
            print(e)
    

    print("INGESTION SUCCEEDED.")

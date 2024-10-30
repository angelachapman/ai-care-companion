import os
from typing import cast
from dotenv import load_dotenv

import chainlit as cl
import asyncio
from uuid import uuid4

from langchain_qdrant import QdrantVectorStore
from langchain_anthropic import ChatAnthropic
from langchain_openai import OpenAIEmbeddings
from langchain.retrievers import EnsembleRetriever
from langchain_core.prompts import ChatPromptTemplate
from langchain.memory import ConversationBufferWindowMemory
from langchain.chains import create_history_aware_retriever
from langchain_core.prompts import MessagesPlaceholder

from vars import SYSTEM_PROMPT, MAX_CONTEXT, GREETING
from vars import COLLECTION_NAME_FIXED, COLLECTION_NAME_SEMANTIC, URL
from vars import HAIKU, SONNET, TEMPERATURE, TOP_P, MAX_TOKENS, MAX_MEMORY
from utils import add_sources, get_toolbelt, use_eldercare_api, check_facts

# Environment vars
load_dotenv('.env')
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
try:
    LANGCHAIN_API_KEY = os.getenv("LANGCHAIN_API_KEY")
except:
    print(f"Langsmith API key not found; tracing will not be enabled")

os.environ["LANGCHAIN_TRACING_V2"] = "true"
unique_id = uuid4().hex[0:8]
os.environ["LANGCHAIN_PROJECT"] = f"CareCompanion - {unique_id}"

if not ANTHROPIC_API_KEY or not OPENAI_API_KEY:
    raise ValueError("ANTHROPIC_API_KEY or OPENAI_API_KEY environment variable is not set")

# Embedding model
openai_embeddings = OpenAIEmbeddings(
    model="text-embedding-3-large",
    openai_api_key=OPENAI_API_KEY  
)

# Initialize retriever
def init_retriever(llm):

    fixed_store = QdrantVectorStore.from_existing_collection (
        embedding=openai_embeddings,
        collection_name=COLLECTION_NAME_FIXED,
        url=URL
    )
    semantic_store = QdrantVectorStore.from_existing_collection (
        embedding=openai_embeddings,
        collection_name=COLLECTION_NAME_SEMANTIC,
        url=URL
    )
    similarity_retriever_fixed = fixed_store.as_retriever(k=10)
    similarity_retriever_semantic = semantic_store.as_retriever(k=10)
    ensemble_retriever = EnsembleRetriever(retrievers=[similarity_retriever_fixed, 
                                                       similarity_retriever_semantic])
    
    # Prompt for context-awareness
    retriever_prompt = ChatPromptTemplate.from_messages([
        MessagesPlaceholder(variable_name="chat_history"),
        ("user", "User input: {input}"),
        ("user", "Given the above conversation, generate a search query to look up to get information relevant to the the user's input")
    ])
    retriever_chain = create_history_aware_retriever(llm, ensemble_retriever, retriever_prompt)

    print(f"Initialized retriever of type {type(retriever_chain)}")
    return retriever_chain

@cl.on_chat_start
async def start():    

    haiku_llm = ChatAnthropic(
        model=HAIKU,    
        anthropic_api_key=ANTHROPIC_API_KEY,
        temperature = TEMPERATURE,
        top_p = TOP_P,
        max_tokens = MAX_TOKENS
    )
    sonnet_llm = ChatAnthropic(
        model= SONNET,
        anthropic_api_key=ANTHROPIC_API_KEY,
        temperature = TEMPERATURE,
        top_p = TOP_P,
        max_tokens = MAX_TOKENS
    )
    llm_with_tools = haiku_llm.bind_tools(get_toolbelt())

    fact_checker_llm = ChatAnthropic(
        model=SONNET, # Haiku is unable to reliably accomplish this. Good use case for fine tuning a small llm?
        anthropic_api_key=ANTHROPIC_API_KEY,
        temperature = TEMPERATURE,
        top_p = TOP_P,
        max_tokens = 1 # Ensure output is just Y or N
    )

    fact_fixer_llm = sonnet_llm

    memory = ConversationBufferWindowMemory(k=MAX_MEMORY)

    retriever = None
    try:
        retriever = init_retriever(haiku_llm)
    except Exception as e:
        print(f"error initializing retriever: {e}")
    if not retriever: raise ValueError("Error initializing retriever")

    memory.chat_memory.add_ai_message(GREETING)

    cl.user_session.set("retriever",retriever)
    cl.user_session.set("llm",sonnet_llm) # Change this line to swap out the main question answering LLM!!
    cl.user_session.set("llm_with_tools",llm_with_tools)
    cl.user_session.set("fact_checker_llm",fact_checker_llm)
    cl.user_session.set("fact_fixer_llm",fact_fixer_llm)
    cl.user_session.set("memory",memory)

    msg = cl.Message(content=GREETING)
    await msg.send()

@cl.author_rename
def rename(orig_author: str):
    rename_dict = {"Assistant": "CareCompanion"}
    return rename_dict.get(orig_author, orig_author)

@cl.on_message
async def main(message: cl.Message):

    retriever = cl.user_session.get("retriever")
    llm = cl.user_session.get("llm")
    llm_with_tools = cl.user_session.get("llm_with_tools")
    fact_checker_llm = cl.user_session.get("fact_checker_llm")
    fact_fixer_llm = cl.user_session.get("fact_fixer_llm")
    
    memory = cl.user_session.get("memory")
    memory.chat_memory.add_user_message(message.content)

    msg = cl.Message(content="")

    context_docs = None
    try:
        retriever_inputs = {
            "input": message.content,
            "chat_history": memory.chat_memory.messages
        }
        retriever_task = retriever.ainvoke(retriever_inputs)
        tool_output_task = use_eldercare_api(memory.chat_memory.messages, llm_with_tools)
        context_docs, tool_output = await asyncio.gather(retriever_task, tool_output_task)

        context_docs = context_docs[:MAX_CONTEXT]  # Limit context size if necessary
        sources = add_sources(context_docs)
        formatted_context = "\n".join([doc.page_content for doc in context_docs])
        #print(f"formatted context: {formatted_context}") #uncomment to see context

    except Exception as e:
        print(f"Error in retrieval or tool use: {e}")
        await cl.Message(content="I'm sorry, an error occurred processing your request").send()

    ai_response = ""
    fact_checker_passed = False
    attempt = 1
    max_tries = 3

    if context_docs:
        try:
            prompt_inputs = {
                'context': formatted_context,
                'history': memory.load_memory_variables({})["history"],
                'tool_output': tool_output,
                'query': message.content
            }

            prompt_text = SYSTEM_PROMPT.format(**prompt_inputs)

            async for chunk in llm.astream(prompt_text):
                #print(chunk) #uncomment to debug streaming
                ai_response+=chunk.content
                await msg.stream_token(chunk.content)

            await msg.stream_token(sources)
            await msg.send()

            while not fact_checker_passed and attempt<=max_tries:

                fact_checker_passed = await check_facts(formatted_context, tool_output, ai_response,
                                                        fact_checker_llm, memory, fact_fixer_llm,
                                                        attempt, max_tries)
                attempt += 1
                
        except Exception as e:
            print(f"Error in chain execution or guardail: {e}")
            await cl.Message(content="I'm sorry, an error occurred processing your request").send()

    memory.chat_memory.add_ai_message(ai_response)
    cl.user_session.set("memory",memory)

if __name__ == "__main__":
    cl.run()
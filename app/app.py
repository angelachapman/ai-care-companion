from operator import itemgetter
import os
from typing import cast
from dotenv import load_dotenv

import chainlit as cl
import asyncio

from langchain_qdrant import QdrantVectorStore
from langchain_anthropic import ChatAnthropic
from langchain_openai import OpenAIEmbeddings
from langchain.retrievers import EnsembleRetriever
from langchain_core.prompts import PromptTemplate, ChatPromptTemplate
from langchain.memory import ConversationBufferWindowMemory
from langchain.chains import create_history_aware_retriever
from langchain_core.prompts import MessagesPlaceholder

from vars import SYSTEM_PROMPT, MAX_CONTEXT, GREETING, COLLECTION_NAME, URL
from vars import HAIKU, SONNET, TEMPERATURE, TOP_P, MAX_TOKENS, MAX_MEMORY
from vars import FACT_CHECKER_MESSAGE, FACT_CHECKER_PROMPT, FACT_CHECKER_GIVE_UP_MESSAGE
from utils import add_sources, get_toolbelt, use_eldercare_api

# Environment vars
load_dotenv('.env')
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not ANTHROPIC_API_KEY or not OPENAI_API_KEY:
    raise ValueError("ANTHROPIC_API_KEY or OPENAI_API_KEY environment variable is not set")

# Embedding model
from langchain_openai import OpenAIEmbeddings
openai_embeddings = OpenAIEmbeddings(
    model="text-embedding-3-large",
    openai_api_key=OPENAI_API_KEY  
)

# Initialize retriever
def init_retriever(llm):

    store = QdrantVectorStore.from_existing_collection (
        embedding=openai_embeddings,
        collection_name=COLLECTION_NAME,
        url=URL
    )
    mmr_retriever = store.as_retriever(
        search_type="mmr",
        search_kwargs={'k': 10, 'lambda_mult': 0.1}
    )
    similarity_retriever = store.as_retriever(k=10)
    ensemble_retriever = EnsembleRetriever(retrievers=[mmr_retriever,similarity_retriever])
    
    retriever_prompt = ChatPromptTemplate.from_messages([
        MessagesPlaceholder(variable_name="chat_history"),
        ("user", "{input}"),
        ("user", "Given the above conversation, generate a search query to look up to get information relevant to the conversation")
    ])
    retriever_chain = create_history_aware_retriever(llm, ensemble_retriever, retriever_prompt)

    print(f"Initialized retriever of type {type(retriever_chain)}")
    return retriever_chain

@cl.on_chat_start
async def start():    

    rag_prompt = PromptTemplate.from_template(SYSTEM_PROMPT)
    fact_checker_prompt = PromptTemplate.from_template(FACT_CHECKER_PROMPT)

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

    llm_with_tools = ChatAnthropic(
        model="claude-3-haiku-20240307",    
        anthropic_api_key=ANTHROPIC_API_KEY,
    ).bind_tools(get_toolbelt())

    fact_checker_llm = ChatAnthropic(
        model=SONNET, # Haiku is unable to reliably accomplish this. Good use case for fine tuning a small llm?
        anthropic_api_key=ANTHROPIC_API_KEY,
        temperature = TEMPERATURE,
        top_p = TOP_P,
        max_tokens = 1
    )

    memory = ConversationBufferWindowMemory(k=MAX_MEMORY)

    retriever = None
    try:
        retriever = init_retriever(haiku_llm)
    except Exception as e:
        print(f"error initializing retriever: {e}")
    if not retriever: raise ValueError("Error initializing retriever")

    memory.chat_memory.add_ai_message(GREETING)

    cl.user_session.set("retriever",retriever)
    cl.user_session.set("rag_prompt",rag_prompt)
    cl.user_session.set("llm",sonnet_llm) # Change this line to swap out the main LLM!!
    cl.user_session.set("llm_with_tools",llm_with_tools)
    cl.user_session.set("fact_checker_llm",fact_checker_llm)
    cl.user_session.set("fact_checker_prompt",fact_checker_prompt)
    cl.user_session.set("memory",memory)

    msg = cl.Message(content=GREETING)
    await msg.send()


@cl.on_message
async def main(message: cl.Message):

    retriever = cl.user_session.get("retriever")
    rag_prompt = cl.user_session.get("rag_prompt")
    llm = cl.user_session.get("llm")
    llm_with_tools = cl.user_session.get("llm_with_tools")

    fact_checker_llm = cl.user_session.get("fact_checker_llm")
    fact_checker_prompt = cl.user_session.get("fact_checker_prompt")
    
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

    except Exception as e:
        print(f"Error in retrieval or tool use: {e}")
        await cl.Message(content="I'm sorry, an error occurred processing your request").send()

    ai_response = ""
    fact_checker_passed = False
    attempt = 1
    max_tries = 2

    if context_docs:
        while not fact_checker_passed and attempt<=max_tries:
            try:
                prompt_inputs = {
                    'context': formatted_context,
                    'history': memory.load_memory_variables({})["history"],
                    'tool_output': tool_output,
                    'query': message.content
                }

                prompt_text = rag_prompt.format(**prompt_inputs)

                async for chunk in llm.astream(prompt_text):
                    #print(chunk) #uncomment to debug streaming
                    ai_response+=chunk.content
                    await msg.stream_token(chunk.content)

                await msg.stream_token(sources)
                await msg.send()

                fact_checker_prompt_inputs = {
                    'context': formatted_context,
                    'tool_output': tool_output,
                    'ai_response': ai_response # change this line to something irrelevant or untrue to test the fact-checker
                }
                fact_checker_prompt_text = fact_checker_prompt.format(**fact_checker_prompt_inputs)
                fact_checker_output = await fact_checker_llm.ainvoke(fact_checker_prompt_text)
                if fact_checker_output:
                    print(f"fact checker results: {fact_checker_output.content}")
                    
                    if 'y' in fact_checker_output.content.lower():
                        # if the checker thinks we gave erroneous info, remove the last message and try again
                        await msg.remove()
                        if attempt == 1: 
                            await cl.Message(content=FACT_CHECKER_MESSAGE).send()
                            msg = cl.Message(content="")
                        elif attempt < max_tries:
                            msg = cl.Message(content="")
                        else:
                            ai_response = FACT_CHECKER_GIVE_UP_MESSAGE
                            await cl.Message(content=ai_response).send()
                    else:
                        fact_checker_passed = True
                
            except Exception as e:
                print(f"Error in chain execution or guardail: {e}")
                await cl.Message(content="I'm sorry, an error occurred processing your request").send()

            attempt += 1


    memory.chat_memory.add_ai_message(ai_response)
    cl.user_session.set("memory",memory)

if __name__ == "__main__":
    cl.run()
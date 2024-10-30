import os
from dotenv import load_dotenv

import chainlit as cl

from langchain.schema import Document
from langchain_core.tools import tool
from langchain_core.language_models.chat_models import BaseChatModel
from langchain.memory.chat_memory import BaseChatMemory

from zeep import Client
from zeep.helpers import serialize_object

from vars import FACT_CHECKER_PROMPT, FACT_CHECKER_MESSAGE, FACT_FIXER_PROMPT, FACT_CHECKER_GIVE_UP_MESSAGE

#### Code to work with the Eldercare API ####

load_dotenv('.env')
ELDERCARE_API_USERNAME = os.getenv("ELDERCARE_API_USERNAME")
ELDERCARE_API_PASSWORD = os.getenv("ELDERCARE_API_PASSWORD")

# Initialize the ElderCare API client with the WSDL URL
wsdl = 'https://eldercare.acl.gov/WebServices/EldercareData/ec_search.asmx?WSDL'
client = None
try:
    client = Client(wsdl=wsdl)
except Exception as e:
    print(f"error initializing client: {e}")

@tool
def search_by_city_state(city: str, state: str):
    """Uses the Eldercare Data API to search for elder care close to a given city and two-letter state abbreviation"""
    result = ""
    try:
        if not client:
            client = Client(wsdl=wsdl)
        session_token = client.service.login(ELDERCARE_API_USERNAME, ELDERCARE_API_PASSWORD)
        result = client.service.SearchByCityState(asCity=city, asState=state, asToken=session_token)
    except Exception as e:
        print(f"error in API call: {e}")
    return result

@tool
def search_by_zip(zip_code: str):
    """Uses the Eldercare Data API to search for elder care close to a zip code"""
    result = ""
    try: 
        if not client:
            client = Client(wsdl=wsdl)
        session_token = client.service.login(ELDERCARE_API_USERNAME, ELDERCARE_API_PASSWORD)
        result = client.service.SearchByZip(asZipCode=zip_code, asToken=session_token)
    except Exception as e:
        print(f"error in API call: {e}")
    return result

def get_toolbelt():
    return [search_by_city_state, search_by_zip]

# function to compress ElderCare API output into a string. Returns "" if none.
def condense_tool_output(tool_output):
    # Serialize the Zeep complex object into a Python dictionary
    serialized_data = serialize_object(tool_output)

    # Initialize an empty list to hold the formatted agency information
    formatted_output = []

    # Iterate through the agencies in the serialized data
    for agency in serialized_data['_value_1']['_value_1']:
        info = agency.get('Table1', {})

        # Extract relevant fields and handle missing data
        name = info.get('Name', 'N/A')
        address = f"{info.get('Address1', '')}, {info.get('City', '')}, {info.get('StateCode', '')} {info.get('ZipCode', '')}".strip(", ")
        phone = info.get('O_Phone', 'N/A')
        email = info.get('EMailAdd', 'N/A')
        url = info.get('URL', 'N/A')
        description = info.get('Description', 'No description available')

        # Format each agency's info into a single line
        formatted_entry = f"Name: {name} | Address: {address} | Phone: {phone} | Email: {email} | URL: {url} | Description: {description}"

        # Append the formatted entry to the output list
        formatted_output.append(formatted_entry)

    # Join all the entries with a single newline between each
    return "\n".join(formatted_output)

# function to call the eldercare API
async def use_eldercare_api(messages,llm_with_tools):

    tool_call_results = ""
    ai_msg = None
    tool_output = None

    try:
        ai_msg = await llm_with_tools.ainvoke(messages)
    except Exception as e:
        print(f"{use_eldercare_api.__name__}: LLM invocation returned an error: {e}")

    if ai_msg:
        for tool_call in ai_msg.tool_calls:
            selected_tool = {"search_by_city_state": search_by_city_state, "search_by_zip": search_by_zip}[tool_call["name"].lower()]
            try:
                tool_output = await selected_tool.ainvoke(tool_call["args"])
                tool_call_results += condense_tool_output(tool_output)

            except Exception as e:
                print(f"{use_eldercare_api.__name__}: Tool invocation returned an error: {e}")

    print(f"{use_eldercare_api.__name__}: Tool call results: {tool_call_results}")
    return tool_call_results


#### Other utilities ####

# Simple function to format sources as links before appending to a response
def add_sources(context: list[Document]) -> str:
    sources = []
    i=1
    for doc in context:
        url = doc.metadata.get('url', None)
        if url:
            # Remove any accidental escaping backslashes
            clean_url = url.replace("\\", "")
            already_have_it = False
            # Check for duplicates
            for source in sources:
                if clean_url in source:
                    already_have_it = True
            if not already_have_it:
                sources.append(f"[{i}]({clean_url})")
                i+=1
        else:
            sources.append(f"{i} (No URL)")
            i+=1
    sources_str = "\n\nSources: " + " ".join(sources)
    return sources_str

# Fact-checking function
async def check_facts(formatted_context:str, tool_output:str, ai_response:str,
                      fact_checker_llm:BaseChatModel, memory:BaseChatMemory, fact_fixer_llm:BaseChatModel,
                      attempt:int=1, max_tries:int=3) -> bool:
    
    fact_checker_passed = False
    fact_checker_prompt_inputs = {
                    'context': formatted_context,
                    'tool_output': tool_output,
                    'ai_response': ai_response # change this line to something irrelevant or untrue to test the fact-checker
                    }

    # check whether the response is factual. "Y" indicates a problem, "N" indicates that the 
    # response is ok
    fact_checker_prompt_text = FACT_CHECKER_PROMPT.format(**fact_checker_prompt_inputs)
    fact_checker_output = await fact_checker_llm.ainvoke(fact_checker_prompt_text)

    if fact_checker_output:
        print(f"fact checker results: {fact_checker_output.content}")
                    
        if 'y' in fact_checker_output.content.lower():
            # if the checker thinks we gave erroneous info, remove the last message and try again
            await msg.remove()
            if attempt == 1: 
                await cl.Message(content=FACT_CHECKER_MESSAGE).send()
                print("regenerating response -- attempt 1")
                        
            if attempt < max_tries:
                # Attempt to fix the response without re-doing retrieval 
                msg = cl.Message(content="")
                ai_response = ""
                fact_fixer_prompt_inputs = {
                    'history': memory.load_memory_variables({})["history"],
                    'context': formatted_context,
                    'tool_output': tool_output,
                    'ai_response': ai_response # change this line to something irrelevant or untrue to test the fact-checker
                }
                fact_fixer_prompt_text = FACT_FIXER_PROMPT.format(**fact_fixer_prompt_inputs)

                async for chunk in fact_fixer_llm.astream(fact_fixer_prompt_text):
                    #print(chunk) #uncomment to debug streaming
                    ai_response+=chunk.content
                    await msg.stream_token(chunk.content)

                await msg.stream_token(sources)
                await msg.send()
            else:
                # If max_tries is reached, send a "give up" message to avoid an infinite loop
                ai_response = FACT_CHECKER_GIVE_UP_MESSAGE
                await cl.Message(content=ai_response).send()
                print(f"reached max attempts, generating give-up message")

        else:
            fact_checker_passed = True
    return fact_checker_passed

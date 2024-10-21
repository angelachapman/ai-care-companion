import os
from dotenv import load_dotenv

from langchain.schema import Document
from langchain_core.tools import tool

from zeep import Client
from zeep.helpers import serialize_object

#### Code to work with the Eldercare API ####

load_dotenv('.env')
ELDERCARE_API_USERNAME = os.getenv("ELDERCARE_API_USERNAME")
ELDERCARE_API_PASSWORD = os.getenv("ELDERCARE_API_PASSWORD")

# Initialize the ElderCare API client with the WSDL URL
wsdl = 'https://eldercare.acl.gov/WebServices/EldercareData/ec_search.asmx?WSDL'
client = Client(wsdl=wsdl)

@tool
def search_by_city_state(city: str, state: str):
    """Uses the Eldercare Data API to search for elder care close to a given city and two-letter state abbreviation"""
    session_token = client.service.login(ELDERCARE_API_USERNAME, ELDERCARE_API_PASSWORD)
    return client.service.SearchByCityState(asCity=city, asState=state, asToken=session_token)

@tool
def search_by_zip(zip_code: str):
    """Uses the Eldercare Data API to search for elder care close to a zip code"""
    session_token = client.service.login(ELDERCARE_API_USERNAME, ELDERCARE_API_PASSWORD)
    return client.service.SearchByZip(asZipCode=zip_code, asToken=session_token)

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


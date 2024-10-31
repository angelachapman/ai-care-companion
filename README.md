# ai-care-companion

**Prerequisites**

This chatbot uses Anthropic LLMs, OpenAI embeddings, the [ElderCare API](https://eldercare.acl.gov/Public/Index.aspx), and (optionally) Langsmith tracing.
In order to use it, you must first get API keys for all of the above. Either place them in a .env file
or export them some other way into your environment as:
* ANTHROPIC_API_KEY
* OPENAI_API_KEY
* ELDERCARE_API_USERNAME
* ELDERCARE_API_PASSWORD
* LANGCHAIN_API_KEY

You will also need to install Docker and [Qdrant](https://qdrant.tech/) on your development machine.

**Environment Creation**

Chainlit is a little fussy about compatibility, so this project has separate environments for the notebooks and Chainlit app.
1. For the notebooks, create an environment and install notebook_requirements.txt
1. For the app, create an environment and install app_requirements.txt


**Kicking off Qdrant**
This project uses Qdrant as its vector database. To ensure quick performance, we populate the database once and then re-use it.

To start qdrant, in your terminal type:
'docker run -p 6333:6333 -p 6334:6334 \
    -v $(pwd)/qdrant_storage:/qdrant/storage:z \
    qdrant/qdrant'

You can use the Docker console to start and stop the process if you've already populated the DB before.

To check if it's running:
navigate to localhost:6333/dashboard in a browser


**Data Processing**
In addition to calling the EldercareAPI

**Running the App**
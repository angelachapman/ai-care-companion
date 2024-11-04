# CareCompanion

**CareCompanion** is a chatbot-driven tool designed to provide meaningful support to dementia caregivers. This project aims to assist caregivers by answering questions, offering resources, and providing personalized guidance on dementia care. With its easy-to-use interface, CareCompanion offers caregivers quick access to information and support tailored to the unique challenges they face, helping to alleviate some of the burdens associated with caregiving.

For more information about ths project, check out the [presentation deck](https://docs.google.com/presentation/d/1zrOrrBTq2Cd5RdVKr2-c5a_wnLrn4y7AivLNnXa7x8U/edit?usp=drive_link)

## About Blue Grotto Labs

**Blue Grotto Labs** is a boutique AI consultancy specializing in generative AI solutions, offering hands-on support for both prototyping and production deployments. Focused on delivering custom AI applications, Blue Grotto Labs provides expertise in implementation as well as strategic advising to help clients leverage AI technology effectively and bring tailored solutions into production. Learn more or reach out [here](https://www.linkedin.com/company/blue-grotto-labs)!

## Using the Code

### Prerequisites

This chatbot uses Anthropic LLMs, OpenAI embeddings, the [ElderCare API](https://eldercare.acl.gov/Public/Index.aspx), and (optionally) Langsmith tracing.
In order to use it, you must first get API keys for all of the above. Either place them in a .env file
or export them some other way into your environment as:

* ANTHROPIC_API_KEY
* OPENAI_API_KEY
* ELDERCARE_API_USERNAME
* ELDERCARE_API_PASSWORD
* LANGCHAIN_API_KEY

You will also need to install [Docker](https://www.docker.com/get-started/) and [Qdrant](https://qdrant.tech/) on your development machine.

### Environment Creation

To avoid dependency conflicts, this project has separate environments for the notebooks and Chainlit app.
1. For the notebooks, create an environment and install notebook_requirements.txt
1. For the app, create an environment and install app_requirements.txt


### Kicking off Qdrant

This project uses Qdrant as its vector database. To ensure quick performance, we populate the database once and then re-use it.

To start qdrant, in your terminal type:
'docker run -p 6333:6333 -p 6334:6334 \
    -v $(pwd)/qdrant_storage:/qdrant/storage:z \
    qdrant/qdrant'

You can use the Docker console to start and stop the process if you've already populated the DB before.

To check if it's running:
navigate to localhost:6333/dashboard in a browser


### Data Processing
This app scrapes websites such as the Mayo Clinic, CDC, Alzheimer's Association and others. To complete the one-time data scraping and database population process, run the following notebooks:

notebooks/fetch_data.ipynb
notebooks/chunk_and_load_data.ipynb

Once you scrape the data and populate your Qdrant collection, you are good to go!

### Running the App

All the code for the chainlit app is located in the app/ directory. After creating and activating your environment as described above, you can use
`> chainlit run app.py` from the command line to run the app.
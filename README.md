# OSO - Auto-Responder

OSO is an open-source project to automate social media interactions. 
It currently replies and posts content from Reddit users.

## Features

- **Reddit Integration**: Processes anon stories sent to the u/osoconfesoso007 inbox
- **Content Summarization**: Shortens stories and publishes them on its own profile.
- **Privacy Protection**: Removes personal information from submissions
- **Interaction with users**: It replies to messages and gives feedback if the story bounced
- **Spam filter**: It filters inapropriate submissions
- **Small models**: Tasks are divided so small LLMs can be used 
- **Containerized Deployment**: Easy setup with Docker Compose

## Requirements

- Docker and Docker Compose
- Reddit API credentials
- OpenAI API key (or equivalent)
- Postgres URL credentials

## Quick Start

1. Clone the repository:
   ```
   git clone https://github.com/yourusername/oso.git
   cd oso
   ```

2. Create a `.env` file using the provided template:
   ```
   cp .env.example .env
   ```

3. Configure your environment variables in the `.env` file

4. Start the application:
   ```
   docker-compose up -d
   ```

## Architecture

The project consists of several modules:

- **Interfaces**: Reddit API integration
- **Models**: Content processing components including:
  - Agent management
  - Embedder for content analysis
  - Summarizer for shortening content
  - Replier for automated responses
- **Database**: PostgreSQL schema for data persistence

## License

MIT License - Copyright (c) 2025 raul3820

## Contributing

Contributions are welcome! Please feel free to fork or submit changes.

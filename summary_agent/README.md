# Summary Agent

This is a standalone service for the Prepzo backend that handles generating and sending conversation summaries via email.

## Environment Variables

Before running the summary agent, make sure to set the following environment variables:

```
SUPABASE_URL=your_supabase_url
SUPABASE_SERVICE_ROLE_KEY=your_supabase_key
GOOGLE_API_KEY=your_google_api_key
GMAIL_USER=your_gmail_address
GMAIL_PASSWORD=your_gmail_app_password
FRONTEND_ORIGIN=http://localhost:3000 (or your frontend URL)
```

## Running Locally

1. Navigate to the root directory of the backend:

```bash
cd flask-prepzo-backend
```

2. Run the summary agent directly with Python:

```bash
python summary_agent/summary_agent.py
```

This will start the service on port 8000.

## Running with Docker

1. Build the Docker image from the root directory:

```bash
cd flask-prepzo-backend
docker build -f summary_agent/Dockerfile -t prepzo-summary-agent .
```

2. Run the Docker container:

```bash
docker run -p 8000:8000 \
  -e SUPABASE_URL=your_supabase_url \
  -e SUPABASE_SERVICE_ROLE_KEY=your_supabase_key \
  -e GOOGLE_API_KEY=your_google_api_key \
  -e GMAIL_USER=your_gmail_address \
  -e GMAIL_PASSWORD=your_gmail_app_password \
  -e FRONTEND_ORIGIN=http://localhost:3000 \
  prepzo-summary-agent
```

## API Endpoints

- `/sendsummary` - POST endpoint that generates and sends a summary email
- `/test-email` - GET endpoint to test email functionality (requires `email` query parameter)

## Deploying to Production

For production, consider:
1. Setting up SSL certificates for secure connections
2. Using a reverse proxy like Nginx
3. Implementing proper logging and monitoring
4. Setting up environment variables securely 
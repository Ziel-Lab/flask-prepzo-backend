FROM python:3.12.4
ENV PYTHONUNBUFFERED=1

# Set workdir
WORKDIR /app

# Copy only the requirements.txt first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the summary agent code
COPY summary_agent/ /app/

# Make sure all dependencies are installed
RUN pip install flask google-generativeai supabase python-dotenv flask-cors

# Create dirs if needed
RUN mkdir -p logs

EXPOSE 8000

# Start the summary agent
CMD ["python", "summary_agent.py"] 
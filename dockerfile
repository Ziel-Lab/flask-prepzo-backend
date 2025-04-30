# dockerfile

FROM python:3.12.4
ENV PYTHONUNBUFFERED=1

# 1. Set workdir
WORKDIR /app

# 2. Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 3. Copy everything else
#    (Excludes venv/, .git/, etc. via .dockerignore)
COPY . .

# 4. Make uploads dir
RUN mkdir -p uploads

EXPOSE 5001

# 5. Start your app
CMD ["python", "-m", "opti.run_backend"]

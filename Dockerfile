# Shared image for the Flask web server and the Celery worker
# (docker-compose overrides the command per service).
FROM python:3.9-slim

WORKDIR /app

# Copy only requirements first so dependency installs are cached across builds
COPY requirements.txt .

RUN apt-get -y update && apt-get install -y --no-install-recommends ffmpeg
RUN pip install --trusted-host pypi.python.org -r requirements.txt

# Copy the rest of the application files
COPY . .

# Expose Flask's port
EXPOSE 5000

# Run Flask when the container starts
CMD ["python", "run.py"]

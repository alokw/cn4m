# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /app

# Copy only the necessary files first (for better caching)
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --trusted-host pypi.python.org -r requirements.txt
RUN apt-get -y update && apt-get -y upgrade && apt-get install -y --no-install-recommends ffmpeg

# Copy the rest of the application files
COPY . .

# Expose Flask's port
EXPOSE 5000

# Run Flask when the container starts
CMD ["python", "run.py"]

#ENV FLASK_APP=app.app
#ENV FLASK_ENV=development

# Default command to run Flask (can be overridden in docker-compose)
# CMD ["flask", "--debug", "--app app", "run", "--host=0.0.0.0"]
# CMD ["flask", "run", "--host=0.0.0.0", "--port=5000", "--debug"]
# CMD ["python", "app.py"]
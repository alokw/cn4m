# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /app

# Copy only the necessary files first (for better caching)
COPY requirements.txt ./

# Install any needed packages specified in requirements.txt
RUN pip install --trusted-host pypi.python.org -r requirements.txt

# Copy the rest of the application files
COPY . /app

# Make port 5000 available to the world outside this container
#EXPOSE 5000

# Set environment variables
#ENV FLASK_APP=app.py \
#    FLASK_ENV=development \
#    CELERY_BROKER_URL=redis://redis:6379/0 \
#    CELERY_RESULT_BACKEND=redis://redis:6379/0

# Run app.py when the container launches
# CMD ["python", "app.py"]
# Default command to run Flask (can be overridden in docker-compose)
# CMD ["flask", "--debug", "--app app", "run", "--host=0.0.0.0"]
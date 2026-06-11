# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Copy the dependencies file to the working directory
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the working directory contents into the container at /app
COPY . .

# Cloud Run injects the PORT environment variable (default 8080)
ENV PORT=8080

# Run with Gunicorn (sheetgo_agent.app is the module, app is the Flask object)
CMD ["sh", "-c", "gunicorn --bind :$PORT --workers 4 --timeout 0 sheetgo_agent.app:app"]
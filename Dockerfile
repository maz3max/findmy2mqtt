# Dockerfile for findmy2mqtt
# build with `docker build -t findmy2mqtt .`
# Install requirements and run python script

# Use the official image as a parent image
FROM python:3.12-slim

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Run the application
CMD ["python", "findmy2mqtt.py"]
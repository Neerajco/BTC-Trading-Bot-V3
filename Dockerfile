# Use Python 3.12 to match our local environment and pandas-ta requirements
FROM python:3.12

# Set the working directory
WORKDIR /app

# Upgrade pip first to avoid wheel errors
RUN pip install --upgrade pip

# Copy dependencies and install them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Run the bot in unbuffered mode
CMD ["python", "-u", "main.py"]

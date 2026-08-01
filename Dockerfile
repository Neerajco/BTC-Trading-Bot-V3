# Use a lightweight python image
FROM python:3.10-slim

# Set the working directory
WORKDIR /app

# Copy dependencies and install them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Run the bot in unbuffered mode to ensure logs print immediately in Railway
CMD ["python", "-u", "main.py"]
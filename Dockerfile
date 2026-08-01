# Use the full Python image (Includes necessary C++ compilers for pandas/numpy)
FROM python:3.10

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

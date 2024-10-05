# Using this python base image
FROM python:3.12-slim

# Defining the workind directory inside the container
WORKDIR /app

# Copying the requerimients into the container
COPY requirements.txt .

# Installing the dependendencies
RUN pip install --no-cache-dir -r requirements.txt

# Copying the code inside the container
COPY . .

# Exposing the streamlit port
EXPOSE 8501

# Command for executing the streamlit app
CMD ["streamlit", "run", "ui/app.py", "--server.port=8501", "--server.address=0.0.0.0"]

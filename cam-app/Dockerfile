# Use the official Python 3.11 image as the base
FROM python:3.11-slim-bullseye

# Install FFmpeg and other necessary tools
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y ffmpeg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN pip install \
    apscheduler \
    fastapi-login \
    fastapi-proxiedheadersmiddleware \
    fastapi[standard] \
    jinja2 \
    python-multipart \
    sqlalchemy \
    uvicorn[standard]

WORKDIR /code

COPY ./app /code/app

CMD ["fastapi", "run", "app/main.py", "--port", "9090"]

FROM python:3.9-slim

RUN apt-get update && apt-get install -y \
    gcc \
    git \
    make \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Clone and build the fake TLS proxy
RUN git clone https://github.com/alexbers/mtprotoproxy.git .

# Copy our custom configuration
COPY config.py ./
COPY entrypoint.sh ./
COPY proxy_server.py ./

RUN chmod +x entrypoint.sh

EXPOSE 443

CMD ["./entrypoint.sh"]
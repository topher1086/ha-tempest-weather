ARG BUILD_FROM
FROM ghcr.io/home-assistant/amd64-base:latest

# Copy data for add-on
COPY run.sh /
COPY tempest.py /
COPY requirements.txt /
RUN chmod a+x /run.sh

RUN apk add --no-cache
RUN apk add python3
RUN apk add py3-pip

# Alpine 3.19 doesn't work without a virtual environment now
# set the environment variable and add it to the path so it works
ENV VIRTUAL_ENV=/.venv
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

RUN pip3 install -r requirements.txt


# Install wget and unzip for downloading and extracting Chrome/Chromedriver
RUN apk add --no-cache wget unzip

# Download and extract Chrome Headless Shell
RUN wget -O /chrome-headless-shell-linux64.zip https://storage.googleapis.com/chrome-for-testing-public/126.0.6478.126/linux64/chrome-headless-shell-linux64.zip \
	&& unzip /chrome-headless-shell-linux64.zip -d / \
	&& rm /chrome-headless-shell-linux64.zip \
	&& chmod +x /chrome-headless-shell-linux64/chrome-headless-shell

# Download and extract Chromedriver
RUN wget -O /chromedriver-linux64.zip https://storage.googleapis.com/chrome-for-testing-public/126.0.6478.126/linux64/chromedriver-linux64.zip \
	&& unzip /chromedriver-linux64.zip -d / \
	&& rm /chromedriver-linux64.zip \
	&& chmod +x /chromedriver-linux64/chromedriver

CMD ["./run.sh"]
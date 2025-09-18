# ARG BUILD_FROM # This is fine if you're using it in a build system
FROM ghcr.io/home-assistant/amd64-base:latest

# Set shell to bash if available, otherwise sh
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Copy data for add-on
COPY run.sh /
COPY tempest.py /
COPY requirements.txt /
RUN chmod a+x /run.sh

# Update apk cache and install all packages in a single layer to save space
# - python3 and pip are needed for the script
# - chromium and chromedriver are for selenium
# - udev, ttf-freefont, and dbus are necessary runtime dependencies for headless chrome
RUN apk update && apk add --no-cache \
    python3 \
    py3-pip \
    chromium \
    chromium-chromedriver \
    udev \
    ttf-freefont \
    dbus

# Alpine 3.19+ works best with a virtual environment
ENV VIRTUAL_ENV=/.venv
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Install python dependencies
RUN pip3 install --no-cache-dir -r requirements.txt

# You can add CMD or ENTRYPOINT here depending on run.sh
# For example:
CMD [ "/run.sh" ]

# # Install wget and unzip for downloading and extracting Chrome/Chromedriver
# RUN apk add --no-cache wget unzip

# # Download and extract Chrome Headless Shell
# RUN wget -O /chrome-headless-shell-linux64.zip https://storage.googleapis.com/chrome-for-testing-public/126.0.6478.126/linux64/chrome-headless-shell-linux64.zip \
# 	&& unzip /chrome-headless-shell-linux64.zip -d / \
# 	&& rm /chrome-headless-shell-linux64.zip \
# 	&& chmod +x /chrome-headless-shell-linux64/chrome-headless-shell

# # Download and extract Chromedriver
# RUN wget -O /chromedriver-linux64.zip https://storage.googleapis.com/chrome-for-testing-public/126.0.6478.126/linux64/chromedriver-linux64.zip \
# 	&& unzip /chromedriver-linux64.zip -d / \
# 	&& rm /chromedriver-linux64.zip \
# 	&& chmod +x /chromedriver-linux64/chromedriver

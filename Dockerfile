FROM python:3 as base

MAINTAINER Ben Yanke <benyanke@gmail.com>

##############
# Main setup stage
##############

# Copy in deps first, to improve build caching
COPY requirements.txt /app-src/requirements.txt
WORKDIR /app-src

# Get kerberos deps before pip deps can be fetched
#RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -qq -y krb5-user -y && rm -rf /var/lib/apt/lists/*

# Get latest pip and dependencies
RUN /usr/local/bin/python3 -m pip install --upgrade pip && pip install -r requirements.txt

# Copy in rest of the code after deps are in place
COPY . /app-src

# Install the app
RUN /usr/local/bin/python3 setup.py install

##############
# Run tests in a throwaway stage
# if tests are added later, run them here
##############
#FROM base as test
#WORKDIR /app-src
#RUN /usr/local/bin/python3 setup.py test

##############
# Throw away the test stage, revert back to base stage before push
##############

FROM base
WORKDIR /root
CMD ["/usr/local/bin/offlineimap"]
# reads from /root/.offlineimaprc by default - mount this in for running

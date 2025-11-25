#!/bin/sh

if [ -z "$SERVER_NAME" ]; then
  echo "Error: SERVER_NAME is not set!"
  exit 1
fi

envsubst '$SERVER_NAME' < /etc/nginx/conf.d/nginx.conf.template > /etc/nginx/conf.d/default.conf

exec nginx -g "daemon off;"
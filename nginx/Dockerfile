FROM nginx:1.28.0-alpine-slim


RUN rm /etc/nginx/conf.d/default.conf

COPY nginx.conf.template /etc/nginx/conf.d/nginx.conf.template
COPY entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
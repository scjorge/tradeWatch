FROM postgres:16-alpine
RUN apk add --no-cache gnupg
COPY backup.sh restore.sh verify-restore.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/*.sh
ENTRYPOINT []
CMD ["backup.sh", "loop"]

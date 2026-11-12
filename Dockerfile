ARG HELFERTOOL_VERSION=latest
FROM helfertool/helfertool:${HELFERTOOL_VERSION}

USER root

COPY docker/generate_config.py /usr/local/lib/helfertool-deploy/generate_config.py
COPY docker/bootstrap.py /usr/local/lib/helfertool-deploy/bootstrap.py
COPY docker/entrypoint.sh /usr/local/bin/helfertool-entrypoint
COPY scripts/healthcheck.sh /usr/local/bin/helfertool-healthcheck

RUN chmod 0755 /usr/local/bin/helfertool-entrypoint /usr/local/bin/helfertool-healthcheck \
    && chmod 0644 /usr/local/lib/helfertool-deploy/generate_config.py /usr/local/lib/helfertool-deploy/bootstrap.py

USER 10001:10001
ENTRYPOINT ["/usr/local/bin/helfertool-entrypoint"]
CMD ["run"]


FROM europe-north1-docker.pkg.dev/cgr-nav/pull-through/nav.no/python:3.10-dev AS builder
USER root
COPY --from=ghcr.io/astral-sh/uv@sha256:87a04222b228501907f487b338ca6fc1514a93369bfce6930eb06c8d576e58a4 /uv /uvx /bin/
WORKDIR /home/nonroot
ENV HOME=/home/nonroot
COPY --chown=nonroot:nonroot . /home/nonroot/src
USER nonroot
RUN uv tool install /home/nonroot/src

FROM europe-north1-docker.pkg.dev/cgr-nav/pull-through/nav.no/python:3.10-dev AS production
COPY --from=builder --chown=nonroot:nonroot /home/nonroot/.local /home/nonroot/.local
ENV HOME=/home/nonroot
ENV PATH="/home/nonroot/.local/bin:$PATH"
RUN cartography -h

ENTRYPOINT ["cartography"]
CMD ["-h"]

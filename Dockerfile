# MoRE — run the whole harness in a container.
#
# This is the clean way to let the crew use the shell freely: the container is
# the sandbox, so `--shell host` inside it can only touch this disposable box.
# Mount a workspace and pass the model endpoint at run time:
#
#   docker build -t more .
#   docker run --rm -it \
#     -e MOR_BASE_URL=http://your-gpu-box:8080/v1 \
#     -e MOR_MODEL=your-model \
#     -e MOR_SHELL=host \
#     -v "$PWD":/work -e MOR_WORKSPACE=/work \
#     more
#
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY mor ./mor
RUN pip install --no-cache-dir .

# state lives here; mount a volume to persist projects/config across runs
ENV MOR_HOME=/root/.mor
ENTRYPOINT ["mor"]

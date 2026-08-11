import http from "node:http";
import net from "node:net";

const targetValue = process.env.KTM_C7_LOOPBACK_UI_PROXY_TARGET ?? "";
const portValue = process.env.KTM_C7_LOOPBACK_UI_PROXY_PORT ?? "";
const target = URL.canParse(targetValue) ? new URL(targetValue) : null;

if (
  target === null ||
  target.protocol !== "http:" ||
  target.hostname !== "candidate-ui" ||
  target.username !== "" ||
  target.password !== "" ||
  target.pathname !== "/" ||
  target.search !== "" ||
  target.hash !== "" ||
  !/^[1-9][0-9]{0,4}$/.test(target.port) ||
  Number(target.port) > 65535 ||
  !/^[1-9][0-9]{0,4}$/.test(portValue) ||
  Number(portValue) > 65535
) {
  throw new Error("C7 loopback UI proxy configuration is invalid");
}

const targetPort = Number(target.port);
const listenPort = Number(portValue);

function requestHeaders(headers) {
  return {
    ...headers,
    host: target.host,
    "x-forwarded-host": target.host,
    "x-forwarded-proto": "http",
  };
}

const server = http.createServer((request, response) => {
  const upstream = http.request(
    {
      headers: requestHeaders(request.headers),
      hostname: target.hostname,
      method: request.method,
      path: request.url,
      port: targetPort,
    },
    (upstreamResponse) => {
      response.writeHead(upstreamResponse.statusCode ?? 502, upstreamResponse.headers);
      upstreamResponse.pipe(response);
    },
  );
  upstream.on("error", () => {
    if (!response.headersSent) {
      response.writeHead(502);
    }
    response.end();
  });
  request.pipe(upstream);
});

server.on("upgrade", (request, socket, head) => {
  const upstream = net.connect({ host: target.hostname, port: targetPort });
  const closeBoth = () => {
    socket.destroy();
    upstream.destroy();
  };
  upstream.on("error", closeBoth);
  socket.on("error", closeBoth);
  upstream.once("connect", () => {
    const headers = requestHeaders(request.headers);
    const serializedHeaders = Object.entries(headers)
      .flatMap(([name, value]) =>
        Array.isArray(value)
          ? value.map((item) => `${name}: ${item}`)
          : value === undefined
            ? []
            : [`${name}: ${value}`],
      )
      .join("\r\n");
    upstream.write(
      `${request.method} ${request.url ?? "/"} HTTP/${request.httpVersion}\r\n${serializedHeaders}\r\n\r\n`,
    );
    if (head.length > 0) {
      upstream.write(head);
    }
    socket.pipe(upstream).pipe(socket);
  });
});

server.listen(listenPort, "127.0.0.1");

function stop() {
  server.close(() => process.exit(0));
}

process.once("SIGINT", stop);
process.once("SIGTERM", stop);

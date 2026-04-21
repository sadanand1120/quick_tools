import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

MAX_BROWSER_POINTS = 2_000_000
MAX_DIRECT_FILE_BYTES = 256 * 1024 * 1024

_PLY_SCALAR_SIZES = {
    b"char": 1,
    b"uchar": 1,
    b"int8": 1,
    b"uint8": 1,
    b"short": 2,
    b"ushort": 2,
    b"int16": 2,
    b"uint16": 2,
    b"int": 4,
    b"uint": 4,
    b"int32": 4,
    b"uint32": 4,
    b"float": 4,
    b"float32": 4,
    b"double": 8,
    b"float64": 8,
}


HTML_PAGE = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>__TITLE_HTML__</title>
    <style>
      html,
      body {
        margin: 0;
        height: 100%;
        overflow: hidden;
        background: #050505;
        color: #f4f4f4;
        font-family: sans-serif;
      }

      #app {
        width: 100%;
        height: 100%;
      }

      #status {
        position: fixed;
        top: 12px;
        left: 12px;
        z-index: 10;
        padding: 10px 12px;
        border-radius: 8px;
        background: rgba(0, 0, 0, 0.68);
        font-size: 14px;
        line-height: 1.4;
        pointer-events: none;
      }
    </style>
    <script type="importmap">
      {
        "imports": {
          "three": "https://unpkg.com/three@0.166.1/build/three.module.js",
          "three/addons/": "https://unpkg.com/three@0.166.1/examples/jsm/"
        }
      }
    </script>
  </head>
  <body>
    <div id="status">Loading __TITLE_HTML__...</div>
    <div id="app"></div>
    <script type="module">
      import * as THREE from "three";
      import { OrbitControls } from "three/addons/controls/OrbitControls.js";
      import { PLYLoader } from "three/addons/loaders/PLYLoader.js";

      const container = document.getElementById("app");
      const status = document.getElementById("status");
      const title = __TITLE_JS__;

      const renderer = new THREE.WebGLRenderer({ antialias: true });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      renderer.setSize(window.innerWidth, window.innerHeight);
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      container.appendChild(renderer.domElement);

      const scene = new THREE.Scene();
      scene.background = new THREE.Color(0x050505);

      const camera = new THREE.PerspectiveCamera(
        55,
        window.innerWidth / window.innerHeight,
        0.01,
        1e6,
      );
      camera.up.set(0, 0, 1);
      camera.position.set(2, 2, 1.5);

      const controls = new OrbitControls(camera, renderer.domElement);
      controls.enableDamping = true;

      const loader = new PLYLoader();

      function formatBytes(bytes) {
        if (!bytes || bytes < 0) return "";
        const units = ["B", "KB", "MB", "GB"];
        let value = bytes;
        let unit = 0;
        while (value >= 1024 && unit < units.length - 1) {
          value /= 1024;
          unit += 1;
        }
        return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
      }

      loader.load(
        "/data.ply",
        (geometry) => {
          if (geometry.hasAttribute("normal")) {
            geometry.deleteAttribute("normal");
          }

          geometry.center();
          geometry.computeBoundingSphere();

          const radius = geometry.boundingSphere?.radius || 1;
          const material = new THREE.PointsMaterial({
            size: Math.max(radius / 400, 0.0025),
            sizeAttenuation: true,
            vertexColors: geometry.hasAttribute("color"),
          });

          const cloud = new THREE.Points(geometry, material);
          scene.add(cloud);

          camera.near = Math.max(radius / 1000, 0.001);
          camera.far = radius * 20;
          camera.position.set(radius * 1.7, -radius * 1.7, radius * 1.1);
          camera.updateProjectionMatrix();
          controls.target.set(0, 0, 0);
          controls.update();

          const count = geometry.getAttribute("position").count.toLocaleString();
          status.innerHTML = `${count} points<br />Drag to orbit, scroll to zoom`;
        },
        (event) => {
          const loaded = formatBytes(event.loaded);
          const total = formatBytes(event.total);
          status.textContent = total
            ? `Loading ${title}... ${loaded} / ${total}`
            : `Loading ${title}... ${loaded}`;
        },
        (error) => {
          console.error(error);
          status.textContent = `Failed to load ${title}: ${error?.message || error}`;
        },
      );

      window.addEventListener("resize", () => {
        camera.aspect = window.innerWidth / window.innerHeight;
        camera.updateProjectionMatrix();
        renderer.setSize(window.innerWidth, window.innerHeight);
      });

      function animate() {
        requestAnimationFrame(animate);
        controls.update();
        renderer.render(scene, camera);
      }

      animate();
    </script>
  </body>
</html>
"""


class _ViewerHandler(BaseHTTPRequestHandler):
    ply_path = None
    ply_bytes = None
    title = ""

    def do_GET(self) -> None:
        self._handle_request(send_body=True)

    def do_HEAD(self) -> None:
        self._handle_request(send_body=False)

    def log_message(self, format, *args) -> None:
        return

    def _write_chunks(self, payload: bytes, chunk_size: int = 1024 * 1024) -> None:
        try:
            for start in range(0, len(payload), chunk_size):
                self.wfile.write(payload[start : start + chunk_size])
        except (BrokenPipeError, ConnectionResetError):
            return

    def _handle_request(self, send_body: bool) -> None:
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            content = (
                HTML_PAGE.replace("__TITLE_HTML__", html.escape(self.title))
                .replace("__TITLE_JS__", json.dumps(self.title))
                .encode("utf-8")
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            if send_body:
                self.wfile.write(content)
            return

        if path == "/data.ply":
            if self.ply_bytes is not None:
                size = len(self.ply_bytes)
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(size))
                self.end_headers()
                if send_body:
                    self._write_chunks(self.ply_bytes)
                return

            size = self.ply_path.stat().st_size
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(size))
            self.end_headers()
            if send_body:
                with self.ply_path.open("rb") as handle:
                    try:
                        while True:
                            chunk = handle.read(1024 * 1024)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        return
            return

        self.send_error(404)


def _build_handler(ply_path: Path, ply_bytes=None):
    class Handler(_ViewerHandler):
        pass

    Handler.ply_path = ply_path
    Handler.ply_bytes = ply_bytes
    Handler.title = ply_path.name
    return Handler


def _print_ssh_hint(port: int) -> None:
    print("", flush=True)
    print("SSH tunnel from your local machine if needed:", flush=True)
    print(f"  ssh -L {port}:127.0.0.1:{port} <user>@<remote-host>", flush=True)
    print(f"  then open http://127.0.0.1:{port}/ locally", flush=True)


def _read_ply_header(ply_path: Path):
    with ply_path.open("rb") as handle:
        first_line = handle.readline()
        if first_line.strip() != b"ply":
            raise RuntimeError(f"Unsupported PLY header in {ply_path}")

        format_name = None
        vertex_count = None
        vertex_stride = 0
        vertex_properties = []
        in_vertex_element = False

        while True:
            line = handle.readline()
            if not line:
                raise RuntimeError(f"Unexpected EOF while reading header from {ply_path}")

            stripped = line.strip()
            if stripped == b"end_header":
                return {
                    "format": format_name,
                    "vertex_count": vertex_count,
                    "vertex_stride": vertex_stride,
                    "vertex_properties": vertex_properties,
                    "data_offset": handle.tell(),
                }

            if not stripped:
                continue

            parts = stripped.split()
            keyword = parts[0]

            if keyword == b"format" and len(parts) >= 2:
                format_name = parts[1].decode("ascii")
                continue

            if keyword == b"element" and len(parts) >= 3:
                in_vertex_element = parts[1] == b"vertex"
                if in_vertex_element:
                    vertex_count = int(parts[2])
                continue

            if keyword == b"property" and in_vertex_element:
                if len(parts) < 3 or parts[1] == b"list":
                    raise RuntimeError(f"Unsupported vertex property layout in {ply_path}")
                property_type = parts[1]
                size = _PLY_SCALAR_SIZES.get(property_type)
                if size is None:
                    raise RuntimeError(f"Unsupported PLY property type {property_type!r} in {ply_path}")
                vertex_stride += size
                vertex_properties.append((property_type.decode("ascii"), parts[2].decode("ascii")))


def _build_sampled_ply_bytes(ply_path: Path) -> Optional[bytes]:
    file_size = ply_path.stat().st_size
    if file_size <= MAX_DIRECT_FILE_BYTES:
        return None

    header = _read_ply_header(ply_path)
    fmt = header["format"]
    vertex_count = header["vertex_count"]
    vertex_stride = header["vertex_stride"]
    data_offset = header["data_offset"]
    vertex_properties = header["vertex_properties"]

    if fmt not in {"binary_little_endian", "binary_big_endian"}:
        raise RuntimeError(
            f"{ply_path.name} is too large to load directly in a browser and unsupported for auto-downsampling"
        )
    if not vertex_count or not vertex_stride or not vertex_properties:
        raise RuntimeError(f"Could not determine vertex layout for {ply_path.name}")
    if vertex_count <= MAX_BROWSER_POINTS:
        return None

    step = (vertex_count + MAX_BROWSER_POINTS - 1) // MAX_BROWSER_POINTS
    sampled_count = (vertex_count + step - 1) // step

    header_lines = [
        b"ply\n",
        f"format {fmt} 1.0\n".encode("ascii"),
        f"element vertex {sampled_count}\n".encode("ascii"),
    ]
    header_lines.extend(
        f"property {property_type} {property_name}\n".encode("ascii")
        for property_type, property_name in vertex_properties
    )
    header_lines.append(b"end_header\n")

    sampled = bytearray(b"".join(header_lines))
    skip_bytes = (step - 1) * vertex_stride

    with ply_path.open("rb") as handle:
        handle.seek(data_offset)
        for _ in range(sampled_count):
            record = handle.read(vertex_stride)
            if len(record) != vertex_stride:
                break
            sampled.extend(record)
            if skip_bytes:
                handle.seek(skip_bytes, 1)

    print(
        f"Downsampling {ply_path.name} for browser viewing: "
        f"{vertex_count:,} -> {sampled_count:,} points",
        flush=True,
    )
    return bytes(sampled)


def serve_ply_viewer(ply_path: Path, port: int) -> int:
    ply_path = ply_path.expanduser().resolve()
    if not ply_path.is_file():
        raise SystemExit(f"PLY file not found: {ply_path}")

    ply_bytes = _build_sampled_ply_bytes(ply_path)
    handler = _build_handler(ply_path, ply_bytes=ply_bytes)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    local_url = f"http://127.0.0.1:{port}/"

    print(f"Serving {ply_path}", flush=True)
    print(f"Open: {local_url}", flush=True)
    _print_ssh_hint(port)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

    return 0
